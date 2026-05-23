#!/usr/bin/env python3
"""Render output/edition.json + assets/template.html → output/index.html.

Also rotates yesterday's index.html into output/archive/ and regenerates
output/archive.html.

Stdlib only.

edition.json shape (see SKILL.md § 6 for the full spec):

  {
    "date":   "2026-05-21",
    "theme":  {"en": "...", "zh": "..."},
    "dek":    {"en": "...", "zh": "..."},
    "sections": [
      {
        "id":    "ai-accelerators",
        "title": {"en": "AI & Accelerators", "zh": "AI与加速器"},
        "stories": [
          {
            "featured": true,
            "title":   {"en": "...", "zh": "..."},
            "summary": {"en": "...", "zh": "..."},
            "source":  "SemiAnalysis",
            "url":     "https://...",
            "published": "2026-05-21T08:30:00Z"
          }
        ]
      }
    ]
  }
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = ROOT / "assets" / "template.html"
DEFAULT_RESEARCH_TEMPLATE = ROOT / "assets" / "research-template.html"
DEFAULT_EDITION = ROOT / "output" / "edition.json"
OUT_DIR = ROOT / "output"
ARCHIVE_DIR = OUT_DIR / "archive"
RESEARCH_ARCHIVE_DIR = OUT_DIR / "archive" / "research"
SEEN_URLS_PATH = OUT_DIR / ".seen_urls.json"
SEEN_RETENTION_DAYS = 90

ZH_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
ZH_MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]


def e(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def relative_time(iso: str | None, now: dt.datetime) -> tuple[str, str]:
    """Return (english, chinese) relative time strings, e.g. ("4h ago", "4小时前")."""
    if not iso:
        return ("", "")
    try:
        when = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ("", "")
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    delta = now - when.astimezone(dt.timezone.utc)
    secs = int(delta.total_seconds())
    if secs < 60:
        return ("just now", "刚刚")
    if secs < 3600:
        m = secs // 60
        return (f"{m}m ago", f"{m}分钟前")
    if secs < 86400:
        h = secs // 3600
        return (f"{h}h ago", f"{h}小时前")
    d = secs // 86400
    if d <= 7:
        return (f"{d}d ago", f"{d}天前")
    # Past a week — show date.
    label = when.strftime("%b %d")
    return (label, f"{when.month}月{when.day}日")


def render_story(story: dict, now: dt.datetime) -> str:
    featured = " featured" if story.get("featured") else ""
    t = story.get("title", {})
    s = story.get("summary", {})
    rel_en, rel_zh = relative_time(story.get("published"), now)
    url = story.get("url", "#")
    src = story.get("source", "")
    meta_en = f'<span class="source">{e(src)}</span>' + (f' · {e(rel_en)}' if rel_en else "")
    meta_zh = f'<span class="source">{e(src)}</span>' + (f' · {e(rel_zh)}' if rel_zh else "")
    return f"""    <article class="story{featured}">
      <h3>
        <a href="{e(url)}" target="_blank" rel="noopener">
          <span class="en">{e(t.get("en", ""))}</span>
          <span class="zh">{e(t.get("zh", ""))}</span>
        </a>
      </h3>
      <div class="meta">
        <span class="en">{meta_en}</span>
        <span class="zh">{meta_zh}</span>
      </div>
      <p class="summary">
        <span class="en">{e(s.get("en", ""))}</span>
        <span class="zh">{e(s.get("zh", ""))}</span>
      </p>
    </article>"""


def render_paper(p: dict) -> str:
    t = p.get("title", {})
    s = p.get("summary", {})
    authors = p.get("authors", "")
    affil = p.get("affiliation", "")
    venue = p.get("venue", "")
    venue_url = p.get("venue_url") or p.get("url") or "#"
    published = p.get("published", "")
    tags = p.get("tags") or []
    tag_html = "".join(f'<span class="tag">{e(t)}</span>' for t in tags)
    affil_block = f'<p class="affil">{e(affil)}</p>' if affil else ""
    venue_line = ""
    if venue or published:
        bits = []
        if venue:
            bits.append(f'<a href="{e(venue_url)}" target="_blank" rel="noopener">{e(venue)}</a>')
        if published:
            bits.append(e(published))
        venue_line = ' · '.join(bits)
    return f"""    <article class="paper">
      <h3>
        <a href="{e(venue_url)}" target="_blank" rel="noopener">
          <span class="en">{e(t.get("en", ""))}</span>
          <span class="zh">{e(t.get("zh", ""))}</span>
        </a>{tag_html}
      </h3>
      <p class="authors">{e(authors)}</p>
      {affil_block}
      <p class="venue">{venue_line}</p>
      <p class="summary">
        <span class="en">{e(s.get("en", ""))}</span>
        <span class="zh">{e(s.get("zh", ""))}</span>
      </p>
    </article>"""


def render_area(area: dict) -> str:
    papers = area.get("papers") or []
    if not papers:
        return ""
    title = area.get("title", {})
    aid = area.get("id", "")
    body = "\n".join(render_paper(p) for p in papers)
    return f"""  <section class="area" id="{e(aid)}">
    <h2>
      <span class="en">{e(title.get("en", ""))}</span>
      <span class="zh">{e(title.get("zh", ""))}</span>
    </h2>
{body}
  </section>"""


def render_research_page(edition: dict, template: str, now: dt.datetime) -> str:
    research = edition.get("research") or {}
    date_str = edition.get("date") or now.date().isoformat()
    date_obj = dt.date.fromisoformat(date_str)
    theme = research.get("theme", {})
    dek = research.get("dek", {})

    date_long_en = (date_obj.strftime("%A, %B %-d, %Y")
                    if sys.platform != "win32"
                    else date_obj.strftime("%A, %B %d, %Y"))
    date_long_zh = (f"{date_obj.year}年{ZH_MONTHS[date_obj.month - 1]}"
                    f"{date_obj.day}日 {ZH_WEEKDAYS[date_obj.weekday()]}")

    areas = research.get("areas") or []
    areas_html = "\n".join(render_area(a) for a in areas)
    paper_count = sum(len(a.get("papers") or []) for a in areas)

    window_days = research.get("window_days", 7)
    win_en = f"{window_days} day{'s' if window_days != 1 else ''}"
    win_zh = f"{window_days}天"

    generated = now.strftime("%Y-%m-%d %H:%M UTC")

    return (template
            .replace("{{ISO_DATE}}", e(date_str))
            .replace("{{DATE}}", e(date_str))
            .replace("{{DATE_LONG_EN}}", e(date_long_en))
            .replace("{{DATE_LONG_ZH}}", e(date_long_zh))
            .replace("{{RESEARCH_THEME_EN}}", e(theme.get("en", "")))
            .replace("{{RESEARCH_THEME_ZH}}", e(theme.get("zh", "")))
            .replace("{{RESEARCH_DEK_EN}}", e(dek.get("en", "")))
            .replace("{{RESEARCH_DEK_ZH}}", e(dek.get("zh", "")))
            .replace("{{RESEARCH_AREAS}}", areas_html)
            .replace("{{RESEARCH_WINDOW_EN}}", e(win_en))
            .replace("{{RESEARCH_WINDOW_ZH}}", e(win_zh))
            .replace("{{PAPER_COUNT}}", e(str(paper_count)))
            .replace("{{GENERATED_AT}}", e(generated)))


def render_section(section: dict, now: dt.datetime) -> str:
    stories = section.get("stories") or []
    if not stories:
        return ""
    title = section.get("title", {})
    sid = section.get("id", "")
    body = "\n".join(render_story(s, now) for s in stories)
    return f"""  <section class="cat" id="{e(sid)}">
    <h2>
      <span class="en">{e(title.get("en", ""))}</span>
      <span class="zh">{e(title.get("zh", ""))}</span>
    </h2>
{body}
  </section>"""


def render_page(edition: dict, template: str, now: dt.datetime) -> str:
    date_str = edition.get("date") or now.date().isoformat()
    date_obj = dt.date.fromisoformat(date_str)
    theme = edition.get("theme", {})
    dek = edition.get("dek", {})

    date_long_en = date_obj.strftime("%A, %B %-d, %Y") if sys.platform != "win32" else date_obj.strftime("%A, %B %d, %Y")
    date_long_zh = f"{date_obj.year}年{ZH_MONTHS[date_obj.month - 1]}{date_obj.day}日 {ZH_WEEKDAYS[date_obj.weekday()]}"

    sections_html = "\n".join(render_section(s, now) for s in edition.get("sections", []))

    generated = now.strftime("%Y-%m-%d %H:%M UTC")

    return (template
            .replace("{{ISO_DATE}}", e(date_str))
            .replace("{{DATE}}", e(date_str))
            .replace("{{DATE_LONG_EN}}", e(date_long_en))
            .replace("{{DATE_LONG_ZH}}", e(date_long_zh))
            .replace("{{THEME_EN}}", e(theme.get("en", "")))
            .replace("{{THEME_ZH}}", e(theme.get("zh", "")))
            .replace("{{DEK_EN}}", e(dek.get("en", "")))
            .replace("{{DEK_ZH}}", e(dek.get("zh", "")))
            .replace("{{SECTIONS}}", sections_html)
            .replace("{{GENERATED_AT}}", e(generated)))


def rotate_to_archive(index_path: Path, today: str) -> Path | None:
    """If output/index.html exists with a different date than `today`, move it
    to archive/<that-date>.html. Returns the archived path, or None."""
    if not index_path.exists():
        return None
    text = index_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'<meta name="edition-date" content="([0-9-]+)"', text)
    if not m:
        return None
    prev_date = m.group(1)
    if prev_date == today:
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"{prev_date}.html"
    shutil.copyfile(index_path, dest)
    return dest


def extract_edition_metadata(html_path: Path) -> dict:
    """Pull date + theme out of an existing edition HTML for the archive index."""
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    date = ""
    theme_en = ""
    theme_zh = ""
    m = re.search(r'<meta name="edition-date" content="([0-9-]+)"', text)
    if m:
        date = m.group(1)
    m = re.search(r"<h1>\s*<span class=\"en\">([^<]*)</span>\s*<span class=\"zh\">([^<]*)</span>", text)
    if m:
        theme_en = html.unescape(m.group(1))
        theme_zh = html.unescape(m.group(2))
    return {"date": date, "theme_en": theme_en, "theme_zh": theme_zh, "href": html_path.name}


def regenerate_archive_index(today_file: Path) -> None:
    items: list[dict] = []
    # Today
    if today_file.exists():
        meta = extract_edition_metadata(today_file)
        meta["href"] = "index.html"
        items.append(meta)
    # Older
    if ARCHIVE_DIR.exists():
        for p in sorted(ARCHIVE_DIR.glob("*.html"), reverse=True):
            meta = extract_edition_metadata(p)
            meta["href"] = f"archive/{p.name}"
            items.append(meta)
    # Render a simple list page, sharing the template's CSS palette for visual continuity.
    rows = "\n".join(
        f'    <li><a href="{e(it["href"])}"><span class="date">{e(it["date"])}</span>'
        f'<span class="en"> — {e(it["theme_en"])}</span>'
        f'<span class="zh"> — {e(it["theme_zh"])}</span></a></li>'
        for it in items if it["date"]
    )
    page = f"""<!doctype html>
<html lang="en" data-lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Archive — Semi News Daily</title>
<style>
  :root {{
    --bg:#fbfaf7;--fg:#18181b;--muted:#6b6b6b;--rule:#e7e3da;--accent:#b1370b;
    --serif:"Newsreader","Charter","Iowan Old Style",Georgia,serif;
    --sans:-apple-system,BlinkMacSystemFont,"Inter","Helvetica Neue","PingFang SC",Arial,sans-serif;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14130f;--fg:#ece9e1;--muted:#9a9690;--rule:#2b2925;--accent:#e88a55; }}
  }}
  body {{ background:var(--bg);color:var(--fg);font-family:var(--sans);
         max-width:720px;margin:0 auto;padding:48px 20px 80px;line-height:1.55; }}
  h1 {{ font-family:var(--serif);font-weight:600;font-size:32px;margin:0 0 28px; }}
  .top {{ font-size:13px;color:var(--muted);margin-bottom:8px; }}
  .top a {{ color:var(--muted); }}
  ul {{ list-style:none;padding:0;margin:0; }}
  li {{ padding:14px 0;border-bottom:1px solid var(--rule); }}
  li a {{ color:var(--fg);text-decoration:none;display:flex;gap:14px;align-items:baseline; }}
  li a:hover .date {{ color:var(--accent); }}
  .date {{ font-family:var(--serif);font-variant-numeric:tabular-nums;color:var(--muted);min-width:104px; }}
  body[data-lang="en"] .zh {{ display:none; }}
  body[data-lang="zh"] .en {{ display:none; }}
</style>
</head>
<body>
  <div class="top"><a href="index.html">← <span class="en">today</span><span class="zh">今日</span></a></div>
  <h1><span class="en">Archive</span><span class="zh">往期</span></h1>
  <ul>
{rows}
  </ul>
</body>
</html>
"""
    (OUT_DIR / "archive.html").write_text(page, encoding="utf-8")


def update_seen_urls(edition: dict, today: str) -> tuple[int, int]:
    """Append today's news + research URLs to output/.seen_urls.json.

    Preserves the first-seen date for URLs already in the file (so same-day
    re-renders don't promote yesterday's articles to today). Prunes entries
    older than SEEN_RETENTION_DAYS to bound the file size — a year-old URL
    re-surfacing in RSS is rare, and if it does, treating it as new is fine.

    Returns (added, pruned).
    """
    existing: dict[str, str] = {}
    if SEEN_URLS_PATH.exists():
        try:
            existing = json.loads(SEEN_URLS_PATH.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except json.JSONDecodeError:
            existing = {}

    # Prune anything older than the retention window.
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    pruned = sum(1 for d in existing.values() if d < cutoff)
    existing = {u: d for u, d in existing.items() if d >= cutoff}

    # Collect URLs from this edition.
    added = 0
    for section in edition.get("sections", []) or []:
        for story in section.get("stories", []) or []:
            url = story.get("url")
            if url and url not in existing:
                existing[url] = today
                added += 1
    research = edition.get("research") or {}
    for area in research.get("areas", []) or []:
        for paper in area.get("papers", []) or []:
            url = paper.get("venue_url") or paper.get("url")
            if url and url not in existing:
                existing[url] = today
                added += 1

    SEEN_URLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_URLS_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return added, pruned


def rotate_research_to_archive(research_path: Path, today: str) -> Path | None:
    if not research_path.exists():
        return None
    text = research_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'<meta name="edition-date" content="([0-9-]+)"', text)
    if not m:
        return None
    prev_date = m.group(1)
    if prev_date == today:
        return None
    RESEARCH_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = RESEARCH_ARCHIVE_DIR / f"{prev_date}.html"
    shutil.copyfile(research_path, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", default=str(DEFAULT_EDITION))
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--research-template", default=str(DEFAULT_RESEARCH_TEMPLATE))
    args = ap.parse_args()

    edition_path = Path(args.edition)
    template_path = Path(args.template)
    research_template_path = Path(args.research_template)

    if not edition_path.exists():
        print(f"edition.json not found: {edition_path}", file=sys.stderr)
        return 2
    if not template_path.exists():
        print(f"template not found: {template_path}", file=sys.stderr)
        return 2

    edition = json.loads(edition_path.read_text(encoding="utf-8"))
    template = template_path.read_text(encoding="utf-8")
    now = dt.datetime.now(dt.timezone.utc)
    today = edition.get("date") or now.date().isoformat()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_path = OUT_DIR / "index.html"

    archived = rotate_to_archive(index_path, today)
    if archived:
        print(f"rotated previous edition → {archived}", file=sys.stderr)

    html_out = render_page(edition, template, now)
    index_path.write_text(html_out, encoding="utf-8")
    print(f"wrote {index_path}", file=sys.stderr)

    # Research page is optional — only render if the edition has a `research` block
    # with at least one area containing papers.
    research_path = OUT_DIR / "research.html"
    research = edition.get("research") or {}
    has_papers = any((a.get("papers") for a in research.get("areas", [])))
    if has_papers:
        if not research_template_path.exists():
            print(f"research template not found: {research_template_path}", file=sys.stderr)
            return 2
        r_template = research_template_path.read_text(encoding="utf-8")
        r_archived = rotate_research_to_archive(research_path, today)
        if r_archived:
            print(f"rotated previous research page → {r_archived}", file=sys.stderr)
        r_html = render_research_page(edition, r_template, now)
        research_path.write_text(r_html, encoding="utf-8")
        print(f"wrote {research_path}", file=sys.stderr)
    elif research_path.exists():
        # Keep the stale page so the cross-link from index.html still works.
        print(f"no research papers in edition; leaving existing {research_path} as-is",
              file=sys.stderr)

    regenerate_archive_index(index_path)
    print(f"refreshed archive index → {OUT_DIR / 'archive.html'}", file=sys.stderr)

    added, pruned = update_seen_urls(edition, today)
    print(f"seen_urls: +{added} new, -{pruned} pruned → {SEEN_URLS_PATH}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
