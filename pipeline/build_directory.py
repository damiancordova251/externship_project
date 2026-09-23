"""
Build the Campus Recruiting Directory page.

    inputs                                          output
    ------                                          ------
    private/ashby_candidate_list.csv   (hires)  ->  private/campus-recruiting-
    data/career_fairs.json             (fairs)      directory.html
    private/current_employees.json     (roster)     (self-contained, data inlined)
    private/ashby_overrides.json       (fixes)

What it does, in order:

  1. Reads every hired candidate out of the Ashby CSV export.
  2. Normalizes each alma mater through target_schools.canonicalize(), which
     handles casing, aliases, sub-colleges, and multi-school cells.
  3. Counts DISTINCT people per school (the CSV has duplicate candidate records
     for the same person, so a raw row count over-reports).
  4. Unions in every target school from the inclusion criteria, even ones with
     zero hires — those render with an empty state, and they're precisely the
     schools worth recruiting at.
  5. Attaches each school's upcoming career fairs from career_fairs.json.
  6. Inlines the whole payload as JSON into the HTML template and writes it out.

Run:  python pipeline/build_directory.py

NOTE: the output contains real candidate PII. It is written to private/, which
is git-ignored in its entirety. Keep it that way.
"""

import ast
import datetime as dt
import html
import json
import re
from collections import defaultdict

import pandas as pd

import paths
from directory_template import TEMPLATE
from target_schools import (AMBIGUOUS, EXTRA_KEYS, NY_KEYS, OFFICIAL,
                            RANKING_SOURCE, REMOVABLE_AMBIGUOUS, SF_KEYS,
                            TOP_KEYS, canonicalize)


# --- Small helpers -----------------------------------------------------------

def _name_key(s):
    """Normalized key for matching a person's name (roster <-> hire)."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower())).strip()


def parse(v):
    """Read back a Python literal that pandas stored as a string (Ashby's
    nested fields arrive as "[{'type': 'linkedin', ...}]"). Falls back to the
    raw value if it isn't a literal."""
    if pd.isna(v):
        return None
    try:
        return ast.literal_eval(v)
    except Exception:
        return v


def _contact_sig(c):
    """Signature used to de-duplicate a contact. Phone numbers compare by digits
    only, so '623-853-6555' and '6238536555' are recognized as the same."""
    v = str(c.get("value", "")).strip().lower()
    if c.get("kind") == "phone":
        return "phone:" + re.sub(r"\D", "", v)
    return f"{c.get('kind', '')}:{v}"


# --- Loading the git-ignored side inputs -------------------------------------

def load_overrides():
    """Manual per-candidate school corrections, keyed by Ashby candidate id.

    Lives in a git-ignored file so candidate ids never land in tracked code.
    Format: {"candidate-id": "Real University Name", ...}. Populated by
    reviewing the output of enrich_resumes.py.
    """
    try:
        with open(paths.SCHOOL_OVERRIDES) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load_current_employees(roster_path=None):
    """Names of confirmed current employees (git-ignored; employee PII).

    A hire whose name is in this set renders under "Current Employees";
    everyone else renders under "Past Hires".
    """
    try:
        with open(roster_path or paths.CURRENT_EMPLOYEES) as f:
            return {_name_key(n) for n in json.load(f)}
    except FileNotFoundError:
        return set()


def load_fairs():
    """Load career_fairs.json and group fairs by school match key.

    Feed college names resolve through the same alias/official normalization as
    the CSV, so the feed may use official names or known aliases interchangeably.

    Per school we keep every UPCOMING fair plus at most the single
    most-recently-passed one — the template shows that last one in a "recently
    passed" section so a school with nothing scheduled still shows a signal.
    """
    try:
        with open(paths.CAREER_FAIRS) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"! {paths.CAREER_FAIRS.name} not found; directory will have no fairs")
        return {}, {}

    today = dt.date.today().isoformat()
    by_key = defaultdict(list)
    for fair in data.get("fairs", []):
        matches = canonicalize(fair.get("college", ""))
        if not matches:
            continue
        _, k = matches[0]
        by_key[k].append({
            "name": fair.get("name", "Career fair"),
            "date": fair["date"],
            "location": fair.get("location", ""),
            "source": fair.get("source", ""),
        })

    trimmed = {}
    for k, fs in by_key.items():
        fs.sort(key=lambda x: x["date"])
        upcoming = [f for f in fs if f["date"] >= today]
        past = [f for f in fs if f["date"] < today]
        keep = upcoming + past[-1:]        # past[-1] = the most recent one
        keep.sort(key=lambda x: x["date"])
        trimmed[k] = keep

    meta = {"note": data.get("note", ""), "lastScraped": data.get("last_scraped")}
    return trimmed, meta


# --- Per-candidate extraction ------------------------------------------------

def extract_contacts(row):
    """Ordered list of the contact methods we actually have for one hire.

    Anything missing is simply omitted, so the page never renders empty fields.
    Phone numbers are deliberately excluded: the directory is for email outreach
    and there's no reason to spread phone numbers around.
    """
    contacts = []
    email = row.get("primaryEmailAddress.value")
    if pd.notna(email):
        contacts.append({"kind": "email", "label": "Email",
                         "value": str(email), "href": f"mailto:{email}"})

    social = parse(row.get("socialLinks"))
    if isinstance(social, list):
        want = {"linkedin": "LinkedIn", "github": "GitHub",
                "website": "Website", "twitter": "Twitter"}
        for item in social:
            if not isinstance(item, dict):
                continue
            t = str(item.get("type", "")).lower()
            url = item.get("url")
            if url and t in want:
                contacts.append({"kind": t, "label": want[t],
                                 "value": url, "href": url})

    profile_url = row.get("profileUrl")
    if pd.notna(profile_url):
        contacts.append({"kind": "ashby", "label": "Ashby profile",
                         "value": str(profile_url), "href": str(profile_url)})
    return contacts


def dedupe_hires(hires):
    """Collapse duplicate candidate records for the SAME person at one school.

    Two records merge only when they share a name AND at least one email or
    phone (compared ignoring formatting). Contacts are unioned, so merging never
    loses information. Two different people who happen to share a name but no
    contact details stay separate — the cautious direction to err in.
    """
    buckets = []   # [{"key": name_key, "sigs": {...}, "hire": {...}}, ...]
    for h in hires:
        key = _name_key(h["name"]) if h.get("name") else None
        sigs = {_contact_sig(c) for c in h.get("contacts", [])
                if c.get("kind") in ("email", "phone")}

        target = None
        if key:
            for b in buckets:
                if b["key"] == key and (sigs & b["sigs"]):
                    target = b
                    break

        if target is None:
            buckets.append({"key": key, "sigs": set(sigs),
                            "hire": {"name": h.get("name"),
                                     "current": bool(h.get("current")),
                                     "contacts": list(h.get("contacts", []))}})
        else:
            target["sigs"] |= sigs
            target["hire"]["current"] = (target["hire"]["current"]
                                         or bool(h.get("current")))
            have = {_contact_sig(c) for c in target["hire"]["contacts"]}
            for c in h.get("contacts", []):
                s = _contact_sig(c)
                if s not in have:
                    have.add(s)
                    target["hire"]["contacts"].append(c)
    return [b["hire"] for b in buckets]


# --- Assembly ----------------------------------------------------------------

def collect_schools(df, overrides, current_employees):
    """Group every candidate row into {match_key: record} buckets by school."""
    schools = defaultdict(lambda: {"keys_seen": defaultdict(int),
                                   "person_ids": set(), "hires": []})
    missing_school = 0

    for _, row in df.iterrows():
        raw = row.get("school")
        if pd.isna(raw) or not str(raw).strip():
            missing_school += 1
            continue

        pid = row.get("id")
        contacts = extract_contacts(row)
        name = row.get("name")
        hire = {"name": (None if pd.isna(name) else str(name)),
                "current": (pd.notna(name)
                            and _name_key(name) in current_employees),
                "contacts": contacts}

        raw_eff = overrides.get(pid, raw)     # a manual correction always wins
        has_linkedin = any(c["kind"] == "linkedin" for c in contacts)

        for disp, k in canonicalize(raw_eff):
            # Unverifiable school and no LinkedIn to check it against: skip the
            # person rather than file them under a school they may not attend.
            if k in REMOVABLE_AMBIGUOUS and not has_linkedin:
                continue
            rec = schools[k]
            rec["keys_seen"][disp] += 1       # vote on the best display spelling
            if pid not in rec["person_ids"]:  # count each person once per school
                rec["person_ids"].add(pid)
                rec["hires"].append(hire)

    return schools, missing_school


def finalize(schools, fairs_by_key):
    """Turn the raw buckets into the sorted, tagged list the template renders."""
    today = dt.date.today().isoformat()
    out = []

    for k, rec in schools.items():
        # Pick a display name: an explicit label, then the official name, then
        # the spelling most candidates used (longest wins ties, as the longer
        # spelling is usually the more complete one).
        if k in AMBIGUOUS:
            display = AMBIGUOUS[k]
        elif OFFICIAL.get(k):
            display = OFFICIAL[k]
        elif rec["keys_seen"]:
            display = max(rec["keys_seen"].items(),
                          key=lambda kv: (kv[1], len(kv[0])))[0]
        else:
            display = k.title()

        fairs = fairs_by_key.get(k, [])

        # Tags drive the filter pills in the page.
        criteria = []
        if k in TOP_KEYS:
            criteria.append("ranked")
        if k in NY_KEYS:
            criteria.append("ny")
        if k in SF_KEYS:
            criteria.append("sf")
        if k in EXTRA_KEYS:
            criteria.append("extra")
        if any(f["date"] >= today for f in fairs):   # an UPCOMING fair, not past
            criteria.append("fair")
        if rec["hires"]:
            criteria.append("hired")

        deduped = dedupe_hires(rec["hires"])
        out.append({
            "name": display,
            "count": len(deduped),              # distinct PEOPLE, not raw rows
            "criteria": criteria,
            "fairs": fairs,
            "hires": sorted(deduped, key=lambda h: (h["name"] or "").lower()),
        })

    out.sort(key=lambda s: (-s["count"], s["name"].lower()))
    return out


def print_stats(df, out, missing_school):
    """Aggregate-only build summary — counts, never names."""
    total_schools = len(out)
    with_hires = sum(1 for s in out if s["count"] > 0)
    fair_schools = sum(1 for s in out if "fair" in s["criteria"])
    fair_count = sum(len(s["fairs"]) for s in out)

    print(f"Candidates in CSV:        {len(df)}")
    print(f"  missing school:         {missing_school}")
    print(f"Schools in directory:     {total_schools}")
    print(f"  with >=1 hire:          {with_hires}")
    print(f"  0-hire (target only):   {total_schools - with_hires}")
    print(f"  ranked (Top-100):       {sum(1 for s in out if 'ranked' in s['criteria'])}")
    print(f"  NY 4-year:              {sum(1 for s in out if 'ny' in s['criteria'])}")
    print(f"  SF 4-year:              {sum(1 for s in out if 'sf' in s['criteria'])}")
    print(f"  extra (fair coverage):  {sum(1 for s in out if 'extra' in s['criteria'])}")
    print(f"  with upcoming fair:     {fair_schools} ({fair_count} fairs total)")
    print("Top 5 by hires:           "
          + ", ".join(f"{s['name']} ({s['count']})" for s in out[:5]))

    return total_schools, with_hires, fair_schools, fair_count


def main(csv_path=None, out_path=None, roster_path=None):
    csv_path = csv_path or paths.CANDIDATES_CSV
    out_path = out_path or paths.DIRECTORY_HTML

    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except FileNotFoundError:
        raise SystemExit(
            f"Missing input: {csv_path}\n"
            f"  Export it first with:  python pipeline/extract_ashby.py\n"
            f"  Or run the pipeline on synthetic demo data (no API key needed):\n"
            f"    python pipeline/build_directory.py --sample")

    schools, missing_school = collect_schools(
        df, load_overrides(), load_current_employees(roster_path))

    fairs_by_key, fairs_meta = load_fairs()

    # Seed zero-hire target schools so they still get a row. Schools that only
    # appear in the fair feed are included too.
    for k in TOP_KEYS | NY_KEYS | SF_KEYS | EXTRA_KEYS | set(fairs_by_key):
        schools[k]          # touch the defaultdict to create an empty record

    out = finalize(schools, fairs_by_key)
    total_schools, with_hires, fair_schools, fair_count = print_stats(
        df, out, missing_school)

    payload = {"generatedFrom": csv_path.name, "rankingSource": RANKING_SOURCE,
               "totalSchools": total_schools, "schoolsWithHires": with_hires,
               "candidateCount": int(len(df)), "missingSchool": int(missing_school),
               "schoolsWithFair": fair_schools, "fairCount": fair_count,
               "fairsMeta": fairs_meta, "schools": out}

    page = TEMPLATE.replace("__DATA__", json.dumps(payload))
    page = page.replace("__RANKING_SOURCE__", html.escape(RANKING_SOURCE))

    paths.ensure_private()
    out_path.write_text(page, encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    import sys
    # --sample builds from the committed synthetic roster, so the pipeline can
    # be run and demoed end to end with no API key and no real candidate data.
    # Career-fair data is real either way — it comes from data/career_fairs.json.
    if "--sample" in sys.argv:
        main(csv_path=paths.SAMPLE_CANDIDATES,
             out_path=paths.PRIVATE / "sample-directory.html",
             roster_path=paths.SAMPLE_EMPLOYEES)
    else:
        main()
