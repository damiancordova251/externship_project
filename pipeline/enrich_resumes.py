"""
Resume-based school enrichment for the Campus Recruiting Directory.

For each hired candidate, this:
  1. Resolves their resume file handle to a download URL via Ashby's file.info
  2. Downloads the resume PDF and extracts its text
  3. Detects the school(s) named in the resume
  4. Flags where the resume disagrees with the Ashby `school` field
     (the transfer / community-college problem, e.g. "Mesa Community College"
      in the field vs. "Northern Arizona University" on the resume)

It never silently overwrites anything — an automated guess about someone's
education is exactly the kind of thing that should need a human's sign-off. It
writes a review file plus conservative override *suggestions*; approved fixes
get copied into private/ashby_overrides.json, which build_directory.py applies.

Run:  python pipeline/enrich_resumes.py   (needs an Ashby API key + network)

Outputs (git-ignored — they contain PII):
  private/ashby_resume_review.csv          one row per candidate: field vs resume
  private/ashby_override_suggestions.json  {id: real_school} for clear mismatches
"""

import ast
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from getpass import getpass

import pandas as pd
import requests

try:
    import pdfplumber
except ImportError:
    raise SystemExit("Missing dependency. Run:  pip install -r requirements.txt")

import paths
# Reuse the exact school lists + normalizers the directory uses, so a school
# recognized here is guaranteed to be recognized there.
from target_schools import (NY_FOUR_YEAR, SF_FOUR_YEAR, TOP_NATIONAL,
                            canonicalize, norm_key)

BASE_URL = "https://api.ashbyhq.com"
CONCURRENCY = 8
REQUEST_TIMEOUT = 45

# Shared connection pool. Credentials are attached in main(), not here, so
# importing this module never prompts for a key.
session = requests.Session()


def parse(v):
    if pd.isna(v):
        return None
    try:
        return ast.literal_eval(v)
    except Exception:
        return v


def linkedin(row):
    s = parse(row.get("socialLinks"))
    if isinstance(s, list):
        for it in s:
            if isinstance(it, dict) and str(it.get("type", "")).lower() == "linkedin":
                return it.get("url")
    return ""


# ---- Ashby: file handle -> download URL -------------------------------------
def file_url(handle):
    r = session.post(f"{BASE_URL}/file.info", json={"fileHandle": handle},
                     timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    res = r.json().get("results") or {}
    # results is typically {"url": "..."}; be defensive about the shape.
    if isinstance(res, dict):
        return res.get("url") or res.get("downloadUrl")
    return None


def extract_text(url):
    # Presigned URL - fetch WITHOUT the Ashby auth header.
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


# ---- School detection in resume text ----------------------------------------
def build_known(df):
    """norm_key -> display for every school we know about (lists + CSV values)."""
    known = {}
    for nm in TOP_NATIONAL + NY_FOUR_YEAR + SF_FOUR_YEAR:
        known.setdefault(norm_key(nm), nm)
    for raw in df["school"].dropna().astype(str).unique():
        for disp, k in canonicalize(raw):
            known.setdefault(k, disp)
    return known


def build_real(df):
    """norm_keys of institutions we trust enough to auto-suggest: curated lists
    plus any school named by >=2 candidates (corroborated, not a one-off fragment)."""
    real = {norm_key(n) for n in TOP_NATIONAL + NY_FOUR_YEAR + SF_FOUR_YEAR}
    from collections import Counter
    cnt = Counter()
    for raw in df["school"].dropna().astype(str):
        for _, k in canonicalize(raw):
            cnt[k] += 1
    real |= {k for k, n in cnt.items() if n >= 2}
    return real


# Catch institution names not in our dictionary, e.g. "Foo State University".
_UNI_RE = re.compile(
    r"\b([A-Z][A-Za-z.&'-]+(?:\s+[A-Z][A-Za-z.&'-]+){0,5}\s+"
    r"(?:University|College|Institute of Technology|Polytechnic))\b")


def is_cc(name):
    n = name.lower()
    return "community college" in n or "junior college" in n


# Words that get greedily swept into regex matches but aren't part of a name.
_JUNK_LEAD = {"education", "relevant", "coursework", "some", "the", "expected",
              "present", "current", "bachelor", "bachelors", "master", "masters",
              "associate", "associates", "degree", "major", "minor", "gpa",
              "graduated", "attended", "studies", "study", "in"}
_STATE = {"al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
          "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
          "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
          "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
          "wi", "wy"}
# Placeholder / fragment "names" that are never a real school.
_PLACEHOLDER = {norm_key(x) for x in
                ["The University", "Some College", "Some University", "Continuing",
                 "Education", "University", "College", "School", "State College",
                 "Business College", "The College", "My University"]}


def _clean_name(name):
    toks = name.split()
    while toks and (toks[0].lower() in _JUNK_LEAD or toks[0].lower() in _STATE):
        toks.pop(0)
    return re.sub(r"\s+", " ", " ".join(toks)).strip()


def detect_schools(text, known):
    found = []
    nt = norm_key(text)                       # normalized whole-resume text
    for k, disp in known.items():
        if k and len(k) > 8 and k in nt:      # len>8 avoids tiny/ambiguous keys
            found.append(disp)
    for m in _UNI_RE.finditer(text):
        found.append(_clean_name(m.group(1)))
    # de-dup + drop placeholders/fragments
    seen, out = set(), []
    for f in found:
        kk = norm_key(f)
        if kk and kk not in seen and kk not in _PLACEHOLDER and len(kk) > 6:
            seen.add(kk)
            out.append(f)
    return out


def field_school(raw):
    """Canonical display of the Ashby `school` field (first component)."""
    cs = canonicalize(str(raw)) if pd.notna(raw) else []
    return cs[0][0] if cs else ""


def analyze(row, known, real):
    handle = row.get("resumeFileHandle.handle")
    field = row.get("school")
    field_disp = field_school(field)
    rec = {"candidate_id": row.get("id"), "name": row.get("name"),
           "ashby_school": field_disp, "resume_schools": "", "status": "",
           "suggested_override": "", "linkedin": linkedin(row)}
    if pd.isna(handle) or not str(handle).strip():
        rec["status"] = "no resume on file"
        return rec
    try:
        url = file_url(str(handle))
        if not url:
            rec["status"] = "file.info returned no URL"
            return rec
        text = extract_text(url)
    except Exception as e:
        rec["status"] = f"error: {type(e).__name__}"
        return rec
    if not text or len(text.strip()) < 30:
        rec["status"] = "no extractable text (scanned/image PDF?)"
        return rec

    schools = detect_schools(text, known)
    rec["resume_schools"] = " | ".join(schools)
    field_key = norm_key(field_disp) if field_disp else ""
    school_keys = {norm_key(s) for s in schools}

    if not schools:
        rec["status"] = "no school detected in resume"
    elif field_key and field_key in school_keys:
        rec["status"] = "match"
    else:
        rec["status"] = "MISMATCH"
        # Conservative suggestion: field empty/CC, resume names exactly one 4-year,
        # AND that school is a real/corroborated institution (not a fragment).
        four_year = [s for s in schools
                     if not is_cc(s) and norm_key(s) in real]
        if (not field_disp or is_cc(field_disp)) and len(four_year) == 1:
            rec["suggested_override"] = four_year[0]
    return rec


def main():
    # Prompted rather than read from the environment: this key can read every
    # candidate record in the ATS, so it should never sit in a shell history
    # file or a committed .env.
    session.auth = (getpass("Paste your Ashby API key: "), "")

    try:
        df = pd.read_csv(paths.CANDIDATES_CSV, low_memory=False)
    except FileNotFoundError:
        raise SystemExit(f"Missing input: {paths.CANDIDATES_CSV}\n"
                         f"  Export it first with: python pipeline/extract_ashby.py")
    known = build_known(df)
    real = build_real(df)
    rows = df.to_dict("records")
    print(f"Analyzing resumes for {len(rows)} hired candidates "
          f"(concurrency {CONCURRENCY})...\n")

    out = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(analyze, r, known, real): r for r in rows}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                out.append(fut.result())
            except Exception as e:
                print(f"  !! row failed: {e}")
            if i % 50 == 0 or i == len(rows):
                print(f"  {i}/{len(rows)}")

    paths.ensure_private()
    review = pd.DataFrame(out).sort_values(
        ["status", "ashby_school", "name"], na_position="last")
    review.to_csv(paths.RESUME_REVIEW, index=False)

    suggestions = {r["candidate_id"]: r["suggested_override"]
                   for r in out if r["suggested_override"]}
    paths.OVERRIDE_SUGGESTIONS.write_text(json.dumps(suggestions, indent=2) + "\n")

    counts = review["status"].value_counts().to_dict()
    print("\n=== summary ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"\nMismatches with a confident fix (suggested overrides): {len(suggestions)}")
    print(f"Wrote {paths.RESUME_REVIEW.name} and {paths.OVERRIDE_SUGGESTIONS.name}")
    print(f"\nNext: review those files. To apply a fix, copy the id->school entry")
    print(f"into {paths.SCHOOL_OVERRIDES.name}, then re-run:")
    print(f"  python pipeline/build_directory.py")


if __name__ == "__main__":
    main()
