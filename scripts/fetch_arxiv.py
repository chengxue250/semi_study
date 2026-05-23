#!/usr/bin/env python3
"""Fetch recent semiconductor/EE papers from the arXiv Query API.

Why this exists (vs the arXiv RSS feeds in fetch_rss.py):

The arXiv RSS endpoint at http://export.arxiv.org/rss/<category> only carries
that day's announcement batch. It returns nothing on weekends (arXiv doesn't
announce Sat/Sun) and nothing from any prior day's batch. Asking it for
"papers from the last 7 days" doesn't work — the feed never had them.

This script uses the arXiv Query API instead, which supports an explicit
submittedDate range and returns every matching paper in that window.

Stdlib only. No `pip install` required.

Usage:
  python3 scripts/fetch_arxiv.py                       # 7 days, all configured cats
  python3 scripts/fetch_arxiv.py --days 14             # wider window
  python3 scripts/fetch_arxiv.py --categories cs.AR,cs.LG  # subset
  python3 scripts/fetch_arxiv.py --exclude-seen output/.seen_urls.json
  python3 scripts/fetch_arxiv.py --probe               # just check API health
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "references" / "sources.yaml"

API_BASE = "http://export.arxiv.org/api/query"
UA = "Mozilla/5.0 (compatible; semi-news-daily/1.0; +arxiv-fetcher)"
TIMEOUT = 30

# arXiv's API usage guidelines ask for >= 3 seconds between requests when
# making many calls. We use 3.5s to leave a small safety margin.
RATE_LIMIT_SEC = 3.5

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"

SUMMARY_CAP = 1200          # arXiv abstracts are long; cap generously
AUTHORS_CAP = 12            # store first N author names
TITLE_CAP = 300


# ---------------------------------------------------------------------------
# Minimal sources.yaml reader (same approach as fetch_rss.py)
# Reads the `arxiv_categories:` block — a flat list of category IDs.
# ---------------------------------------------------------------------------
def load_categories(path: Path) -> list[str]:
    cats: list[str] = []
    in_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            in_block = stripped.startswith("arxiv_categories:")
            continue
        if not in_block:
            continue
        if stripped.startswith("- "):
            # Strip inline comments and quotes
            val = stripped[2:].split("#")[0].strip().strip('"').strip("'")
            if val:
                cats.append(val)
    return cats


# ---------------------------------------------------------------------------
# arXiv ID normalization
# ---------------------------------------------------------------------------
def normalize_arxiv_id(url: str) -> str:
    """Canonicalize an arXiv abs URL so dedup catches every equivalent form.

    The arXiv API returns http:// URLs with explicit version suffixes
    (.../abs/2605.12345v2). Other sources (existing edition.json, manual
    additions) often use https:// without a version. They're the same paper.

    Normalize to: https://arxiv.org/abs/<id> with no version, no trailing slash.
    """
    url = url.strip().rstrip("/")
    # Normalize scheme + host to https://arxiv.org
    url = re.sub(r"^https?://(www\.)?arxiv\.org/", "https://arxiv.org/", url)
    # Strip version suffix (v1, v2, ...)
    return re.sub(r"v\d+$", "", url)


# ---------------------------------------------------------------------------
# HTTP + query construction
# ---------------------------------------------------------------------------
def build_query_url(category: str, days: int, max_results: int) -> str:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    fmt = "%Y%m%d%H%M"
    # NB: arXiv API expects literal '+' between search_query terms, not URL-
    # encoded %2B. urlencode would mangle the brackets too. Hand-build the
    # query string.
    search_query = (f"cat:{category}"
                    f"+AND+submittedDate:[{start.strftime(fmt)}+TO+{end.strftime(fmt)}]")
    return (f"{API_BASE}?search_query={search_query}"
            f"&sortBy=submittedDate&sortOrder=descending"
            f"&max_results={max_results}")


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Atom parsing
# ---------------------------------------------------------------------------
def _text(parent, tag, ns=ATOM_NS) -> str:
    el = parent.find(f"{{{ns}}}{tag}")
    return (el.text or "").strip() if el is not None and el.text else ""


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_atom(raw: bytes, category: str) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  warning: malformed Atom response ({e})", file=sys.stderr)
        return []
    items: list[dict] = []
    for entry in root.iter(f"{{{ATOM_NS}}}entry"):
        link = _text(entry, "id")
        title = _collapse(_text(entry, "title"))[:TITLE_CAP]
        summary = _collapse(_text(entry, "summary"))[:SUMMARY_CAP]
        published = _text(entry, "published")
        # Authors + affiliations (when present in the arxiv: namespace)
        authors: list[str] = []
        affils: set[str] = set()
        for a in entry.iter(f"{{{ATOM_NS}}}author"):
            name = _text(a, "name")
            if name:
                authors.append(name)
            for af in a.iter(f"{{{ARXIV_NS}}}affiliation"):
                if af.text:
                    affils.add(af.text.strip())
        if not link or not title:
            continue
        items.append({
            "title": title,
            "link": normalize_arxiv_id(link),
            "source": f"arXiv {category}",
            "published": published,
            "summary": summary,
            "authors": authors[:AUTHORS_CAP],
            "affiliations": sorted(affils),
        })
    return items


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def fetch_one(category: str, days: int, max_results: int) -> tuple[list[dict], str | None]:
    url = build_query_url(category, days, max_results)
    try:
        raw = http_get(url)
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code}: {e.reason}"
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return [], str(e)
    return parse_atom(raw, category), None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7,
                    help="rolling window in days (default: 7). Unlike fetch_rss.py "
                         "this is a real submittedDate range, not a feed-time filter.")
    ap.add_argument("--out", default="/tmp/semi_arxiv.json")
    ap.add_argument("--max-per-category", type=int, default=200,
                    help="API cap is 2000; default 200 covers a week comfortably")
    ap.add_argument("--categories", default=None,
                    help="comma-separated arXiv category IDs (e.g. cs.AR,cs.LG); "
                         "default reads arxiv_categories from sources.yaml")
    ap.add_argument("--exclude-seen", default=None,
                    help="path to .seen_urls.json — drop URLs already published. "
                         "Match is on version-stripped arXiv IDs so v1/v2 dedup correctly.")
    ap.add_argument("--probe", action="store_true",
                    help="hit one category just to check API health, write nothing")
    args = ap.parse_args()

    if args.categories:
        cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    else:
        cats = load_categories(SOURCES)
    if not cats:
        print(f"no categories configured (set arxiv_categories in {SOURCES} "
              f"or pass --categories)", file=sys.stderr)
        return 2

    if args.probe:
        cats = cats[:1]
        print(f"probe: querying {cats[0]} only", file=sys.stderr)

    all_items: list[dict] = []
    failures: list[tuple[str, str]] = []

    for i, cat in enumerate(cats):
        if i > 0:
            time.sleep(RATE_LIMIT_SEC)
        items, err = fetch_one(cat, args.days, args.max_per_category)
        if err:
            print(f"  ✗ {cat}: {err}", file=sys.stderr)
            failures.append((cat, err))
            continue
        print(f"  ✓ {cat}: {len(items)} item(s)", file=sys.stderr)
        all_items.extend(items)

    if args.probe:
        return 0 if not failures else 2

    # Dedupe within run (multiple categories can return the same cross-listed paper).
    seen_ids = set()
    deduped: list[dict] = []
    for it in all_items:
        if it["link"] in seen_ids:
            continue
        seen_ids.add(it["link"])
        deduped.append(it)

    # Cross-edition dedup via .seen_urls.json (handles version-suffix mismatch).
    if args.exclude_seen:
        seen_path = Path(args.exclude_seen)
        if seen_path.exists():
            try:
                already = json.loads(seen_path.read_text(encoding="utf-8"))
                if not isinstance(already, dict):
                    already = {}
            except json.JSONDecodeError as e:
                print(f"warning: {seen_path} malformed ({e}); ignoring", file=sys.stderr)
                already = {}
            today = datetime.now(timezone.utc).date().isoformat()
            # Normalize keys in the .seen map too — entries written by older
            # versions of build_page.py may carry version suffixes.
            already_norm: dict[str, str] = {}
            for u, d in already.items():
                already_norm[normalize_arxiv_id(u)] = d
            before = len(deduped)
            deduped = [
                it for it in deduped
                if already_norm.get(it["link"], today) >= today
            ]
            dropped = before - len(deduped)
            if dropped:
                print(f"excluded {dropped} item(s) already in {seen_path}",
                      file=sys.stderr)
        else:
            print(f"(--exclude-seen file {seen_path} not found; first run, "
                  f"nothing to exclude)", file=sys.stderr)

    deduped.sort(key=lambda it: it["published"] or "", reverse=True)
    Path(args.out).write_text(
        json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {len(deduped)} item(s) to {args.out}", file=sys.stderr)
    if failures:
        print(f"({len(failures)} categor{'y' if len(failures) == 1 else 'ies'} failed)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
