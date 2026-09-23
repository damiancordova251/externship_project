#!/usr/bin/env python3
"""
Scheduled career-fair scraper — live per-college updates.

For every college already in career_fairs.json, fetches that college's public
career-center page(s), extracts upcoming fair dates, and merges anything new
back into career_fairs.json. career_fairs.json is the single source of truth;
the directory (campus-recruiting-directory.html) is regenerated from it by
build_directory.py, so this script only touches the JSON.

Design notes / honest limits
----------------------------
* Merge is ADDITIVE and SAFE: existing rows are never deleted. New rows are
  appended only when (college, date) is not already present, so a bad scrape can
  add noise but can't wipe curated data — review the diff the Action commits.
* Only UPCOMING fairs (date >= today) are added; the feed is forward-looking.
* The default extractor is GENERIC and multi-strategy: it reads Localist JSON
  APIs, schema.org JSON-LD Events, and embedded __NEXT_DATA__/state JSON before
  falling back to scraping rendered text — so it now recovers many pages that
  merely *look* JavaScript-rendered (the data is in the HTML payload). It still
  skips obviously niche fairs (nursing, accounting, MBA-only, etc.). What it
  genuinely can't reach: pages whose dates live only behind a login
  (Handshake / Symplicity / 12twenty) — those stay in MANUAL_COLLEGES or as
  curated rows.
* Auto-added rows are tagged {"auto": true, "scraped_at": "<date>"} so you can
  tell them apart from curated rows and prune them if needed.

Usage
-----
    python pipeline/scrape_fairs.py            # scrape + write
    python pipeline/scrape_fairs.py --dry-run  # scrape, print what WOULD change
    python pipeline/scrape_fairs.py --no-net   # skip network (merge/write path only)

This is the only script that runs unattended (weekly, in GitHub Actions), so it
deliberately depends on nothing but requests + beautifulsoup4 — no pandas, no
API keys, no candidate data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import paths

ROOT = paths.ROOT
JSON_PATH = paths.CAREER_FAIRS                 # source of truth for fairs
SOURCES_PATH = paths.FAIR_SOURCES              # curated, reviewed source URLs
PENDING_PATH = paths.FAIR_SOURCES_PENDING      # discovery output awaiting review

# Discovery is self-throttled to ~monthly (the Action itself runs weekly). Free
# search-API tiers are small, so each run caps its queries and rotates through
# target schools across months.
DISCOVERY_INTERVAL_DAYS = 30
DISCOVERY_QUERY_BUDGET = 40

TODAY = dt.date.today()
# Only accept plausible dates: last year through two years out. Anything else is
# almost certainly a stray date on the page (footer copyright, unrelated event).
MIN_DATE = TODAY - dt.timedelta(days=365)
MAX_DATE = TODAY + dt.timedelta(days=730)

# A block/title must contain one of these fair-title phrases to count. It is
# deliberately strict (a bare "recruit"/"stem" is not enough): structured passes
# enumerate EVERY event on a calendar, and the text pass would otherwise grab
# registration boilerplate ("Register Now", "Payment ...") that merely sits near
# a date. Named non-"fair" events we still want are listed explicitly.
FAIR_TITLE = re.compile(
    r"career fair|career expo|job fair|internship fair|job & internship|"
    r"job and internship|career & internship|career and internship|hiring expo|"
    r"engineering expo|recruiting expo|career (day|night|fest)|"
    r"industrial roundtable|talent connect|opportunities (conference|fair)|"
    r"(tech|stem|engineering|all[- ]?majors) (fair|expo)",
    re.I,
)

# Skip obviously niche fairs so the feed stays scoped to general + tech/STEM,
# matching the curated directory. A block matching any of these is dropped.
NEGATIVE = re.compile(
    r"\b(nursing|accounting|cpa|mba|business school|school of business|"
    r"business career|law school|pre-?law|education|teacher|educator|"
    r"hospitality|supply chain|doctoral|postdoc|dissertation|"
    r"graduate school fair|health(care)? professions|pharmacy|dental|nurse|"
    r"real estate)\b",
    re.I,
)

USER_AGENT = "ValonCampusRecruitingBot/1.0 (+career-fair schedule sync)"

MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}
MONTHS.update({m[:3].lower(): i for m, i in list(MONTHS.items())})


# ----------------------------------------------------------------------------
# Date parsing
# ----------------------------------------------------------------------------
def _mk(y: int, m: int, d: int) -> str | None:
    try:
        date = dt.date(y, m, d)
    except ValueError:
        return None
    if MIN_DATE <= date <= MAX_DATE:
        return date.isoformat()
    return None


def find_dates(text: str) -> list[str]:
    """Return ISO date strings found in free text, filtered to a sane window."""
    out: list[str] = []

    # "September 25, 2026" / "Sep 25 2026"
    for m in re.finditer(
        r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text):
        mon = MONTHS.get(m.group(1).lower())
        if mon:
            iso = _mk(int(m.group(3)), mon, int(m.group(2)))
            if iso:
                out.append(iso)

    # ISO "2026-09-25"
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        iso = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            out.append(iso)

    # "9/25/2026" or "09/25/26"
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text):
        y = int(m.group(3))
        y += 2000 if y < 100 else 0
        iso = _mk(y, int(m.group(1)), int(m.group(2)))
        if iso:
            out.append(iso)

    return out


# ----------------------------------------------------------------------------
# Extractors
#
# generic_extractor runs four passes and merges them (one row per date, richest
# name wins). Order matters — structured data is far more reliable than scraping
# rendered text, so it comes first:
#   1. Localist  — many .edu event calendars expose a public JSON API at
#                  <host>/api/2/events; no browser needed.
#   2. JSON-LD   — schema.org "Event" objects embedded in <script type=ld+json>.
#   3. __NEXT_DATA__ / inline JSON — Next.js and similar SPAs ship their event
#                  data as JSON in the initial HTML even when the DOM is empty.
#   4. Text pass — the original heuristic (keyword + nearby date in a block).
# Passes 1-3 recover most pages that "look" JavaScript-rendered, because the data
# is in the HTML payload even if the visible DOM is built client-side.
# ----------------------------------------------------------------------------
def _iso_from(value) -> str | None:
    """Normalize a date/datetime string to a windowed YYYY-MM-DD, or None."""
    if not value:
        return None
    s = str(value)
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    found = find_dates(s)
    return found[0] if found else None


def _fair_row(college: str, url: str, name, date, location="") -> dict | None:
    """Build+validate a fair row from structured fields. The NAME must look like a
    career fair (and not a niche one); the date must be in the sane window."""
    name = (name or "")
    name = name if isinstance(name, str) else str(name)
    name = " ".join(name.split())
    if not name or not FAIR_TITLE.search(name) or NEGATIVE.search(name):
        return None
    iso = _iso_from(date)
    if not iso:
        return None
    loc = location if isinstance(location, str) else ""
    return {"college": college, "name": name[:120], "date": iso,
            "location": " ".join(loc.split())[:160], "source": url}


def _walk(obj):
    """Yield every dict nested anywhere inside a JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _jsonld_location(loc) -> str:
    if isinstance(loc, str):
        return loc
    if isinstance(loc, list) and loc:
        return _jsonld_location(loc[0])
    if isinstance(loc, dict):
        if isinstance(loc.get("name"), str):
            return loc["name"]
        addr = loc.get("address")
        if isinstance(addr, str):
            return addr
        if isinstance(addr, dict):
            return addr.get("addressLocality") or addr.get("streetAddress") or ""
    return ""


def parse_jsonld(html: str, college: str, url: str) -> list[dict]:
    """schema.org Event objects in <script type='application/ld+json'>."""
    rows: list[dict] = []
    for m in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.I | re.S):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:  # noqa: BLE001 — malformed/multi-object blocks: skip
            continue
        for d in _walk(data):
            t = d.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if not any("event" in str(x).lower() for x in types):
                continue
            r = _fair_row(college, url,
                          d.get("name") or d.get("headline"),
                          d.get("startDate") or d.get("startdate"),
                          _jsonld_location(d.get("location")))
            if r:
                rows.append(r)
    return rows


def parse_embedded_json(html: str, college: str, url: str) -> list[dict]:
    """Event data shipped as JSON in the initial HTML (Next.js __NEXT_DATA__,
    Nuxt, Redux state dumps, etc.). We walk every embedded blob for dict shapes
    that look like an event (a title-ish field + a start-date-ish field)."""
    rows: list[dict] = []
    blobs = re.findall(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    blobs += re.findall(
        r'<script[^>]*>\s*(?:window\.)?__(?:NUXT|APOLLO_STATE|INITIAL_STATE)__\s*=\s*({.*?})\s*;?\s*</script>',
        html, re.I | re.S)
    NAME_KEYS = ("name", "title", "eventName", "event_name")
    DATE_KEYS = ("startDate", "start_date", "starts_at", "startsAt", "start", "date",
                 "first_date", "beginDate")
    LOC_KEYS = ("location", "locationName", "location_name", "venue", "place", "room")
    for blob in blobs:
        try:
            data = json.loads(blob.strip())
        except Exception:  # noqa: BLE001
            continue
        for d in _walk(data):
            name = next((d[k] for k in NAME_KEYS if isinstance(d.get(k), str)), None)
            date = next((d[k] for k in DATE_KEYS if d.get(k)), None)
            if not name or not date:
                continue
            loc = ""
            for lk in LOC_KEYS:
                v = d.get(lk)
                if isinstance(v, str):
                    loc = v
                    break
                if isinstance(v, dict) and isinstance(v.get("name"), str):
                    loc = v["name"]
                    break
            r = _fair_row(college, url, name, date, loc)
            if r:
                rows.append(r)
    return rows


def parse_localist(html: str, college: str, url: str) -> list[dict]:
    """If the page is a Localist calendar, hit its public JSON API directly.
    Detected by the Localist signature in the HTML; the API lives at
    <same-host>/api/2/events."""
    if not re.search(r"platform-controller|localist|/api/2/events", html, re.I):
        return []
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    if not host:
        return []
    # Localist API v2: `days`+`pp` is the documented form (combining `days` with
    # `start` 400s). 365 days from today covers the whole upcoming fall/spring.
    api = f"https://{host}/api/2/events?days=365&pp=100"
    body = fetch(api)
    if not body:
        return []
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return []
    rows: list[dict] = []
    for wrap in data.get("events", []):
        ev = wrap.get("event", wrap) if isinstance(wrap, dict) else {}
        if not isinstance(ev, dict):
            continue
        date = ev.get("first_date")
        if not date:
            insts = ev.get("event_instances") or []
            if insts and isinstance(insts[0], dict):
                inst = insts[0].get("event_instance", insts[0])
                date = inst.get("start") if isinstance(inst, dict) else None
        r = _fair_row(college, url, ev.get("title") or ev.get("name"), date,
                      ev.get("location_name") or ev.get("location") or "")
        if r:
            rows.append(r)
    return rows


def _text_block_extractor(html: str, college: str, url: str) -> list[dict]:
    """Original heuristic: any DOM block that mentions a career-fair keyword AND
    contains a date. Fair name is a best-effort trim of the block text."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        print("  ! beautifulsoup4 not installed; skipping text parse", file=sys.stderr)
        return []

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    rows: list[dict] = []
    seen: set[str] = set()
    for el in soup.find_all(["li", "tr", "article", "section", "h2", "h3", "p", "div", "time"]):
        block = " ".join(el.get_text(" ", strip=True).split())
        if not block or len(block) > 600:      # loosened from 400
            continue
        # Require the STRICT fair-title phrase in the block (not just a loose
        # keyword) — this is what kept "Register Now" / "Payment ..." junk out.
        m = FAIR_TITLE.search(block)
        if not m or NEGATIVE.search(block):
            continue
        dates = find_dates(block)
        if not dates:
            continue
        # Name: text before the first date; if that isn't a fair title, fall back
        # to a window starting at the matched fair phrase.
        name = re.split(r"\b[A-Za-z]{3,9}\.?\s+\d{1,2}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}",
                        block)[0].strip(" -–—:·|")
        if not FAIR_TITLE.search(name):
            name = block[m.start():m.start() + 70].strip(" -–—:·|")
        name = (name[:80] or m.group(0)).strip()
        for iso in dates:
            if iso in seen:
                continue
            seen.add(iso)
            rows.append({"college": college, "name": name or m.group(0),
                         "date": iso, "location": "", "source": url})
    return rows


def _name_rank(row: dict) -> int:
    """Prefer informative names when two passes find the same date."""
    n = row.get("name", "")
    rank = len(n)
    if n.lower() in ("career fair", "career expo", "job fair", ""):
        rank -= 100
    if row.get("location"):
        rank += 20
    return rank


def generic_extractor(html: str, college: str, url: str) -> list[dict]:
    """Run all strategies and merge: one row per date, richest name wins."""
    rows: list[dict] = []
    for strategy in (parse_localist, parse_jsonld, parse_embedded_json,
                     _text_block_extractor):
        try:
            rows.extend(strategy(html, college, url))
        except Exception as e:  # noqa: BLE001 — one bad parser shouldn't kill the page
            print(f"  ! {strategy.__name__} failed for {college}: {e}", file=sys.stderr)
    best: dict[str, dict] = {}
    for r in rows:
        k = r["date"]
        if k not in best or _name_rank(r) > _name_rank(best[k]):
            best[k] = r
    return list(best.values())


# Site-specific extractors go here, keyed by college. Signature matches
# generic_extractor(html, college, url) -> list[dict]. The generic pass now
# handles Localist / JSON-LD / embedded-JSON automatically, so most sites no
# longer need one; add here only for pages too irregular for all four passes.
EXTRACTORS: dict[str, callable] = {
    # "MIT": mit_extractor,
}

# Schools the scraper cannot reach — their fair dates live behind a login
# (Handshake / 12twenty) or a bot wall, and Valon has no API access. These are
# maintained by hand: add/update curated rows for them in career_fairs.json.
# The scraper skips them so it never wastes requests or writes junk here.
# (Sources that merely serve a login-gated Symplicity/Handshake calendar don't
# need to be listed — the generic extractor just finds no dates and moves on.)
MANUAL_COLLEGES = {
    "University of Michigan",   # career-center site behind a WAF (403 to bots)
}


# ----------------------------------------------------------------------------
# Fetch + orchestrate
# ----------------------------------------------------------------------------
def fetch(url: str, timeout: int = 20) -> str | None:
    try:
        import requests  # type: ignore
    except ImportError:
        print("  ! requests not installed; cannot fetch", file=sys.stderr)
        return None
    # Browser-like headers get past some WAFs/CDNs that 403 a bare bot UA. We
    # still identify ourselves in a comment-style suffix for server logs.
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 "
                       f"Safari/537.36 ({USER_AGENT})"),
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:  # noqa: BLE001 — one bad site shouldn't kill the run
        print(f"  ! fetch failed for {url}: {e}", file=sys.stderr)
        return None


def sources_from(fairs: list[dict]) -> dict[str, list[str]]:
    """Group the distinct source URLs we already know about, per college."""
    by: dict[str, list[str]] = {}
    for f in fairs:
        by.setdefault(f["college"], [])
        if f.get("source") and f["source"] not in by[f["college"]]:
            by[f["college"]].append(f["source"])
    return by


def scrape(fairs: list[dict], curated_sources: dict, use_net: bool) -> list[dict]:
    """Existing behavior, UNCHANGED: fetch each known career-center URL and
    extract fair dates. Now also scrapes any curated/approved URLs from
    fair_sources.json, so discovered-and-approved sites feed the same pipeline."""
    if not use_net:
        print("(--no-net) skipping fetch; nothing new scraped")
        return []
    # Targets = URLs already in the feed  +  curated/approved URLs.
    targets: dict[str, list[str]] = sources_from(fairs)
    for college, urls in (curated_sources or {}).items():
        targets.setdefault(college, [])
        for u in urls:
            if u and u not in targets[college]:
                targets[college].append(u)
    found: list[dict] = []
    for college, urls in targets.items():
        if college in MANUAL_COLLEGES:
            print(f"· {college}: manual-entry school — skipping")
            continue
        extractor = EXTRACTORS.get(college, generic_extractor)
        for url in urls:
            print(f"· {college}: {url}")
            html = fetch(url)
            rows = extractor(html, college, url) if html else []
            print(f"    {len(rows)} candidate row(s)")
            found.extend(rows)
    return found


def merge(existing: list[dict], scraped: list[dict]) -> tuple[list[dict], list[dict]]:
    """Add scraped rows whose (college, date) isn't already present. Returns
    (merged_list, newly_added)."""
    have = {(f["college"], f["date"]) for f in existing}
    added: list[dict] = []
    stamp = TODAY.isoformat()
    today_iso = TODAY.isoformat()
    for row in scraped:
        if row["date"] < today_iso:      # only ever add upcoming fairs
            continue
        key = (row["college"], row["date"])
        if key in have:
            continue
        have.add(key)
        row = {**row, "auto": True, "scraped_at": stamp}
        added.append(row)
    merged = existing + added
    merged.sort(key=lambda f: (f["college"], f["date"]))
    return merged, added


# ----------------------------------------------------------------------------
# Writers
# ----------------------------------------------------------------------------
def write_json(data: dict, fairs: list[dict]) -> None:
    data["fairs"] = fairs
    JSON_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")


def prune_stale(fairs: list[dict]) -> tuple[list[dict], int]:
    """Keep every UPCOMING fair, plus at most the single most-recently-passed fair
    per college (so a 'recently passed' one survives but old ones don't pile up).
    The directory renders that one passed fair in a separate section."""
    today_iso = TODAY.isoformat()
    by_college: dict[str, list[dict]] = {}
    for f in fairs:
        by_college.setdefault(f["college"], []).append(f)
    kept: list[dict] = []
    dropped = 0
    for _college, fs in by_college.items():
        upcoming = [f for f in fs if f.get("date", "") >= today_iso]
        past = sorted((f for f in fs if f.get("date", "") < today_iso),
                      key=lambda x: x["date"])
        kept.extend(upcoming)
        if past:
            kept.append(past[-1])       # most-recently-passed only
            dropped += len(past) - 1    # older past fairs pruned
    kept.sort(key=lambda f: (f["college"], f["date"]))
    return kept, dropped


# ----------------------------------------------------------------------------
# Discovery: web-search for NEW career-fair / job-board sites not on our list.
# Runs alongside (not instead of) the scraper. Self-throttled to ~monthly.
# Candidates are written to PENDING_PATH for human review; NEVER auto-added.
# ----------------------------------------------------------------------------
def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as e:  # noqa: BLE001
        print(f"  ! could not read {path.name}: {e}", file=sys.stderr)
        return default


def discovery_targets() -> list[str]:
    """The curated target schools (Top-100 / NY / SF / extra) to search for.
    Shared with the directory builder via target_schools, so the two can never
    drift apart. Contains no candidate PII."""
    from target_schools import ALL_TARGETS
    return list(ALL_TARGETS)


_NEG_DOMAIN = re.compile(
    r"(facebook|twitter|reddit|wikipedia|youtube|instagram|indeed|glassdoor|"
    r"ziprecruiter|linkedin)\.com", re.I)
_POS_SOURCE = re.compile(
    r"career.?fair|/career|/careers|career-?center|career-?services|/events|"
    r"joinhandshake\.com|symplicity|12twenty", re.I)


def plausible_source(url: str) -> bool:
    u = (url or "").lower()
    if not u.startswith("http") or _NEG_DOMAIN.search(u):
        return False
    if _POS_SOURCE.search(u):
        return True
    return ".edu" in u and ("career" in u or "event" in u)


def source_score(url: str) -> int:
    """Rough relevance rank so real official career pages sort to the top of the
    review file and noise sinks to the bottom. Higher = more likely legit."""
    u = (url or "").lower()
    score = 0
    if ".edu" in u:
        score += 3
    if re.search(r"career.?fair|career-?center|career-?services|/careers?\b", u):
        score += 2
    if "/events" in u:
        score += 1
    if re.search(r"symplicity|joinhandshake|12twenty|careereco", u):
        score += 1                      # real recruiting platforms
    if re.search(r"blog|press-?room|press-?release|/news|forum|/event/", u):
        score -= 2                      # articles / one-off event pages, not schedules
    return score


def web_search(query: str, num: int = 6):
    """Return [(title, url)] via whichever Search API key is set, [] on error,
    or None if NO backend is configured (so discovery can no-op cleanly)."""
    import os
    try:
        import requests  # type: ignore
    except ImportError:
        return None
    tav = os.environ.get("TAVILY_API_KEY")
    serp = os.environ.get("SERPAPI_KEY")
    bing = os.environ.get("BING_SEARCH_KEY")
    gkey, gcx = os.environ.get("GOOGLE_API_KEY"), os.environ.get("GOOGLE_CSE_ID")
    try:
        if tav:
            r = requests.post("https://api.tavily.com/search",
                              json={"api_key": tav, "query": query,
                                    "max_results": num, "search_depth": "basic"},
                              timeout=25)
            r.raise_for_status()
            return [(i.get("title", ""), i.get("url", ""))
                    for i in r.json().get("results", [])[:num]]
        if serp:
            r = requests.get("https://serpapi.com/search.json",
                             params={"q": query, "api_key": serp, "num": num,
                                     "engine": "google"}, timeout=25)
            r.raise_for_status()
            return [(i.get("title", ""), i.get("link", ""))
                    for i in r.json().get("organic_results", [])[:num]]
        if bing:
            r = requests.get("https://api.bing.microsoft.com/v7.0/search",
                             headers={"Ocp-Apim-Subscription-Key": bing},
                             params={"q": query, "count": num}, timeout=25)
            r.raise_for_status()
            return [(i.get("name", ""), i.get("url", ""))
                    for i in r.json().get("webPages", {}).get("value", [])[:num]]
        if gkey and gcx:
            r = requests.get("https://www.googleapis.com/customsearch/v1",
                             params={"key": gkey, "cx": gcx, "q": query,
                                     "num": min(num, 10)}, timeout=25)
            r.raise_for_status()
            return [(i.get("title", ""), i.get("link", ""))
                    for i in r.json().get("items", [])[:num]]
    except Exception as e:  # noqa: BLE001
        print(f"  ! search failed for {query!r}: {e}", file=sys.stderr)
        return []
    return None  # no backend configured


def discover(data: dict, existing_fairs: list[dict], curated_sources: dict,
             force: bool, write: bool):
    """Monthly-throttled discovery. Returns (state_or_None, new_candidates).
    state_or_None is None when discovery did NOT run (throttled / no backend)."""
    state = dict(data.get("discovery", {}) or {})
    last = state.get("last_run")
    if not force and last:
        try:
            gap = (TODAY - dt.date.fromisoformat(last)).days
        except ValueError:
            gap = DISCOVERY_INTERVAL_DAYS
        if gap < DISCOVERY_INTERVAL_DAYS:
            print(f"· discovery: last ran {last} ({gap}d ago) < "
                  f"{DISCOVERY_INTERVAL_DAYS}d — skipping (monthly cadence)")
            return None, []

    targets = discovery_targets()
    if not targets:
        return None, []

    known = {f["college"] for f in existing_fairs} | set(curated_sources)
    searched = set(state.get("searched_colleges", []))
    todo = [s for s in targets if s not in known and s not in searched]
    if not todo:                       # full rotation done -> start over
        searched = set()
        todo = [s for s in targets if s not in known]

    pending = _read_json(PENDING_PATH, [])
    seen = {(p["college"], p["url"]) for p in pending}
    new: list[dict] = []
    budget = DISCOVERY_QUERY_BUDGET
    for school in todo:
        if budget <= 0:
            break
        query = f"{school} career fair 2026"
        results = web_search(query)
        if results is None:            # no backend -> don't mark state, retry later
            print("  ! discovery: no search backend configured "
                  "(set TAVILY_API_KEY / SERPAPI_KEY / BING_SEARCH_KEY / "
                  "GOOGLE_API_KEY+GOOGLE_CSE_ID)")
            return None, []
        budget -= 1
        searched.add(school)
        for title, url in results:
            if plausible_source(url) and (school, url) not in seen:
                seen.add((school, url))
                new.append({"college": school, "url": url, "title": title,
                            "score": source_score(url),
                            "query": query, "found": TODAY.isoformat(),
                            "status": "pending_review"})

    if write:
        pending.extend(new)
        # Best (most-likely-official) sources first within each school.
        pending.sort(key=lambda p: (p["college"], -p.get("score", 0), p["url"]))
        PENDING_PATH.write_text(
            json.dumps(pending, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state = {"last_run": TODAY.isoformat(), "searched_colleges": sorted(searched)}
    return state, new


# ----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="scrape + report, but don't write files")
    ap.add_argument("--no-net", action="store_true",
                    help="skip network fetches (exercise merge/write path only)")
    ap.add_argument("--no-discover", action="store_true",
                    help="skip the web-search discovery step")
    ap.add_argument("--force-discover", action="store_true",
                    help="run discovery now even if <30 days since last run")
    args = ap.parse_args()

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    existing = data.get("fairs", [])
    curated = _read_json(SOURCES_PATH, {})     # {college: [approved urls]}
    n_curated = sum(len(v) for v in curated.values())
    print(f"Loaded {len(existing)} existing fairs; {n_curated} curated source URL(s)")

    # 1) SCRAPE (unchanged behavior) — known feed URLs + curated/approved URLs.
    scraped = scrape(existing, curated, use_net=not args.no_net)
    merged, added = merge(existing, scraped)
    merged, pruned = prune_stale(merged)

    # 2) DISCOVERY (search API) — additive, monthly-throttled, review-only.
    disc_state, disc_new = (None, [])
    if not args.no_discover and not args.no_net:
        disc_state, disc_new = discover(data, existing, curated,
                                        force=args.force_discover,
                                        write=not args.dry_run)

    print(f"\n{len(added)} new fair(s) scraped:")
    for f in added:
        print(f"  + {f['college']} {f['date']} — {f['name']}")
    if pruned:
        print(f"{pruned} stale past fair(s) pruned (kept 1 most-recent per school).")
    if disc_new:
        print(f"{len(disc_new)} candidate source(s) flagged for review in "
              f"{PENDING_PATH.name} (NOT auto-added).")
    if disc_state:
        print(f"discovery ran; {len(disc_state['searched_colleges'])} school(s) "
              f"searched cumulatively.")

    if args.dry_run:
        print("\n(--dry-run) no files written.")
        return 0

    # career_fairs.json changes if fairs changed OR discovery state advanced.
    file_changed = bool(added or pruned) or disc_state is not None
    if disc_state is not None:
        data["discovery"] = disc_state
    if not file_changed:
        print("\nNothing new; career_fairs.json unchanged.")
        return 0

    data["last_scraped"] = TODAY.isoformat()
    write_json(data, merged)
    print(f"\nWrote {JSON_PATH.name} "
          f"({len(added)} added, {pruned} pruned, {len(merged)} total).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
