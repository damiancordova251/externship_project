"""
The target school list, plus every rule for turning a messy school name into a
canonical one.

Why this is its own module: three different scripts need the school list, but
only one of them (build_directory.py) needs pandas. Keeping the lists and the
name-matching here means the career-fair scraper — the part that runs weekly in
GitHub Actions — can import them with nothing but the standard library.

The directory tracks a school if it matches ANY of four criteria:

  1. TOP_NATIONAL   ~Top 100 U.S. national universities
  2. NY_FOUR_YEAR   4-year degree-granting institutions in New York State
  3. SF_FOUR_YEAR   4-year degree-granting institutions in San Francisco
  4. EXTRA_TRACKED  schools that show up in the career-fair feed

Plus, at build time, any school that appears as an alma mater in the Ashby data.
Schools matching 1-4 with zero hires are kept deliberately: a target school we
have never hired from is exactly the one worth sending a recruiter to.

Name matching happens on a NORMALIZED KEY (see norm_key), never on the raw
string, because the same institution arrives spelled a dozen ways: "NYU",
"New York University", "new york university ", "NYU School of Professional
Studies". canonicalize() is the single entry point that applies every rule.
"""

import re

# Source used for the Top-100 inclusion set. Only the *set of institution names*
# matters for membership testing — the ranked order is never used.
RANKING_SOURCE = ("U.S. News & World Report — 2025 Best National Universities "
                  "(used as an unordered set of institution names for inclusion, "
                  "not the ranking order)")

# --- Criterion 1: ~Top 100 U.S. national universities (names only) ------------
TOP_NATIONAL = [
    "Princeton University", "Massachusetts Institute of Technology",
    "Harvard University", "Stanford University", "Yale University",
    "California Institute of Technology", "Duke University",
    "Johns Hopkins University", "Northwestern University",
    "University of Pennsylvania", "Cornell University", "University of Chicago",
    "Brown University", "Columbia University", "Dartmouth College",
    "University of California, Los Angeles", "University of California, Berkeley",
    "Rice University", "University of Notre Dame", "Vanderbilt University",
    "Carnegie Mellon University", "University of Michigan",
    "Washington University in St. Louis", "Emory University",
    "Georgetown University", "University of Virginia",
    "University of North Carolina at Chapel Hill",
    "University of Southern California", "University of California, San Diego",
    "New York University", "University of Florida",
    "University of Texas at Austin", "University of California, Davis",
    "University of California, Irvine", "Georgia Institute of Technology",
    "University of California, Santa Barbara",
    "University of Illinois Urbana-Champaign",
    "University of Wisconsin-Madison", "Boston College",
    "Rutgers University", "Tufts University", "University of Washington",
    "Boston University", "The Ohio State University", "Purdue University",
    "University of Georgia", "University of Maryland, College Park",
    "Lehigh University", "Wake Forest University", "Texas A&M University",
    "University of California, Santa Cruz", "Case Western Reserve University",
    "Northeastern University", "Virginia Tech", "Michigan State University",
    "Florida State University", "William & Mary", "University of Rochester",
    "University of Minnesota, Twin Cities", "Pennsylvania State University",
    "George Washington University", "University of Pittsburgh",
    "Brandeis University", "University of California, Riverside",
    "University of Connecticut", "University of Miami",
    "Indiana University Bloomington", "Tulane University",
    "University of Colorado Boulder", "Syracuse University",
    "Pepperdine University", "Southern Methodist University",
    "Stony Brook University", "Rensselaer Polytechnic Institute",
    "University of Massachusetts Amherst", "Clemson University",
    "Fordham University", "Baylor University", "Brigham Young University",
    "American University", "Arizona State University", "University of Delaware",
    "Marquette University", "Stevens Institute of Technology",
    "North Carolina State University", "Binghamton University",
    "University of Iowa", "University of Arizona", "Auburn University",
    "Loyola Marymount University", "University of Tennessee, Knoxville",
    "University of Kentucky", "University of Nebraska-Lincoln",
    "University of San Diego", "Yeshiva University", "Worcester Polytechnic Institute",
    "University at Buffalo", "University of Vermont", "Texas Christian University",
    "University of Denver",
]

# --- Criterion 2: 4-year degree-granting institutions in New York State -------
NY_FOUR_YEAR = [
    # Private
    "Columbia University", "Cornell University", "New York University",
    "Fordham University", "Syracuse University", "University of Rochester",
    "Rensselaer Polytechnic Institute", "Rochester Institute of Technology",
    "Colgate University", "Hamilton College", "Vassar College",
    "Barnard College", "Skidmore College", "Union College",
    "Hobart and William Smith Colleges", "St. Lawrence University",
    "Ithaca College", "Pace University", "Yeshiva University",
    "The New School", "Pratt Institute", "Manhattan College",
    "Marist College", "Siena College", "Le Moyne College",
    "Canisius University", "St. John's University", "Adelphi University",
    "Hofstra University", "Clarkson University", "Wagner College",
    "Iona University", "Nazareth University", "Sarah Lawrence College",
    "Bard College", "Cooper Union", "The Juilliard School",
    "Rockefeller University", "Elmira College",
    "Wells College", "Utica University", "Daemen University",
    "St. Bonaventure University", "Niagara University", "Dominican University New York",
    "Molloy University", "Mercy University", "Long Island University",
    "New York Institute of Technology", "School of Visual Arts",
    "Fashion Institute of Technology",
    # SUNY (4-year)
    "University at Albany", "Binghamton University", "University at Buffalo",
    "Stony Brook University", "SUNY College at Brockport",
    "Buffalo State University", "SUNY Cortland", "SUNY Fredonia",
    "SUNY Geneseo", "SUNY New Paltz", "SUNY Old Westbury", "SUNY Oneonta",
    "SUNY Oswego", "SUNY Plattsburgh", "SUNY Potsdam", "Purchase College",
    "SUNY Empire State University", "SUNY Polytechnic Institute",
    "SUNY Maritime College",
    "SUNY College of Environmental Science and Forestry",
    "Farmingdale State College", "SUNY Cobleskill", "SUNY Morrisville",
    "Alfred State College", "SUNY Delhi",
    # CUNY (4-year)
    "Baruch College", "Brooklyn College", "The City College of New York",
    "Hunter College", "John Jay College of Criminal Justice", "Lehman College",
    "Medgar Evers College", "New York City College of Technology",
    "Queens College", "College of Staten Island", "York College, CUNY",
    "Macaulay Honors College",
]

# --- Criterion 3: 4-year degree-granting institutions in San Francisco --------
SF_FOUR_YEAR = [
    "University of San Francisco",
    "San Francisco State University",
    "California College of the Arts",
    "Academy of Art University",
    "Golden Gate University",
    "San Francisco Conservatory of Music",
]

# --- Criterion 4: extra schools tracked for career-fair coverage --------------
# Not ranked / NY / SF, but they appear in career_fairs.json, so they get a row.
EXTRA_TRACKED = [
    "San Jose State University",
    "University of Cincinnati",
    "University of Minnesota Duluth",
    "University of Rhode Island",
    "University of Texas at Dallas",
    "University of Texas at San Antonio",
    "University of Utah",
    "University of Washington Bothell",
]

# Every curated target, de-duplicated, in list order. Used by the scraper and
# the source-discovery sweep.
ALL_TARGETS = list(dict.fromkeys(
    TOP_NATIONAL + NY_FOUR_YEAR + SF_FOUR_YEAR + EXTRA_TRACKED))


# --- Alias map: what people actually type -> the official display name --------
# Keyed by raw string here for readability; normalized into _ALIAS_KEYS below.
_ALIAS_RAW = {
    # Common abbreviations.
    "nyu": "New York University",
    "mit": "Massachusetts Institute of Technology",
    "ucla": "University of California, Los Angeles",
    "usc": "University of Southern California",
    "cal": "University of California, Berkeley",
    "uc berkeley": "University of California, Berkeley",
    "berkeley": "University of California, Berkeley",
    "ucsd": "University of California, San Diego",
    "uc san diego": "University of California, San Diego",
    "uc davis": "University of California, Davis",
    "uc irvine": "University of California, Irvine",
    "uc santa barbara": "University of California, Santa Barbara",
    "ucsb": "University of California, Santa Barbara",
    "cmu": "Carnegie Mellon University",
    "penn": "University of Pennsylvania",
    "upenn": "University of Pennsylvania",
    "uiuc": "University of Illinois Urbana-Champaign",
    "university of illinois": "University of Illinois Urbana-Champaign",
    "georgia tech": "Georgia Institute of Technology",
    "gatech": "Georgia Institute of Technology",
    "ut austin": "University of Texas at Austin",
    "umich": "University of Michigan",
    "u of m": "University of Michigan",
    "osu": "The Ohio State University",
    "ohio state": "The Ohio State University",
    "asu": "Arizona State University",
    "psu": "Pennsylvania State University",
    "penn state": "Pennsylvania State University",
    "rpi": "Rensselaer Polytechnic Institute",
    "rit": "Rochester Institute of Technology",
    "suny buffalo": "University at Buffalo",
    "suny binghamton": "Binghamton University",
    "suny albany": "University at Albany",
    "suny stony brook": "Stony Brook University",
    "cuny baruch": "Baruch College",
    "wash u": "Washington University in St. Louis",
    "washu": "Washington University in St. Louis",
    "unc": "University of North Carolina at Chapel Hill",
    "uw": "University of Washington",
    "uw madison": "University of Wisconsin-Madison",
    "uf": "University of Florida",
    "gwu": "George Washington University",
    "bu": "Boston University",
    "bc": "Boston College",
    "wpi": "Worcester Polytechnic Institute",
    "sfsu": "San Francisco State University",
    "sf state": "San Francisco State University",
    "cca": "California College of the Arts",

    # Merge only the interchangeable undergrad/general Harvard names.
    # (Harvard Business/Law/Extension etc. stay as their own entries.)
    "harvard": "Harvard University",
    "harvard college": "Harvard University",

    # Unambiguous typo / spelling / casing fixes (same institution).
    "arizona state": "Arizona State University",
    "university of north carolina chapelhill": "University of North Carolina at Chapel Hill",
    "central arizona community college": "Central Arizona College",
    "cal state northridge": "California State University, Northridge",
    "cal state university northridge": "California State University, Northridge",
    "california state northridge": "California State University, Northridge",
    "arizona school of real estate business": "Arizona School of Real Estate and Business",
    "wharton": "The Wharton School",
    "columbia university school of law": "Columbia Law School",
    "university of binghamton": "Binghamton University",
    "washington state": "Washington State University",
    "utica college": "Utica University",
    "city university of new york college of staten island": "College of Staten Island",
    "cuny college of staten island": "College of Staten Island",

    # Bare "UC" -> the UC system; flagged ambiguous below.
    "uc": "University of California",

    # Extension / continuing-ed schools fold into the parent university.
    "harvard extension school": "Harvard University",
    "ucla extension": "University of California, Los Angeles",
    "uc berkeley extension": "University of California, Berkeley",
    "nyu school of professional studies": "New York University",

    # Duplicate spellings of the SAME professional school. Kept separate from
    # the parent university, but deduplicated with each other.
    "texas mccombs school of business": "McCombs School of Business",
    "new york university leonard n stern school of business": "Stern School of Business",
}

# Entries with no resolvable campus. Kept in the directory, but clearly labeled
# so nobody mistakes them for a real institution.
AMBIGUOUS = {
    "university california": "University of California (campus unspecified)",
    "california state university": "California State University (campus unspecified)",
    "university": "Unspecified university",   # from a bare "The University"
}

# Rule for unverifiable schools: if a candidate's school is one of these AND
# they have no LinkedIn to check against, drop them. Candidates WITH a LinkedIn
# are kept (labeled) pending manual resolution.
REMOVABLE_AMBIGUOUS = set(AMBIGUOUS) | {"ucl"}


def norm_key(s):
    """Normalized matching key: lowercase, no punctuation, no parentheticals,
    no filler words. "The University of Texas at Austin (UT)" and
    "university of texas austin" both collapse to "university texas austin"."""
    s = str(s).lower()
    s = re.sub(r"\(.*?\)", " ", s)      # drop parentheticals, e.g. "(MIT)"
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)   # punctuation -> space
    s = re.sub(r"\b(the|at|of|for)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Official-name lookup (norm_key -> display name) across all inclusion lists.
OFFICIAL = {}
for _nm in ALL_TARGETS:
    OFFICIAL.setdefault(norm_key(_nm), _nm)

# Per-criterion key sets, for tagging each school in the built directory.
TOP_KEYS = {norm_key(n) for n in TOP_NATIONAL}
NY_KEYS = {norm_key(n) for n in NY_FOUR_YEAR}
SF_KEYS = {norm_key(n) for n in SF_FOUR_YEAR}
EXTRA_KEYS = {norm_key(n) for n in EXTRA_TRACKED}

_ALIAS_KEYS = {norm_key(k): v for k, v in _ALIAS_RAW.items()}

# "Duke University, School of Engineering" -> strip the trailing sub-college.
_SUBCOLLEGE = re.compile(
    r",\s*(college|school|graduate school|faculty|division)\s+of\s+.*$", re.I)

# A general undergraduate college (arts & sciences / liberal arts) folds into
# its parent: "Duke University, Trinity College of Arts and Sciences" -> "Duke
# University". Named graduate/professional schools (Business, Law, Engineering)
# deliberately do NOT match — those stay as separate entries.
_ARTS_SCI = re.compile(
    r",\s*[^,]*?(arts\s*(?:and|&)\s*sciences|liberal arts|letters\s+and\s+science)[^,]*$",
    re.I)

# This is a college directory, so high schools are filtered out entirely.
# Catches "High School", "Senior High", and the "HS"/"H.S." abbreviations.
_NOT_COLLEGE = re.compile(
    r"\b(high school|senior high|junior high|h\.?s\.?)\b", re.I)


def split_multi(raw):
    """Split a cell that lists more than one school ("A / B", "A - B", "A; B")."""
    parts = re.split(r"\s*/\s*|\s+-\s+|\s*;\s*", str(raw))
    return [p.strip() for p in parts if p.strip()]


def pretty(name):
    """Best-effort display casing for a school with no official match. Only
    touches all-caps or all-lowercase input, so correctly-cased names that we
    simply don't recognize are left exactly as written."""
    if name.isupper() or name.islower():
        small = {"of", "the", "at", "and", "for", "in"}
        words = []
        for i, w in enumerate(name.split()):
            lw = w.lower()
            words.append(lw if (lw in small and i > 0) else lw.capitalize())
        return " ".join(words)
    return name.strip()


def canonicalize(raw):
    """Turn one raw school cell into [(display_name, match_key), ...].

    Returns a list because a single cell can name several schools. Returns an
    empty list if the cell holds nothing we'd put in a college directory.
    """
    out = []
    for part in split_multi(raw):
        if _NOT_COLLEGE.search(part):
            continue
        part = _SUBCOLLEGE.sub("", part).strip()
        part = _ARTS_SCI.sub("", part).strip()   # undergrad A&S college -> parent
        if not part:
            continue
        k = norm_key(part)
        if not k:
            continue
        if k in _ALIAS_KEYS:                     # a known alias -> official name
            disp = _ALIAS_KEYS[k]
            k = norm_key(disp)
        elif k in OFFICIAL:                      # already an inclusion-list name
            disp = OFFICIAL[k]
        else:                                    # unknown school: keep, tidy case
            disp = pretty(part)
        out.append((disp, k))
    return out
