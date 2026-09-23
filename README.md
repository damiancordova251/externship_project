# Campus Recruiting Directory

A university-recruiting tool built during the **Valon Technologies externship**
(July 2026).

Valon wanted to recruit on campus but had no view of *which* campuses. The
hiring data existed — three years of it, sitting in the Ashby ATS — but the
school field was free text, so the same university showed up as `MIT`,
`Massachusetts Institute of Technology`, and `mit ` and nothing aggregated. And
knowing a school was promising still left the actual work: find someone from
Valon who went there, dig up their contact info, and write them an email.

This pipeline does both halves. It pulls the hiring data, resolves the school
names, layers on scraped career-fair dates, and generates a single self-contained
HTML page: every target school, who Valon hired from it, when its next career
fair is, and a one-click pre-written outreach email to the alumni contact.

---

## What it produces

One file — `private/campus-recruiting-directory.html` — that opens in any
browser with no server and no dependencies. For each school it shows:

| | |
|---|---|
| **Hire count** | distinct people hired, current employees separated from past hires |
| **Contacts** | email / LinkedIn / GitHub / Ashby profile, whatever exists |
| **Career fairs** | upcoming fairs with dates, locations, and source links; RSVP + Google Calendar |
| **Outreach** | a pre-filled email (Invitation / Inquiry / Other) addressed to that school's alumni contact |
| **Filters** | by criterion (Top-100 / NY / SF), by upcoming-fair date, by minimum hires |

The page recomputes "next fair" against today's date on every load, so it never
goes stale on its own — a fair that happened yesterday drops off by itself.

## The five stages

```
   Ashby API                     college career-center sites
       │                                    │
       ▼                                    ▼
1. extract_ashby.py              3. discover_sources.py  ── finds WHERE to look
   hired applications               (keyless: resolves each school's domain,
   + candidate records               probes common career-center URL patterns)
       │                                    │
       │                                    ▼  data/fair_sources.json
       │                         4. scrape_fairs.py  ── weekly GitHub Action
       │                            Localist API / JSON-LD / __NEXT_DATA__ /
       │                            rendered text, in that order
       ▼                                    ▼  data/career_fairs.json
2. enrich_resumes.py  ──────►  5. build_directory.py  ──►  the HTML page
   resume PDFs vs. the            joins hires + fairs per school,
   ATS school field               inlines everything into the template
```

| Stage | Script | Needs | Runs |
|---|---|---|---|
| 1 | `pipeline/extract_ashby.py` | Ashby API key | once per refresh |
| 2 | `pipeline/enrich_resumes.py` | Ashby API key | optional, for data quality |
| 3 | `pipeline/discover_sources.py` | nothing | once, to bootstrap |
| 4 | `pipeline/scrape_fairs.py` | nothing | weekly, automated in CI |
| 5 | `pipeline/build_directory.py` | the CSV from stage 1 | after any change |

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Demo it (no API key required)

The fastest way to see the tool. Builds the full page from committed synthetic
candidate data and opens it:

```bash
python pipeline/build_directory.py --sample && open private/sample-directory.html
```

<details>
<summary>On Linux, or if <code>open</code> isn't available</summary>

```bash
python pipeline/build_directory.py --sample
xdg-open private/sample-directory.html      # Linux
start private\sample-directory.html         # Windows
```
</details>

You get a working directory of **193 schools**: 191 curated targets plus any
school the sample data adds. What's real and what isn't:

| | |
|---|---|
| Career fairs — 198 fairs, 112 colleges, real dates, locations, source links | **real data** |
| The 191-school target list, and every name-normalization rule | **real** |
| The people — names, emails, LinkedIn handles, hire counts | **synthetic** |

The 191 synthetic hires are invented: random name pairs, `@example.com`
addresses (an [RFC 2606](https://www.rfc-editor.org/rfc/rfc2606) reserved domain
that cannot receive mail), `linkedin.com/in/demo-*` handles. Generation is
seeded, so the sample is identical on every machine. Fifteen rows are
deliberately malformed — `MIT`, `nyu`, `CARNEGIE MELLON UNIVERSITY`,
`Yale University, College of Arts and Sciences`, `Baruch College / Hunter
College`, a high school, a blank, and one person filed twice under two
spellings — so the demo also exercises every rule in `target_schools.py`. The
build prints the result: **191 rows in, 188 distinct people out.**

Career-fair scraping works without a key too:

```bash
python pipeline/scrape_fairs.py --dry-run    # scrape live, print what would change
python pipeline/discover_sources.py          # find career-center URLs from scratch
```

### The real build (needs an Ashby API key)

```bash
python pipeline/extract_ashby.py      # prompts for the key; writes private/*.csv
python pipeline/enrich_resumes.py     # optional: audit schools against resume PDFs
python pipeline/build_directory.py    # -> private/campus-recruiting-directory.html
```

> **If `import pandas` fails:** you're almost certainly running the system or
> Homebrew Python, which refuses `pip install` under
> [PEP 668](https://peps.python.org/pep-0668/) ("externally-managed-environment").
> The virtualenv above is the fix — activate it, and `python` resolves to
> `.venv/bin/python`, which has pandas. Don't reach for
> `--break-system-packages`; it can damage the Homebrew install.

## Layout

```
pipeline/            the five stages, plus two shared modules
  paths.py             every file location, in one place
  target_schools.py    the school list + all name-normalization rules
  directory_template.py  the HTML/CSS/JS page, as one template string
data/                committed — aggregate, no PII
  career_fairs.json      source of truth for fair dates
  fair_sources.json      curated career-center URLs
  fair_sources_pending.json  discovered URLs awaiting human review
  sample_candidates.csv  synthetic input for --sample
private/             git-ignored in full — everything derived from Ashby
docs/                career-fair refresh notes and honest limitations
.github/workflows/   the weekly scraper Action
```

## How school names get resolved

The hardest part of the project, and the reason the counts are trustworthy. All
of it lives in `pipeline/target_schools.py`; `canonicalize()` is the single
entry point, and every stage uses it, so the scraper and the directory can never
disagree about what a school is called.

- **Normalized keys.** Matching happens on a stripped key — lowercased, no
  punctuation, no parentheticals, no filler words — so `The University of Texas
  at Austin (UT)` and `university of texas austin` collapse together.
- **Aliases.** ~60 hand-curated mappings for what people actually type: `NYU`,
  `Cal`, `Georgia Tech`, `WashU`, `SUNY Binghamton`.
- **Sub-colleges fold into the parent** when they're general undergrad
  (`Duke University, Trinity College of Arts and Sciences` → `Duke University`)
  but **stay separate** when they're a named professional school — Harvard
  Business School is a different recruiting target from Harvard College.
- **Multi-school cells split** (`Baruch College / Hunter College` → both).
- **High schools are dropped.** It's a college directory.
- **Ambiguity is labeled, not guessed.** A bare `University of California` with
  no campus becomes *"University of California (campus unspecified)"*. If the
  candidate also has no LinkedIn to verify against, they're dropped rather than
  filed under a school they may never have attended.
- **Duplicate people are collapsed** only when the name *and* an email or phone
  match, so two different people who share a name stay separate. Contacts are
  unioned, so merging never loses information.
- **Manual overrides win.** `private/ashby_overrides.json` maps a candidate id
  to a corrected school and takes precedence over everything above.

## Why zero-hire schools are in the directory

They're the point. A school with no hires that is in the Top 100, or is a
4-year institution in NYC or SF, is precisely where an untapped pipeline is.
The directory unions in every target school regardless of hire count and renders
the empty ones with an explicit empty state, rather than letting them vanish.

Current coverage: **191 curated target schools** (100 national + 88 NY 4-year +
6 SF + 8 fair-only, after overlaps), plus every alma mater appearing in the
Ashby data, plus any school in the fair feed. The committed fair feed carries
**198 fairs across 112 colleges**.

## Privacy

Candidate data never touches git.

- `private/` is git-ignored in its entirety — not by filename pattern, but as a
  whole directory, so a newly-added output file can't slip through.
- The generated page contains real names and contact details. It is a local
  artifact, not a deliverable to commit or share.
- Phone numbers are excluded from the page on purpose: it's a tool for email
  outreach, and there's no reason to spread phone numbers further.
- Interview feedback and scores are never pulled from Ashby at all.
- The Ashby API key is prompted for interactively, never read from the
  environment or a file, so it can't end up in shell history.
- `data/` holds only aggregate, public information: fair dates and career-center
  URLs.

## Automation

`.github/workflows/refresh-fairs.yml` runs the scraper weekly (Mondays 13:00
UTC) and commits any newly-found fairs to `data/career_fairs.json`. The
directory page is regenerated locally from that JSON — CI never sees candidate
data.

The scraper depends on nothing but `requests` and `beautifulsoup4`. That's
deliberate: the school lists live in `target_schools.py` rather than in
`build_directory.py`, so the weekly job doesn't need pandas and can't fail on a
data-science install.

Read [`docs/career-fair-refresh.md`](docs/career-fair-refresh.md) before
trusting the scraped dates — it documents exactly what the scraper can and
cannot reach (login-gated Handshake/Symplicity calendars, mainly).
