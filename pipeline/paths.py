"""
Every file location the pipeline reads or writes, in one place.

Two rules the whole project follows:

  data/     committed to git. Aggregate, public, no personally identifiable
            information (PII) — career-fair dates, career-center URLs.
  private/  NEVER committed (git-ignored wholesale). Anything derived from
            Ashby: candidate CSVs, resumes, the generated directory page.

Paths here are absolute and anchored to the repository root, so every script
behaves the same no matter which directory you run it from.
"""

from pathlib import Path

# pipeline/paths.py -> pipeline/ -> repo root
ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
PRIVATE = ROOT / "private"

# --- Committed, PII-free -----------------------------------------------------
CAREER_FAIRS = DATA / "career_fairs.json"            # source of truth for fairs
FAIR_SOURCES = DATA / "fair_sources.json"            # curated career-center URLs
FAIR_SOURCES_PENDING = DATA / "fair_sources_pending.json"  # discovered, awaiting review
# Synthetic demo inputs — fully invented people, safe to commit. They let the
# whole pipeline be run and shown without an API key or any real candidate data.
SAMPLE_CANDIDATES = DATA / "sample_candidates.csv"
SAMPLE_EMPLOYEES = DATA / "sample_current_employees.json"

# --- Git-ignored, contains PII -----------------------------------------------
CANDIDATES_CSV = PRIVATE / "ashby_candidate_list.csv"   # Ashby export (input)
DIRECTORY_HTML = PRIVATE / "campus-recruiting-directory.html"  # generated page
CURRENT_EMPLOYEES = PRIVATE / "current_employees.json"  # roster: names of staff
SCHOOL_OVERRIDES = PRIVATE / "ashby_overrides.json"     # {candidate id: real school}
RESUME_REVIEW = PRIVATE / "ashby_resume_review.csv"     # resume-vs-field audit
OVERRIDE_SUGGESTIONS = PRIVATE / "ashby_override_suggestions.json"


def ensure_private() -> Path:
    """Create private/ on demand so scripts can write there on a fresh clone."""
    PRIVATE.mkdir(exist_ok=True)
    return PRIVATE
