#!/usr/bin/env python3
"""Pull every RSS/Atom feed in references/sources.yaml and emit candidate stories.

Stdlib only — no `pip install` needed on any reasonable Python 3.9+ install.

Two modes:
  default          fetch all feeds, filter by --since-hours, write JSON
  --probe          HEAD/GET each feed, report status, write nothing

JSON shape (one entry per candidate):
  {
    "title":     "...",
    "link":      "...",
    "source":    "SemiAnalysis",
    "published": "2026-05-21T07:12:00+00:00",   # ISO8601 UTC if parseable
    "summary":   "..."                          # plain text, ~600 chars max
  }
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import email.utils as eut
import gzip
import html
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "references" / "sources.yaml"

UA = "Mozilla/5.0 (compatible; semi-news-daily/1.0; +https://github.com/)"
TIMEOUT = 15
MAX_PER_FEED = 30
SUMMARY_CAP = 600


# ---------------------------------------------------------------------------
# Minimal YAML reader — we only support the subset our sources.yaml uses.
# Avoids a PyYAML dependency so this script runs anywhere with stdlib python.
# ---------------------------------------------------------------------------
def load_feeds(path: Path) -> list[dict]:
    feeds: list[dict] = []
    in_feeds = False
    current: dict | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            in_feeds = line.startswith("feeds:")
            if current and in_feeds is False:
                feeds.append(current)
                current = None
            continue
        if not in_feeds:
            continue
        stripped = line.strip()
        if stripped.startswith("- name:"):
            if current:
                feeds.append(current)
            current = {"name": stripped.split(":", 1)[1].strip()}
        elif current is not None and ":" in stripped:
            k, v = stripped.split(":", 1)
            current[k.strip().lstrip("- ")] = v.strip()
    if current:
        feeds.append(current)
    return [f for f in feeds if f.get("url")]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def http_get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return resp.status, data


# ---------------------------------------------------------------------------
# Parsing — handle RSS 2.0 and Atom; tolerate broken XML by best-effort.
# ---------------------------------------------------------------------------
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
]


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    # RFC 2822 first
    try:
        dt = eut.parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    # ISO with trailing Z
    if s.endswith("Z"):
        try:
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def clean_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > SUMMARY_CAP:
        s = s[: SUMMARY_CAP - 1].rstrip() + "…"
    return s


def text(el, tag, nsmap=None) -> str:
    if el is None:
        return ""
    node = el.find(tag, nsmap) if nsmap else el.find(tag)
    return (node.text or "").strip() if node is not None and node.text else ""


def parse_feed(name: str, raw: bytes) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    items: list[dict] = []
    # RSS 2.0
    for it in root.iter("item"):
        link = text(it, "link")
        if not link:
            guid = text(it, "guid")
            if guid.startswith("http"):
                link = guid
        date_raw = text(it, "pubDate") or text(it, "{http://purl.org/dc/elements/1.1/}date")
        body = text(it, "description") or text(it, "{http://purl.org/rss/1.0/modules/content/}encoded")
        items.append({
            "title": clean_html(text(it, "title"))[:300],
            "link": link,
            "source": name,
            "published_raw": date_raw,
            "summary": clean_html(body),
        })
    # Atom
    if not items:
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = (link_el.get("href") if link_el is not None else "") or ""
            date_raw = text(entry, "{http://www.w3.org/2005/Atom}updated") \
                or text(entry, "{http://www.w3.org/2005/Atom}published")
            body_el = entry.find("{http://www.w3.org/2005/Atom}summary") \
                or entry.find("{http://www.w3.org/2005/Atom}content")
            body = "".join(body_el.itertext()) if body_el is not None else ""
            items.append({
                "title": clean_html(text(entry, "{http://www.w3.org/2005/Atom}title"))[:300],
                "link": link,
                "source": name,
                "published_raw": date_raw,
                "summary": clean_html(body),
            })
    return items[:MAX_PER_FEED]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def fetch_one(feed: dict) -> tuple[dict, list[dict], str | None]:
    try:
        status, data = http_get(feed["url"])
        if status != 200:
            return feed, [], f"http {status}"
        items = parse_feed(feed["name"], data)
        return feed, items, None
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return feed, [], str(e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-hours", type=int, default=36,
                    help="discard entries older than this many hours")
    ap.add_argument("--out", default="/tmp/semi_rss.json",
                    help="output JSON path")
    ap.add_argument("--probe", action="store_true",
                    help="just report feed health, write nothing")
    ap.add_argument("--max-workers", type=int, default=12)
    ap.add_argument("--role", default=None,
                    help="filter to feeds with the given role (e.g. 'research'); "
                         "default is feeds with no role set (i.e. news feeds)")
    args = ap.parse_args()

    feeds = load_feeds(SOURCES)
    if not feeds:
        print(f"no feeds parsed from {SOURCES}", file=sys.stderr)
        return 2

    if args.role == "research":
        feeds = [f for f in feeds if f.get("role") == "research"]
    elif args.role:
        feeds = [f for f in feeds if f.get("role") == args.role]
    else:
        # Default: news feeds — anything without a role, OR with role: news.
        feeds = [f for f in feeds if f.get("role", "news") == "news"]
    if not feeds:
        print(f"no feeds match role={args.role}", file=sys.stderr)
        return 2

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)
    all_items: list[dict] = []
    failures: list[tuple[str, str]] = []

    with cf.ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        for feed, items, err in pool.map(fetch_one, feeds):
            if err:
                failures.append((feed["name"], err))
                print(f"  ✗ {feed['name']}: {err}", file=sys.stderr)
                continue
            kept = 0
            for it in items:
                dt = parse_date(it.pop("published_raw", None))
                if dt is None:
                    # No date — keep but mark as undated. Better than dropping.
                    it["published"] = None
                else:
                    if dt < cutoff:
                        continue
                    it["published"] = dt.isoformat()
                if not it.get("link") or not it.get("title"):
                    continue
                all_items.append(it)
                kept += 1
            print(f"  ✓ {feed['name']}: {kept} item(s)", file=sys.stderr)

    if args.probe:
        print(f"\nprobe: {len(feeds) - len(failures)} ok, {len(failures)} failed")
        for n, e in failures:
            print(f"  failed: {n} — {e}")
        return 0

    # Dedupe by URL.
    seen = set()
    deduped = []
    for it in all_items:
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        deduped.append(it)

    # Sort newest first; undated to the end.
    def sortkey(it):
        return (it["published"] is None, it["published"] or "")
    deduped.sort(key=sortkey, reverse=False)
    deduped.sort(key=lambda it: it["published"] or "", reverse=True)

    Path(args.out).write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {len(deduped)} item(s) to {args.out}", file=sys.stderr)
    if failures:
        print(f"({len(failures)} feed(s) failed — run with --probe to investigate)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
