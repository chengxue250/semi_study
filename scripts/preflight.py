#!/usr/bin/env python3
"""Pre-LLM step of the scripted daily pipeline.

What this does (in order):

  1. Moves any existing output/edition.json to output/edition.json.previous
     so the agent literally cannot re-use yesterday's file.
  2. Runs fetch_rss.py and fetch_arxiv.py with --exclude-seen so all
     candidates are guaranteed-fresh.
  3. Trims each list down to a manageable size (default 80 news + 80
     papers, newest first) so a weak/cheap LLM with a small context
     window can ingest the input.
  4. Writes:
       /tmp/preflight/news.json       (shortlisted news candidates)
       /tmp/preflight/arxiv.json      (shortlisted paper candidates)
       /tmp/preflight/instructions.txt  (a tiny "agent, read this" note)
  5. Aborts the run if the fetches returned suspiciously little
     (configurable threshold).

After this exits 0, the agent only needs to write output/edition.json.
Everything else (rendering, archiving, publishing) is handled by other
scripts in the pipeline.

Usage:
  python3 scripts/preflight.py
  python3 scripts/preflight.py --top-news 50 --top-arxiv 50
  python3 scripts/preflight.py --min-news 0       # tolerate empty fetches
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
SEEN_URLS = OUTPUT / ".seen_urls.json"
PREFLIGHT = Path("/tmp/preflight")


def step(msg: str) -> None:
    print(f"  → {msg}", flush=True)


def shortlist_newest(items: list[dict], top: int) -> list[dict]:
    """Sort by published-date descending, take the first `top`.

    No editorial scoring — the agent does that. The script's only job here
    is to bound input size so a weak LLM can read the file.
    """
    def key(it: dict) -> str:
        return it.get("published") or ""
    items_sorted = sorted(items, key=key, reverse=True)
    return items_sorted[:top]


def run(cmd: list[str]) -> None:
    """Run a subprocess and stream its output. Raise on non-zero exit."""
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-news", type=int, default=80,
                    help="how many news candidates to expose to the agent (newest first)")
    ap.add_argument("--top-arxiv", type=int, default=80,
                    help="how many paper candidates to expose to the agent (newest first)")
    ap.add_argument("--min-news", type=int, default=10,
                    help="abort the pipeline if fetch returns fewer than this")
    ap.add_argument("--min-arxiv", type=int, default=0,
                    help="abort the pipeline if arxiv returns fewer than this "
                         "(default 0: empty arxiv is fine, e.g. on weekends)")
    args = ap.parse_args()

    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    print(f"preflight for {today}")

    # ----- 1. Backup any existing edition.json --------------------------------
    PREFLIGHT.mkdir(parents=True, exist_ok=True)
    edition = OUTPUT / "edition.json"
    backup = OUTPUT / "edition.json.previous"
    if edition.exists():
        shutil.move(str(edition), str(backup))
        step(f"backed up {edition.name} → {backup.name}")
    else:
        if backup.exists():
            step("no current edition.json (previous backup still exists)")
        else:
            step("no existing edition.json (first run)")

    # ----- 2. Fresh fetches ---------------------------------------------------
    news_raw = PREFLIGHT / "news_full.json"
    arxiv_raw = PREFLIGHT / "arxiv_full.json"

    step("fetching news (last 24h, deduped)")
    run([
        sys.executable, str(ROOT / "scripts/fetch_rss.py"),
        "--since-hours", "24",
        "--exclude-seen", str(SEEN_URLS),
        "--out", str(news_raw),
    ])

    step("fetching arxiv (last 7 days, deduped)")
    run([
        sys.executable, str(ROOT / "scripts/fetch_arxiv.py"),
        "--days", "7",
        "--exclude-seen", str(SEEN_URLS),
        "--out", str(arxiv_raw),
    ])

    news_items = json.loads(news_raw.read_text(encoding="utf-8"))
    arxiv_items = json.loads(arxiv_raw.read_text(encoding="utf-8"))
    step(f"raw: news={len(news_items)}, arxiv={len(arxiv_items)}")

    # ----- 3. Threshold checks ------------------------------------------------
    if len(news_items) < args.min_news:
        print(f"\nERROR: news fetch returned {len(news_items)} items, "
              f"below threshold {args.min_news}. Aborting.", file=sys.stderr)
        print("Common causes: feeds down, --exclude-seen too aggressive, "
              "no real news today.", file=sys.stderr)
        return 2

    if len(arxiv_items) < args.min_arxiv:
        print(f"\nERROR: arxiv fetch returned {len(arxiv_items)} items, "
              f"below threshold {args.min_arxiv}. Aborting.", file=sys.stderr)
        return 2

    # ----- 4. Shortlist --------------------------------------------------------
    news_short = shortlist_newest(news_items, args.top_news)
    arxiv_short = shortlist_newest(arxiv_items, args.top_arxiv)
    step(f"shortlisted: news={len(news_short)}, arxiv={len(arxiv_short)}")

    news_out = PREFLIGHT / "news.json"
    arxiv_out = PREFLIGHT / "arxiv.json"
    news_out.write_text(json.dumps(news_short, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    arxiv_out.write_text(json.dumps(arxiv_short, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    # ----- 5. Write a minimal "agent, do this" pointer -----------------------
    (PREFLIGHT / "instructions.txt").write_text(
        "\n".join([
            f"Today's date (UTC): {today}",
            f"News candidates: {news_out}  ({len(news_short)} items)",
            f"Paper candidates: {arxiv_out}  ({len(arxiv_short)} items)",
            f"Yesterday's edition (do NOT reuse): {backup}",
            "",
            "Read PROMPT.md at the project root. Pick from the candidate",
            "files above, write output/edition.json. Do not run any other",
            "scripts; the orchestrator handles rendering and publishing.",
        ]),
        encoding="utf-8",
    )
    step(f"wrote {PREFLIGHT / 'instructions.txt'}")
    print("\npreflight ok — ready for agent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
