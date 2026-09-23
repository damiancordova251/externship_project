"""
Stage 1: pull hiring data out of the Ashby ATS via its REST API.

Writes one CSV per endpoint into private/. The one the rest of the pipeline
actually needs is private/ashby_candidate_list.csv — it carries the `school`
field that the directory is built around.

Strategy, and why it's shaped this way:

  * Only HIRED applications are pulled. The directory answers "which schools do
    our people actually come from", so applicants who weren't hired are noise.
  * Reference data (jobs, departments, locations) is pulled in parallel with the
    applications, since those four calls don't depend on each other.
  * Candidates are then fetched one-by-one but CONCURRENTLY, and only for ids
    that appear on a hired application — pulling the full candidate list would
    mean tens of thousands of records and far more PII than we need.
  * Interview feedback is deliberately NOT pulled: hires already cleared the
    bar, so scores add no ranking signal and would only widen the PII surface.

Run:  python pipeline/extract_ashby.py    (prompts for an API key)

NOTE: output contains candidate PII and lands in the git-ignored private/.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from getpass import getpass

import pandas as pd
import requests

import paths

BASE_URL = "https://api.ashbyhq.com"

LOOKBACK_YEARS = 3        # how far back to pull hires
REQUEST_TIMEOUT = 30      # seconds per request — fail fast instead of hanging
MAX_RETRIES = 3           # retry transient failures (timeouts, 429, 5xx)
CONCURRENCY = 8           # parallel workers for per-hire fetches; modest to avoid 429s

# Populated by main(); module-level so the worker functions can share one
# connection pool instead of opening a socket per request.
session = requests.Session()


def ashby_post(endpoint, payload=None):
    """POST to one Ashby endpoint, retrying only failures worth retrying.

    Rate limits (429) and server errors (5xx) get exponential backoff. Ordinary
    client errors (401, 403, 404) are raised immediately — retrying a bad key
    or a forbidden endpoint just wastes time.
    """
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(f"{BASE_URL}/{endpoint}", json=payload or {},
                                timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} transient", response=resp)
            resp.raise_for_status()
            return resp.json()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                raise
            last_err = e
            if attempt < MAX_RETRIES:
                wait = 2 ** (attempt - 1)      # 1s, 2s, 4s
                print(f"  .. [{endpoint}] {e} — retry {attempt}/{MAX_RETRIES - 1} in {wait}s")
                time.sleep(wait)
    raise last_err


def fetch_all(endpoint, extra_params=None, page_limit=100, max_pages=2000,
              verbose=True):
    """Page through a cursor-paginated Ashby endpoint until it's exhausted.

    Every loop-exit condition here is a guard against a pagination bug turning
    into an infinite loop: a repeated cursor, a missing cursor, a page that adds
    no records, or a page count cap. Returns (endpoint, records) so results can
    be matched up when these run concurrently.
    """
    all_results = []
    cursor = None
    page = 1
    seen_cursors = set()

    while True:
        if page > max_pages:
            if verbose:
                print(f"  !! [{endpoint}] hit max_pages cap — stopping.")
            break

        payload = {"limit": page_limit}
        if extra_params:
            payload.update(extra_params)
        if cursor:
            payload["cursor"] = cursor

        prev_count = len(all_results)
        data = ashby_post(endpoint, payload)
        all_results.extend(data.get("results", []))

        if not data.get("results") and data.get("moreDataAvailable"):
            if verbose:
                print(f"  !! [{endpoint}] 0 results but claims more data — stopping.")
            break
        if not data.get("moreDataAvailable"):
            break

        next_cursor = data.get("nextCursor")
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        if len(all_results) == prev_count:      # no progress; bail out
            break

        cursor = next_cursor
        page += 1
        # No sleep: this is sequential within one endpoint, and Ashby's rate
        # limit tolerates it. If you start seeing HTTP 429, add time.sleep(0.2).

    if verbose:
        print(f"  [{endpoint}] done — {len(all_results)} records")
    return endpoint, all_results


def save_csv(records, name):
    """Flatten nested JSON records into one CSV under private/.

    json_normalize turns Ashby's nested objects into dotted columns, which is
    why build_directory.py reads fields like "primaryEmailAddress.value".
    """
    if not records:
        print(f"  (skip {name}: 0 records)")
        return
    df = pd.json_normalize(records)
    out = paths.ensure_private() / f"ashby_{name.replace('.', '_')}.csv"
    df.to_csv(out, index=False)
    print(f"Saved {out.name} — {len(df)} rows, {len(df.columns)} columns")


def get_candidate_id(app):
    """Ashby returns the candidate either as a top-level id or a nested object
    depending on the endpoint version, so handle both shapes."""
    return app.get("candidateId") or (app.get("candidate") or {}).get("id")


def run_pool(label, fn, items):
    """Run fn over items with a bounded thread pool, logging progress.

    One failed item is reported and skipped rather than aborting the run — a
    single unreadable candidate shouldn't cost a multi-thousand-record pull.
    """
    out = []
    total = len(items)
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                res = fut.result()
                if isinstance(res, list):
                    out.extend(res)
                elif res:
                    out.append(res)
            except Exception as e:
                print(f"  !! {label} {futs[fut]} failed: {e}")
            if i % 100 == 0 or i == total:
                print(f"  {label}: {i}/{total}")
    return out


def main():
    api_key = getpass("Paste your Ashby API key: ")
    session.auth = (api_key, "")

    # Ashby's `createdAfter` expects a Unix timestamp in MILLISECONDS (a
    # number), not an ISO-8601 string. Passing a string silently returns 0
    # records — no error, just an empty result. Cost a while to find.
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_YEARS * 365)
    cutoff_ms = int(cutoff_dt.timestamp() * 1000)
    print(f"Pulling records created after: {cutoff_dt.isoformat()} ({cutoff_ms} ms)\n")

    start = time.time()

    # --- Phase 1: hired applications + reference data, all in parallel -------
    # offer.list is intentionally omitted: it 403s on our key and isn't needed,
    # since the hire signal comes from application.list with status=Hired.
    phase1 = [
        ("application.list", {"createdAfter": cutoff_ms, "status": "Hired"}),
        ("job.list", None),
        ("department.list", None),
        ("location.list", None),
    ]
    print("Phase 1: pulling hired applications + reference data...\n")
    results = {}
    with ThreadPoolExecutor(max_workers=len(phase1)) as executor:
        futures = {executor.submit(fetch_all, ep, params): ep for ep, params in phase1}
        for future in as_completed(futures):
            ep = futures[future]
            try:
                name, data = future.result()
                results[name] = data
            except Exception as e:
                print(f"  !! [{ep}] failed: {e}")
                results[ep] = []

    hired_apps = results.get("application.list", [])
    for name, _ in phase1:
        save_csv(results.get(name, []), name)

    # --- Phase 2: just the hired candidates, for their school field ----------
    cand_ids = sorted({cid for a in hired_apps if (cid := get_candidate_id(a))})
    print(f"\nPhase 2: {len(cand_ids)} unique hired candidates")
    if hired_apps and not cand_ids:
        print("  !! Could not locate candidate ids on applications.")
        print("     application keys seen:", list(hired_apps[0].keys()))

    print("\nFetching hired candidates (school data)...")
    candidates = run_pool(
        "candidate.info",
        lambda cid: ashby_post("candidate.info", {"id": cid}).get("results"),
        cand_ids)
    save_csv(candidates, "candidate.list")

    print(f"\nAll done in {time.time() - start:.1f} seconds.")
    print(f"CSVs are in {paths.PRIVATE}")
    print("Next:  python pipeline/build_directory.py")


if __name__ == "__main__":
    main()
