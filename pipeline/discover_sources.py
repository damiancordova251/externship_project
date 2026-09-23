"""
KEYLESS discovery of career-fair source URLs.

Bootstrap step for the scraper: it figures out WHERE to look for each school's
career fairs, so data/fair_sources.json doesn't have to be hand-assembled for
300+ schools. For each target school it:

  1. resolves the official domain via universities.hipolabs.com (free, no API key)
  2. constructs candidate career-center URLs from common patterns
  3. fetches + validates them (the page must really mention a career fair)
  4. shallow-crawls a valid landing page for deeper fair/event links
  5. writes the good URLs into data/fair_sources.json for the scraper

Needs no API keys and no credentials — every request is to a public page.
Already-present schools are skipped, so re-running only fills in gaps.

Run:  python pipeline/discover_sources.py
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin

import requests

import paths
from target_schools import ALL_TARGETS

SOURCES = paths.FAIR_SOURCES
UA = {"User-Agent": "ValonCampusRecruitingBot/1.0 (career-fair source discovery)"}
KW = re.compile(r"career fair|job fair|career expo|internship fair|"
                r"job & internship|hiring expo|recruit", re.I)
LINK_HINT = re.compile(r"career.?fair|job.?fair|/events|career-?expo", re.I)


def resolve_domain(school: str) -> str | None:
    """Official domain from the free universities API; prefer a .edu domain."""
    try:
        r = requests.get("http://universities.hipolabs.com/search",
                         params={"name": school, "country": "United States"}, timeout=15)
        r.raise_for_status()
        results = r.json()
    except Exception:
        return None
    fallback = None
    for u in results:
        for d in (u.get("domains") or []):
            if d.endswith(".edu"):
                return d
            fallback = fallback or d
    return fallback


def candidate_urls(domain: str) -> list[str]:
    """The URL patterns career centers actually use, most specific first — the
    first one that validates wins, so ordering matters."""
    return [
        f"https://career.{domain}/events",
        f"https://careers.{domain}/events",
        f"https://{domain}/career-services/events",
        f"https://{domain}/careers/career-fairs",
        f"https://career.{domain}",
        f"https://careers.{domain}",
        f"https://{domain}/careers",
    ]


def get(url: str) -> str | None:
    try:
        r = requests.get(url, headers=UA, timeout=15)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def crawl_links(base: str, html: str) -> list[str]:
    """Deeper fair/event links from a valid career landing page (shallow)."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        blob = f"{a.get_text(' ', strip=True)} {a['href']}"
        if LINK_HINT.search(blob):
            full = urljoin(base, a["href"])
            if full not in seen and full.startswith("http"):
                seen.add(full)
                out.append(full)
    return out[:2]


def directory_schools() -> list[str]:
    """Every school currently shown in the generated directory, so the sweep
    covers all ~485 — not just the curated targets. Reads the inlined payload
    back out of the HTML. Skips the unresolvable "campus unspecified" buckets,
    which have no real domain to find. Returns [] if the page isn't built yet."""
    try:
        html = paths.DIRECTORY_HTML.read_text(encoding="utf-8")
        m = re.search(r"const DATA = (\{.*\});\s*\n\s*const SCHOOLS", html, re.S)
        data = json.loads(m.group(1))
        return [s["name"] for s in data["schools"]
                if "(campus unspecified)" not in s["name"]
                and s["name"] != "Unspecified university"]
    except Exception:
        return []


def main():
    targets = list(dict.fromkeys(ALL_TARGETS + directory_schools()))
    try:
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sources = {}

    added_schools = added_urls = 0
    for i, school in enumerate(targets, 1):
        if school in sources:          # already curated / discovered
            continue
        domain = resolve_domain(school)
        if not domain:
            continue
        found: list[str] = []
        for url in candidate_urls(domain):
            html = get(url)
            if html and KW.search(html):
                found.append(url)
                for link in crawl_links(url, html):
                    if link not in found:
                        found.append(link)
                break                  # one good landing page is enough
        if found:
            sources[school] = [{"url": u, "render": False} for u in found[:3]]
            added_schools += 1
            added_urls += len(sources[school])
            print(f"  + {school} ({domain}): {len(sources[school])} url(s)")
        if i % 20 == 0:
            _save(sources)             # checkpoint — a long sweep can be resumed
            print(f"  … {i}/{len(targets)} schools scanned")
        time.sleep(0.2)                # be polite to the servers we're crawling

    _save(sources)
    print(f"\n{SOURCES.name} now has {len(sources)} schools "
          f"(+{added_schools} schools / +{added_urls} URLs this run).")


def _save(sources: dict) -> None:
    SOURCES.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
