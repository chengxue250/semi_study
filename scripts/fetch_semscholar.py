#!/usr/bin/env python3
"""Fetch recent semiconductor/EE papers from the Semantic Scholar Graph API.

This complements fetch_arxiv.py:
- arXiv API covers preprints (arxiv.org submissions).
- Semantic Scholar covers conference proceedings (ISSCC, IEDM, VLSI, MICRO,
  ISCA, ASPLOS, HPCA, DAC, ICCAD, HotChips), journals (IEEE JSSC/TED/EDL,
  Nature Electronics, Science Advances), and many arXiv preprints too.

Together they give us defense-in-depth: a paper that lands in IEEE Xplore
without an arXiv version still surfaces through Semantic Scholar.

API docs: https://api.semanticscholar.org/api-docs/

**Important about rate limits:** Semantic Scholar's documented unauthenticated
quota is 1000 req/5min, but in practice the search endpoints rate-limit
*much* more aggressively than that — running our 10-query list back-to-back
typically gets 429s on most queries even with 5s spacing.

For real daily use, get a free API key at
https://www.semanticscholar.org/product/api and set SEMSCHOLAR_API_KEY in
env. With a key, all 10 queries reliably complete in ~12 seconds. Without
a key, expect partial results (the script degrades gracefully — each query
that 429s is skipped, others still run).

Stdlib only.

Usage:
  python3 scripts/fetch_semscholar.py
  python3 scripts/fetch_semscholar.py --days 14
  python3 scripts/fetch_semscholar.py --queries 'compute-in-memory,VLSI processor'
  python3 scripts/fetch_semscholar.py --exclude-seen output/.seen_urls.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "references" / "sources.yaml"

API_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
UA = "Mozilla/5.0 (compatible; semi-news-daily/1.0; +semscholar-fetcher)"
TIMEOUT = 30

# Semantic Scholar's documented unauthenticated quota is ~1k req / 5 min,
# but the search endpoints rate-limit harder than that — empirically even
# 5s spacing gets some 429s. Without an API key, expect partial coverage.
# With a key the throttle drops dramatically.
RATE_LIMIT_SEC = 5.0
RATE_LIMIT_SEC_KEYED = 1.0   # used if SEMSCHOLAR_API_KEY is set
BACKOFF_429_SEC = 15.0       # extra wait after a 429 before retrying

FIELDS = "title,abstract,authors,venue,publicationDate,year,externalIds,url,openAccessPdf"

SUMMARY_CAP = 1200
TITLE_CAP = 300
AUTHORS_CAP = 12
PER_QUERY_LIMIT = 50


# ---------------------------------------------------------------------------
# sources.yaml reader for semscholar_queries (flat list of strings)
# ---------------------------------------------------------------------------
def load_queries(path: Path) -> list[str]:
    queries: list[str] = []
    in_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            in_block = stripped.startswith("semscholar_queries:")
            continue
        if not in_block:
            continue
        if stripped.startswith("- "):
            val = stripped[2:].split("#")[0].strip().strip('"').strip("'")
            if val:
                queries.append(val)
    return queries


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def http_get_json(url: str, api_key: str | None) -> dict:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def search_one(query: str, days: int, api_key: str | None) -> list[dict]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    params = {
        "query": query,
        "limit": str(PER_QUERY_LIMIT),
        "fields": FIELDS,
        # S2 accepts ISO dates: YYYY-MM-DD:YYYY-MM-DD
        "publicationDateOrYear": f"{start.isoformat()}:{end.isoformat()}",
    }
    url = f"{API_BASE}?{urllib.parse.urlencode(params)}"
    # Try up to 3 times: original + 2 backoffs on 429.
    last_err: str | None = None
    for attempt in range(3):
        try:
            payload = http_get_json(url, api_key)
            return _normalize(payload.get("data") or [], query)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                # Exponential backoff: 8s, then 16s.
                wait = BACKOFF_429_SEC * (2 ** attempt)
                print(f"    429 on attempt {attempt + 1}; backing off {wait:.0f}s",
                      file=sys.stderr)
                time.sleep(wait)
                last_err = f"HTTP 429"
                continue
            last_err = f"HTTP {e.code}: {e.reason}"
            break
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            last_err = str(e)
            break
    raise RuntimeError(last_err or "unknown error")


# ---------------------------------------------------------------------------
# Response normalization → same shape as fetch_rss.py / fetch_arxiv.py
# ---------------------------------------------------------------------------
def _collapse(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _prefer_link(paper: dict) -> str:
    """Pick the best link for a paper: prefer the DOI URL, then arXiv abs,
    then S2's own URL. The link is what we use as the dedup key.
    """
    ext = paper.get("externalIds") or {}
    if ext.get("DOI"):
        return f"https://doi.org/{ext['DOI']}"
    if ext.get("ArXiv"):
        return f"http://arxiv.org/abs/{ext['ArXiv']}"
    oa = paper.get("openAccessPdf") or {}
    if oa.get("url"):
        return oa["url"]
    return paper.get("url") or ""


def _normalize(papers: list[dict], query: str) -> list[dict]:
    out: list[dict] = []
    for p in papers:
        link = _prefer_link(p)
        title = _collapse(p.get("title"))[:TITLE_CAP]
        if not link or not title:
            continue
        abstract = _collapse(p.get("abstract"))[:SUMMARY_CAP]
        authors_raw = p.get("authors") or []
        authors = [a.get("name", "").strip() for a in authors_raw if a.get("name")][:AUTHORS_CAP]
        out.append({
            "title": title,
            "link": link,
            "source": f"SemScholar [{query}]",
            "venue": (p.get("venue") or "").strip(),
            "published": (p.get("publicationDate") or str(p.get("year") or "")).strip(),
            "summary": abstract,
            "authors": authors,
            "affiliations": [],  # S2 affiliations require a separate /paper/{id} call; skip for now
        })
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14,
                    help="rolling window in days (default: 14). Slightly wider "
                         "than arXiv since journal/conference publication dates "
                         "lag the actual work.")
    ap.add_argument("--out", default="/tmp/semi_semscholar.json")
    ap.add_argument("--queries", default=None,
                    help="comma-separated; default reads semscholar_queries from sources.yaml")
    ap.add_argument("--exclude-seen", default=None,
                    help="path to .seen_urls.json — drop URLs already published")
    ap.add_argument("--probe", action="store_true",
                    help="just confirm the API responds; query one term, write nothing")
    args = ap.parse_args()

    if args.queries:
        queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    else:
        queries = load_queries(SOURCES)
    if not queries:
        print(f"no queries configured (set semscholar_queries in {SOURCES} "
              f"or pass --queries)", file=sys.stderr)
        return 2

    if args.probe:
        queries = queries[:1]
        print(f"probe: querying '{queries[0]}' only", file=sys.stderr)

    api_key = os.environ.get("SEMSCHOLAR_API_KEY")
    spacing = RATE_LIMIT_SEC_KEYED if api_key else RATE_LIMIT_SEC
    if api_key:
        print(f"(SEMSCHOLAR_API_KEY set; using {spacing}s spacing)", file=sys.stderr)
    else:
        print(f"(no API key; using {spacing}s spacing — set SEMSCHOLAR_API_KEY for faster runs)",
              file=sys.stderr)

    all_items: list[dict] = []
    failures: list[tuple[str, str]] = []

    for i, q in enumerate(queries):
        if i > 0:
            time.sleep(spacing)
        try:
            items = search_one(q, args.days, api_key)
            print(f"  ✓ '{q}': {len(items)} item(s)", file=sys.stderr)
            all_items.extend(items)
        except RuntimeError as e:
            print(f"  ✗ '{q}': {e}", file=sys.stderr)
            failures.append((q, str(e)))

    if args.probe:
        return 0 if not failures else 2

    # Dedupe within run (papers often hit multiple queries).
    seen_links = set()
    deduped: list[dict] = []
    for it in all_items:
        if it["link"] in seen_links:
            continue
        seen_links.add(it["link"])
        deduped.append(it)

    # Cross-edition dedup via .seen_urls.json.
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
            before = len(deduped)
            deduped = [
                it for it in deduped
                if already.get(it["link"], today) >= today
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
        print(f"({len(failures)} quer{'y' if len(failures) == 1 else 'ies'} failed)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
