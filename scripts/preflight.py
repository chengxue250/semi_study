#!/usr/bin/env python3
"""Pre-LLM step of the scripted daily pipeline.

What this does (in order):

  1. Moves any existing output/edition.json to output/edition.json.previous
     so the agent literally cannot re-use yesterday's file.
  2. Runs the fetch scripts with --exclude-seen so all candidates are
     guaranteed-fresh:
       - fetch_rss.py (news, last 24h)        — required
       - fetch_arxiv.py (papers, last 7d)     — required-ish (weekend may be empty)
       - fetch_semscholar.py (papers, 14d)    — best-effort (free tier rate-limits)
       - fetch_rss.py --role research (168h)  — best-effort (Nature Electronics etc)
  3. Merges all three research sources (arXiv + Semantic Scholar + research RSS)
     into a single /tmp/preflight/research.json, deduped by URL.
  4. Trims each list down to a manageable size (default 80 news + 80
     research items, newest first) so a weak/cheap LLM with a small context
     window can ingest the input.
  5. Writes:
       /tmp/preflight/news.json                  (shortlisted news candidates)
       /tmp/preflight/research.json              (merged shortlisted research)
       /tmp/preflight/research_arxiv.json        (raw arXiv pull, for debugging)
       /tmp/preflight/research_semscholar.json   (raw S2 pull, for debugging)
       /tmp/preflight/research_rss.json          (raw research RSS pull, for debugging)
       /tmp/preflight/instructions.txt           (tiny "agent, read this" note)
  6. Aborts the run if the news fetch returned suspiciously little
     (configurable threshold). Empty research is tolerated (weekend gap).

After this exits 0, the agent only needs to write output/edition.json.
Everything else (rendering, archiving, publishing) is handled by other
scripts in the pipeline.

Usage:
  python3 scripts/preflight.py
  python3 scripts/preflight.py --top-news 50 --top-research 50
  python3 scripts/preflight.py --min-news 0       # tolerate empty fetches
  python3 scripts/preflight.py --skip-semscholar  # if it rate-limits, run other 2

Env (optional):
  SEMSCHOLAR_API_KEY    enables higher-rate Semantic Scholar calls
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


def run_best_effort(cmd: list[str], label: str) -> bool:
    """Run a subprocess. Log a warning on failure but don't raise. Returns
    True iff the command exited 0.

    Used for sources we *want* but can live without (Semantic Scholar
    rate-limiting, a flaky third-party RSS feed).
    """
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ! {label} failed (exit {e.returncode}); continuing without it",
              file=sys.stderr)
        return False


def load_json_or_empty(path: Path) -> list:
    """Load a JSON file or return [] if missing/malformed. Used to keep the
    merge step robust to a fetch script having failed silently."""
    if not path.exists():
        return []
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except json.JSONDecodeError:
        return []


def merge_dedup_by_url(*lists: list[dict]) -> list[dict]:
    """Merge multiple lists of {link, ...} items, dedup by link, preserve
    first occurrence (so a paper that appears in multiple sources gets the
    first one's metadata)."""
    seen: set[str] = set()
    out: list[dict] = []
    for lst in lists:
        for it in lst:
            link = it.get("link") or it.get("url") or it.get("venue_url")
            if not link or link in seen:
                continue
            seen.add(link)
            out.append(it)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-news", type=int, default=80,
                    help="how many news candidates to expose to the agent (newest first)")
    ap.add_argument("--top-research", type=int, default=80,
                    help="how many research candidates to expose to the agent (newest first)")
    ap.add_argument("--min-news", type=int, default=10,
                    help="abort the pipeline if news fetch returns fewer than this")
    ap.add_argument("--min-research", type=int, default=0,
                    help="abort the pipeline if research merge returns fewer than this "
                         "(default 0: empty research is fine, e.g. on weekends)")
    ap.add_argument("--skip-semscholar", action="store_true",
                    help="skip the Semantic Scholar fetch entirely "
                         "(useful when you know S2 is rate-limiting and you don't have an API key)")
    ap.add_argument("--skip-research-rss", action="store_true",
                    help="skip the role=research RSS fetch (Nature Electronics etc)")
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

    # ----- 2. News fetch (required) ------------------------------------------
    news_raw = PREFLIGHT / "news_full.json"
    step("fetching news (last 24h, deduped)")
    run([
        sys.executable, str(ROOT / "scripts/fetch_rss.py"),
        "--since-hours", "24",
        "--exclude-seen", str(SEEN_URLS),
        "--out", str(news_raw),
    ])
    news_items = load_json_or_empty(news_raw)
    step(f"news: {len(news_items)} items")

    if len(news_items) < args.min_news:
        print(f"\nERROR: news fetch returned {len(news_items)} items, "
              f"below threshold {args.min_news}. Aborting.", file=sys.stderr)
        print("Common causes: feeds down, --exclude-seen too aggressive, "
              "no real news today.", file=sys.stderr)
        return 2

    # ----- 3. Research fetches (multiple sources, best-effort) ----------------
    arxiv_out = PREFLIGHT / "research_arxiv.json"
    semscholar_out = PREFLIGHT / "research_semscholar.json"
    research_rss_out = PREFLIGHT / "research_rss.json"

    step("fetching arxiv (last 7 days, deduped)")
    # arxiv is "required-ish" — fail soft (weekend / rate-limit) but log it.
    run_best_effort([
        sys.executable, str(ROOT / "scripts/fetch_arxiv.py"),
        "--days", "7",
        "--exclude-seen", str(SEEN_URLS),
        "--out", str(arxiv_out),
    ], "arxiv")

    if not args.skip_semscholar:
        step("fetching semantic scholar (last 14 days, best-effort)")
        run_best_effort([
            sys.executable, str(ROOT / "scripts/fetch_semscholar.py"),
            "--days", "14",
            "--exclude-seen", str(SEEN_URLS),
            "--out", str(semscholar_out),
        ], "semscholar")
    else:
        step("skip: semantic scholar")
        # Make sure stale data from a previous run doesn't leak in.
        if semscholar_out.exists():
            semscholar_out.unlink()

    if not args.skip_research_rss:
        step("fetching research RSS (Nature Electronics, etc; 168h)")
        run_best_effort([
            sys.executable, str(ROOT / "scripts/fetch_rss.py"),
            "--role", "research",
            "--since-hours", "168",
            "--exclude-seen", str(SEEN_URLS),
            "--out", str(research_rss_out),
        ], "research-rss")
    else:
        step("skip: research RSS")
        if research_rss_out.exists():
            research_rss_out.unlink()

    arxiv_items = load_json_or_empty(arxiv_out)
    semscholar_items = load_json_or_empty(semscholar_out)
    research_rss_items = load_json_or_empty(research_rss_out)

    step(f"research raw: arxiv={len(arxiv_items)}, "
         f"semscholar={len(semscholar_items)}, "
         f"rss={len(research_rss_items)}")

    # ----- 4. Merge research sources (dedup by URL) ---------------------------
    # Order matters for tie-breaking on metadata: arXiv first (richest authors/
    # affiliations), then S2 (richest venue/DOI), then RSS (sparser).
    research_merged = merge_dedup_by_url(
        arxiv_items, semscholar_items, research_rss_items
    )
    step(f"research merged: {len(research_merged)} unique items "
         f"(across {len(arxiv_items) + len(semscholar_items) + len(research_rss_items)} raw)")

    if len(research_merged) < args.min_research:
        print(f"\nERROR: research merge returned {len(research_merged)} items, "
              f"below threshold {args.min_research}. Aborting.", file=sys.stderr)
        return 2

    # ----- 5. Shortlist --------------------------------------------------------
    news_short = shortlist_newest(news_items, args.top_news)
    research_short = shortlist_newest(research_merged, args.top_research)
    step(f"shortlisted: news={len(news_short)}, research={len(research_short)}")

    news_final = PREFLIGHT / "news.json"
    research_final = PREFLIGHT / "research.json"
    news_final.write_text(json.dumps(news_short, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    research_final.write_text(json.dumps(research_short, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    # Back-compat: write /tmp/preflight/arxiv.json as a symlink-ish copy of
    # research.json so any old prompt or invocation that references "arxiv.json"
    # still finds something. Safe to remove this in a future cleanup.
    legacy = PREFLIGHT / "arxiv.json"
    legacy.write_text(json.dumps(research_short, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    # ----- 6. Write a minimal "agent, do this" pointer -----------------------
    (PREFLIGHT / "instructions.txt").write_text(
        "\n".join([
            f"Today's date (UTC): {today}",
            f"News candidates:     {news_final}  ({len(news_short)} items)",
            f"Research candidates: {research_final}  ({len(research_short)} items, merged across arXiv + Semantic Scholar + research RSS)",
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
