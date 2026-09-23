# Keeping career-fair dates fresh

The directory (`private/campus-recruiting-directory.html`) shows each school's **upcoming**
general and tech/STEM career fairs. It never hard-codes a "next fair" date: the
data lives in `data/career_fairs.json`, and the page recomputes each school's next
fair against *today's* date every time it loads.

That gives two layers of "automatic":

## 1. Fairs passing — already fully automatic

No job required. `upcomingFairs()` in the page filters `fairs` to `date >= today`
on every load, so a fair that happened yesterday stops showing and the next one
takes its place. A school with no upcoming fair simply shows none.

## 2. New fairs being posted — the scheduled scraper

### Data flow

```
pipeline/scrape_fairs.py  ──►  data/career_fairs.json  ──►  pipeline/build_directory.py  ──►  private/campus-recruiting-directory.html
  (weekly GitHub Action)       (source of truth,             (inlines fairs +                (generated, contains PII,
                                committed, no PII)            hires per school)               git-ignored — never committed)
```

`data/career_fairs.json` is the **single source of truth**. `pipeline/build_directory.py`
reads it, matches each fair to a school by normalized name, and inlines the
upcoming fairs into the generated page. The scraper only ever writes the JSON;
regenerate the directory with `python pipeline/build_directory.py` to pick up changes
(that step needs the Ashby CSV, so it runs locally, not in CI).

### What's implemented

- **`pipeline/scrape_fairs.py`** — for every college in `data/career_fairs.json`,
  fetches that college's known `source` page(s), extracts upcoming fair dates,
  and MERGES new ones into the JSON. The merge is additive (dedupes by
  college+date, only adds `date >= today`), and it **prunes** fairs that have
  already passed. Auto rows are tagged `"auto": true` so they're easy to spot
  and prune. It also skips obviously niche fairs (nursing/accounting/MBA/etc.)
  to keep the feed scoped to general + tech/STEM. Run with `--dry-run` to
  preview, `--no-net` to exercise only the merge/write path.
- **`.github/workflows/refresh-fairs.yml`** — runs the scraper weekly
  (Mondays 13:00 UTC) and on manual dispatch, then commits any change to
  `data/career_fairs.json`.

### Honest limits (read before trusting it)

- **Works on static-HTML pages only.** Pages that render dates via JavaScript or
  hide them behind a login (many Handshake / Symplicity calendars) yield nothing
  — the extractor just moves on, so those schools keep their curated rows.
- **Name quality varies.** The generic extractor grabs imperfect fair names
  (often just "Career fair"). Add a site-specific function to the `EXTRACTORS`
  registry in `pipeline/scrape_fairs.py` to fix a given site.
- **Parsers break on redesigns.** Review the automated commits the Action pushes;
  auto rows are tagged `"auto": true`.
- **Login-gated holdouts are manual.** Schools whose dates live only behind a
  school login / bot wall are listed in `MANUAL_COLLEGES` and skipped entirely,
  so the scraper never overwrites hand-entered rows. Maintain those by editing
  curated (non-`auto`) rows in `data/career_fairs.json` once per recruiting season.
  `University of Michigan` is currently the only such holdout (its career-center
  site returns 403 to bots).

### JSON shape

```json
{
  "fairs": [
    {
      "college": "Massachusetts Institute of Technology",
      "name": "Fall Career Fair (FCF)",
      "date": "2026-09-25",
      "location": "Johnson Athletic Center",
      "source": "https://capd.mit.edu/channels/fall-career-fair/"
    }
  ]
}
```

- `college` uses the **official school name** (matches the directory's school
  list). Known aliases (`"MIT"`, `"UC Berkeley"`, …) also resolve, because
  `pipeline/build_directory.py` normalizes feed names through the same alias/official map
  it uses for the Ashby data.
- `date` must be ISO `YYYY-MM-DD`.
- A school may have any number of fairs; the page derives the next one.

Schools that appear in the feed but aren't top-100 / NY / SF are tracked via the
`EXTRA_TRACKED` list in `pipeline/target_schools.py` so they still get a directory row.
