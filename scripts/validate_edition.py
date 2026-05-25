#!/usr/bin/env python3
"""Post-LLM step of the scripted daily pipeline.

After the agent writes output/edition.json, this script verifies it's
*genuinely today's work*, not a re-stamp of yesterday or a thin/fabricated
edition. Designed specifically to catch the failure modes weak/cheap LLMs
exhibit when given an open-ended skill prompt:

  - Re-stamping yesterday's edition.json with a new date (the openclaw bug
    we hit repeatedly on 2026-05-{22..24})
  - Inventing URLs that aren't in the fetched candidates
  - Producing too few items
  - Skipping a required field
  - Wrong date

If any check fails, exits non-zero. The orchestrator (run_daily.sh) treats
that as "do not render, do not commit, do not publish." Yesterday's site
stays live until the next successful run.

Usage:
  python3 scripts/validate_edition.py
  python3 scripts/validate_edition.py --min-stories 6 --min-papers 0
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
EDITION = OUTPUT / "edition.json"
PREVIOUS = OUTPUT / "edition.json.previous"
PREFLIGHT = Path("/tmp/preflight")

# Default thresholds. Override via CLI flags.
DEFAULT_MIN_STORIES = 5
DEFAULT_MIN_PAPERS = 0          # research may be empty on weekends
DEFAULT_FRESHNESS = 0.5         # ≥50% of URLs must not appear in yesterday's edition


# ---------------------------------------------------------------------------
# Single check helpers — each returns (ok: bool, message: str). We collect
# all failures and print them together so the agent (or operator) sees the
# full picture, not just the first error.
# ---------------------------------------------------------------------------
def check_file_exists() -> tuple[bool, str]:
    if not EDITION.exists():
        return False, f"output/edition.json does not exist. The agent never wrote it."
    return True, f"{EDITION} exists"


def check_parses(text: str) -> tuple[bool, str, dict | None]:
    try:
        d = json.loads(text)
        return True, "edition.json parses as JSON", d
    except json.JSONDecodeError as e:
        return False, f"edition.json is not valid JSON: {e}", None


def check_date(edition: dict, today: str) -> tuple[bool, str]:
    d = edition.get("date")
    if not d:
        return False, "edition.date is missing"
    if d != today:
        return False, f"edition.date is '{d}' but today (UTC) is '{today}'"
    return True, f"edition.date == {today}"


def collect_urls(edition: dict) -> tuple[set[str], set[str]]:
    """Return (news_urls, paper_urls) from the edition."""
    news = set()
    for section in edition.get("sections") or []:
        for story in section.get("stories") or []:
            u = story.get("url")
            if u:
                news.add(u)
    papers = set()
    research = edition.get("research") or {}
    for area in research.get("areas") or []:
        for paper in area.get("papers") or []:
            u = paper.get("venue_url") or paper.get("url")
            if u:
                papers.add(u)
    return news, papers


def count_stories(edition: dict) -> int:
    return sum(len(s.get("stories") or []) for s in (edition.get("sections") or []))


def count_papers(edition: dict) -> int:
    research = edition.get("research") or {}
    return sum(len(a.get("papers") or []) for a in (research.get("areas") or []))


def check_min_counts(edition: dict, min_stories: int, min_papers: int) -> list[tuple[bool, str]]:
    out = []
    n = count_stories(edition)
    out.append((n >= min_stories,
                f"stories: {n} (need ≥ {min_stories})"))
    p = count_papers(edition)
    out.append((p >= min_papers,
                f"papers: {p} (need ≥ {min_papers})"))
    return out


def check_required_fields(edition: dict) -> list[tuple[bool, str]]:
    """Spot-check that each story/paper has the minimum fields the renderer
    expects. We don't lint *everything* — that's the renderer's job — but we
    catch the common 'forgot a field' cases."""
    fails = []
    for s_idx, section in enumerate(edition.get("sections") or []):
        for st_idx, st in enumerate(section.get("stories") or []):
            path = f"sections[{s_idx}].stories[{st_idx}]"
            for field in ("url", "title", "summary"):
                if not st.get(field):
                    fails.append((False, f"{path}: missing '{field}'"))
            t = st.get("title") or {}
            if not t.get("en"):
                fails.append((False, f"{path}.title.en is empty"))
            su = st.get("summary") or {}
            if not su.get("en"):
                fails.append((False, f"{path}.summary.en is empty"))
            if su.get("en") and len(su["en"]) < 60:
                fails.append((False, f"{path}.summary.en is suspiciously short "
                                     f"({len(su['en'])} chars)"))
    research = edition.get("research") or {}
    for a_idx, area in enumerate(research.get("areas") or []):
        for p_idx, p in enumerate(area.get("papers") or []):
            path = f"research.areas[{a_idx}].papers[{p_idx}]"
            url = p.get("venue_url") or p.get("url")
            if not url:
                fails.append((False, f"{path}: missing venue_url/url"))
            if not (p.get("title") or {}).get("en"):
                fails.append((False, f"{path}.title.en is empty"))
            if not (p.get("summary") or {}).get("en"):
                fails.append((False, f"{path}.summary.en is empty"))
    if not fails:
        return [(True, "required fields present")]
    return fails


def check_urls_in_candidates(news_urls: set[str], paper_urls: set[str]) -> list[tuple[bool, str]]:
    """Every URL in edition.json must be in the preflight candidate files.

    This is the core anti-re-stamp check. The preflight script wrote
    /tmp/preflight/news.json and research.json with deduped, fetched URLs
    (research.json is the merged union of arXiv + Semantic Scholar + research
    RSS feeds). Any URL in edition.json that's NOT in those files is either:
      - fabricated (the LLM made it up), OR
      - from a previous edition (the LLM reused yesterday's content)
    Both are failures.
    """
    news_cand = PREFLIGHT / "news.json"
    research_cand = PREFLIGHT / "research.json"
    # Back-compat: older preflight versions wrote arxiv.json instead of
    # research.json. Fall back to it if research.json is missing.
    if not research_cand.exists():
        research_cand = PREFLIGHT / "arxiv.json"
    out = []

    if not news_cand.exists():
        out.append((False, f"preflight news file missing: {news_cand} — run preflight.py first"))
        return out

    cand_news = {it["link"] for it in json.loads(news_cand.read_text(encoding="utf-8"))}
    cand_papers: set[str] = set()
    if research_cand.exists():
        cand_papers = {it["link"] for it in json.loads(research_cand.read_text(encoding="utf-8"))}

    rogue_news = news_urls - cand_news
    if rogue_news:
        out.append((False,
                    f"{len(rogue_news)} news URL(s) in edition.json are NOT in the "
                    f"preflight candidates (fabricated or reused from a past edition):"))
        for u in sorted(rogue_news)[:5]:
            out.append((False, f"    - {u}"))
        if len(rogue_news) > 5:
            out.append((False, f"    ...and {len(rogue_news) - 5} more"))
    else:
        out.append((True, f"all {len(news_urls)} news URLs came from preflight candidates"))

    rogue_papers = paper_urls - cand_papers
    if rogue_papers and cand_papers:
        out.append((False,
                    f"{len(rogue_papers)} paper URL(s) in edition.json are NOT in "
                    f"the preflight research candidates ({research_cand.name}):"))
        for u in sorted(rogue_papers)[:5]:
            out.append((False, f"    - {u}"))
    elif paper_urls:
        out.append((True, f"all {len(paper_urls)} paper URLs came from preflight candidates"))
    return out


def check_not_a_restamp(news_urls: set[str], paper_urls: set[str],
                       threshold: float) -> list[tuple[bool, str]]:
    """If output/edition.json.previous exists, the new edition's URLs must
    differ by at least `threshold` (default 0.5 = 50%). Otherwise it looks
    like a re-stamp.
    """
    if not PREVIOUS.exists():
        return [(True, "no previous edition to compare against (first run?)")]
    try:
        prev = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [(True, "previous edition not parseable — skipping re-stamp check")]
    prev_news, prev_papers = collect_urls(prev)
    today_all = news_urls | paper_urls
    prev_all = prev_news | prev_papers
    if not today_all:
        return [(False, "edition.json contains no URLs at all")]
    if not prev_all:
        return [(True, "previous edition had no URLs (skipping diff)")]
    overlap = today_all & prev_all
    fresh_frac = 1.0 - (len(overlap) / len(today_all))
    msg = (f"freshness: {len(today_all) - len(overlap)}/{len(today_all)} "
           f"URLs are new vs yesterday ({fresh_frac:.0%})")
    if fresh_frac < threshold:
        return [(False, f"{msg} — below {threshold:.0%} threshold. "
                        f"This looks like a re-stamp of yesterday's edition.")]
    return [(True, msg)]


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-stories", type=int, default=DEFAULT_MIN_STORIES)
    ap.add_argument("--min-papers", type=int, default=DEFAULT_MIN_PAPERS)
    ap.add_argument("--freshness", type=float, default=DEFAULT_FRESHNESS,
                    help="min fraction of URLs that must be new vs the previous edition")
    args = ap.parse_args()

    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    results: list[tuple[bool, str]] = []

    ok, msg = check_file_exists()
    results.append((ok, msg))
    if not ok:
        return print_results(results)

    text = EDITION.read_text(encoding="utf-8")
    ok, msg, edition = check_parses(text)
    results.append((ok, msg))
    if not ok or edition is None:
        return print_results(results)

    results.append(check_date(edition, today))
    results.extend(check_min_counts(edition, args.min_stories, args.min_papers))
    results.extend(check_required_fields(edition))

    news_urls, paper_urls = collect_urls(edition)
    results.extend(check_urls_in_candidates(news_urls, paper_urls))
    results.extend(check_not_a_restamp(news_urls, paper_urls, args.freshness))

    return print_results(results)


def print_results(results: list[tuple[bool, str]]) -> int:
    fails = [(ok, m) for ok, m in results if not ok]
    for ok, m in results:
        prefix = "  ✓" if ok else "  ✗"
        print(f"{prefix} {m}")
    print()
    if fails:
        print(f"VALIDATION FAILED ({len(fails)} issue(s)). "
              f"Pipeline aborted; site not updated.", file=sys.stderr)
        return 1
    print("validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
