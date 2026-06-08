#!/usr/bin/env python3
"""Build a bilingual daily podcast (English + 中文) from output/edition.json.

Design goals (per project constraint): **no third-party API, no extra LLM tokens.**

- The spoken script is assembled *deterministically* from the already-bilingual
  edition.json (titles + summaries are written in both languages by the news run),
  so no LLM call is needed to produce it — zero token cost.
- Audio is synthesized with macOS's built-in `say` command (offline, free) and
  written straight to .m4a (AAC) — no ffmpeg, no cloud TTS, no API key.

Outputs (under output/podcast/):
  YYYY-MM-DD.en.txt        spoken script (English)
  YYYY-MM-DD.zh.txt        spoken script (中文)
  YYYY-MM-DD.en.m4a        audio  (English)   — unless --no-audio
  YYYY-MM-DD.zh.m4a        audio  (中文)       — unless --no-audio
  YYYY-MM-DD.en.notes.md   show notes w/ source links (episode description)
  YYYY-MM-DD.zh.notes.md   show notes w/ source links (episode description)

The English episode is meant for Apple Podcasts / Spotify; the 中文 episode for
小宇宙 / 喜马拉雅 / 网易云. The .txt + .notes.md are the editable artifacts; the
.m4a is what you upload to each platform.

Usage:
  python3 scripts/build_podcast.py                 # both languages, with audio
  python3 scripts/build_podcast.py --lang en       # English only
  python3 scripts/build_podcast.py --no-audio      # scripts + notes only (no `say`)
  python3 scripts/build_podcast.py --news-only     # skip the research segment
  python3 scripts/build_podcast.py --voice-en Ava --voice-zh Tingting --rate 180

Runs anywhere for script/notes generation; audio requires macOS `say`.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITION = os.path.join(ROOT, "output", "edition.json")
OUTDIR = os.path.join(ROOT, "output", "podcast")
DEFAULT_SITE = "https://chengxue250.github.io/semi_study/"

# --- Voices ---------------------------------------------------------------
# `say -v '?'` lists installed voices. Tingting (zh_CN) and Samantha (en_US)
# ship with every macOS. Higher-quality "premium"/"enhanced" voices (e.g. Ava,
# Allison, Meijia) can be added free via System Settings > Accessibility >
# Spoken Content > System Voice > Manage Voices, then passed with --voice-*.
DEFAULT_VOICE = {"en": "Samantha", "zh": "Tingting"}

# --- Phrasebook (deterministic templating, no model needed) ---------------
PHRASES = {
    "en": {
        "weekday": ["Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday"],
        "intro": "Welcome to Semi News Daily for {date}. Here is your "
                 "chip-industry briefing.",
        "theme": "Today's theme: {theme}. {dek}",
        "section_first": "First up, {title}.",
        "section_next": "Next, {title}.",
        "section_turn": "Turning to {title}.",
        "section_also": "Also, in {title}.",
        "story_openers": ["From {src}:", "{src} reports:", "According to {src}:"],
        "story_featured": "Our top story, from {src}:",
        "research_intro": "Now to the research desk. {theme}. {dek}",
        "research_area": "In {title}.",
        "paper": "{title}. From {aff}, in {venue}. {summary}",
        "paper_no_aff": "{title}. In {venue}. {summary}",
        "outro": "That is your briefing for today. Every source is linked in "
                 "the show notes, with the full edition online. Thanks for "
                 "listening — back tomorrow with the next edition of Semi News "
                 "Daily.",
    },
    "zh": {
        "weekday": ["星期一", "星期二", "星期三", "星期四",
                    "星期五", "星期六", "星期日"],
        "intro": "欢迎收听《半导体每日新闻》，今天是{date}。以下是今天的芯片行业简报。",
        "theme": "今日主题：{theme}。{dek}",
        "section_first": "首先，来看{title}。",
        "section_next": "接下来，{title}。",
        "section_turn": "转向{title}。",
        "section_also": "另外，在{title}方面。",
        "story_openers": ["来自{src}的消息：", "据{src}报道：", "{src}消息："],
        "story_featured": "今天的头条，来自{src}：",
        "research_intro": "接下来是研究板块。{theme}。{dek}",
        "research_area": "{title}方面。",
        "paper": "{title}。来自{aff}，发表于{venue}。{summary}",
        "paper_no_aff": "{title}。发表于{venue}。{summary}",
        "outro": "今天的简报就到这里。所有信息来源的链接都在节目说明中，"
                 "完整内容请见网站。感谢收听，我们明天再见。",
    },
}

URL_RE = re.compile(r"https?://\S+")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def t(lang, key):
    return PHRASES[lang][key]


def fmt_date(date_str, lang):
    d = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    wd = PHRASES[lang]["weekday"][d.weekday()]
    if lang == "en":
        return f"{wd}, {d.strftime('%B')} {d.day}, {d.year}"
    return f"{d.year}年{d.month}月{d.day}日 {wd}"


def normalize_for_tts(text, lang):
    """Make a string read cleanly aloud. Conservative on purpose: strip things
    that sound wrong (URLs, markdown), smooth dashes — but never rewrite the
    actual content, so we can't introduce factual errors."""
    if not text:
        return ""
    text = MD_LINK_RE.sub(r"\1", text)      # [label](url) -> label
    text = URL_RE.sub("", text)             # bare URLs -> gone
    text = text.replace("&", " and " if lang == "en" else "和")
    # em/en dashes read as long pauses; commas are gentler
    text = text.replace(" — ", ", " if lang == "en" else "，")
    text = text.replace("—", ", " if lang == "en" else "，")
    text = text.replace("`", "")
    text = text.replace("*", "")
    # dash->comma can create doubled separators where the source had "——"
    text = re.sub(r"([，,。.！!？?；;：:])[，,]+", r"\1", text)
    text = re.sub(r"[，]{2,}", "，", text)
    text = re.sub(r"(,\s*){2,}", ", ", text)
    text = re.sub(r"\s+([，。！？；：])", r"\1", text)   # no space before CJK punct
    text = re.sub(r"\s+", " ", text).strip()
    return text


def L(node, lang):
    """Pull a language string from a {"en":..,"zh":..} node, falling back."""
    if isinstance(node, dict):
        return node.get(lang) or node.get("en") or node.get("zh") or ""
    return node or ""


def build_script(ed, lang, include_research=True):
    """Assemble the spoken script (plain text) for one language."""
    P = PHRASES[lang]
    lines = []
    lines.append(P["intro"].format(date=fmt_date(ed["date"], lang)))
    theme = normalize_for_tts(L(ed.get("theme"), lang), lang)
    dek = normalize_for_tts(L(ed.get("dek"), lang), lang)
    if theme:
        lines.append(P["theme"].format(theme=theme, dek=dek))

    section_intros = [P["section_first"], P["section_next"],
                      P["section_turn"], P["section_also"]]
    for i, sec in enumerate(ed.get("sections", [])):
        stories = sec.get("stories", [])
        if not stories:
            continue
        sec_title = normalize_for_tts(L(sec.get("title"), lang), lang)
        intro = section_intros[i] if i < len(section_intros) else P["section_next"]
        lines.append(intro.format(title=sec_title))
        osep = " " if lang == "en" else ""   # no space after a full-width colon
        period = ". " if lang == "en" else "。"
        for j, st in enumerate(stories):
            src = st.get("source", "")
            title = normalize_for_tts(L(st.get("title"), lang), lang)
            summary = normalize_for_tts(L(st.get("summary"), lang), lang)
            if st.get("featured"):
                opener = P["story_featured"].format(src=src)
            else:
                opener = P["story_openers"][j % len(P["story_openers"])].format(src=src)
            lines.append(f"{opener}{osep}{title}{period}{summary}")

    research = ed.get("research")
    if include_research and research and research.get("areas"):
        r_theme = normalize_for_tts(L(research.get("theme"), lang), lang)
        r_dek = normalize_for_tts(L(research.get("dek"), lang), lang)
        lines.append(P["research_intro"].format(theme=r_theme, dek=r_dek))
        for area in research["areas"]:
            papers = area.get("papers", [])
            if not papers:
                continue
            a_title = normalize_for_tts(L(area.get("title"), lang), lang)
            lines.append(P["research_area"].format(title=a_title))
            for pap in papers:
                title = normalize_for_tts(L(pap.get("title"), lang), lang)
                summary = normalize_for_tts(L(pap.get("summary"), lang), lang)
                aff = normalize_for_tts(pap.get("affiliation", ""), lang)
                venue = normalize_for_tts(pap.get("venue", ""), lang)
                if aff:
                    lines.append(P["paper"].format(
                        title=title, aff=aff, venue=venue, summary=summary))
                else:
                    lines.append(P["paper_no_aff"].format(
                        title=title, venue=venue, summary=summary))

    lines.append(P["outro"])
    return "\n\n".join(lines) + "\n"


def build_notes(ed, lang, site_url, include_research=True):
    """Markdown show notes with source links — paste into the episode description."""
    out = []
    title = L(ed.get("theme"), lang)
    dek = L(ed.get("dek"), lang)
    head = "Semi News Daily" if lang == "en" else "半导体每日新闻"
    out.append(f"# {head} — {fmt_date(ed['date'], lang)}")
    out.append(f"**{title}**")
    if dek:
        out.append(dek)
    out.append("")
    for sec in ed.get("sections", []):
        stories = sec.get("stories", [])
        if not stories:
            continue
        out.append(f"## {L(sec.get('title'), lang)}")
        for st in stories:
            star = "⭐ " if st.get("featured") else ""
            line = f"- {star}**{L(st.get('title'), lang)}** — {st.get('source','')}"
            if st.get("url"):
                line += f" · [{'link' if lang=='en' else '原文'}]({st['url']})"
            out.append(line)
            out.append(f"  - {L(st.get('summary'), lang)}")
        out.append("")
    research = ed.get("research")
    if include_research and research and research.get("areas"):
        rhead = "Research" if lang == "en" else "研究板块"
        out.append(f"## {rhead} — {L(research.get('theme'), lang)}")
        for area in research["areas"]:
            papers = area.get("papers", [])
            if not papers:
                continue
            out.append(f"### {L(area.get('title'), lang)}")
            for pap in papers:
                meta = " · ".join(x for x in [pap.get("affiliation", ""),
                                              pap.get("venue", "")] if x)
                line = f"- **{L(pap.get('title'), lang)}**"
                if meta:
                    line += f" ({meta})"
                if pap.get("venue_url"):
                    line += f" · [{'paper' if lang=='en' else '论文'}]({pap['venue_url']})"
                out.append(line)
                out.append(f"  - {L(pap.get('summary'), lang)}")
        out.append("")
    tail = ("Full edition: " if lang == "en" else "完整内容：") + site_url
    out.append(tail)
    out.append("")
    out.append("_Generated by the podcast-daily skill (offline TTS, no paid API)._"
               if lang == "en" else
               "_由 podcast-daily 技能生成（本地离线合成，无需付费接口）。_")
    return "\n".join(out) + "\n"


def estimate_minutes(script, lang):
    # Rates calibrated against actual `say` output at the default speaking rate
    # (Samantha ~130 wpm, Tingting ~165 zh-chars/min). Pass --rate to speed up.
    if lang == "en":
        words = len(script.split())
        return words / 130.0
    chars = len(re.findall(r"[一-鿿]", script))
    return chars / 165.0


def synthesize(script_path, out_path, voice, rate):
    """Render script to .m4a using macOS `say`. Returns True on success.

    Force AAC-LC (`--data-format=aac`) instead of `say`'s default near-lossless
    encoding: identical quality for speech, ~3-4x smaller files for upload."""
    cmd = ["say", "-v", voice, "--file-format=m4af", "--data-format=aac",
           "-o", out_path, "-f", script_path]
    if rate:
        cmd[1:1] = ["-r", str(rate)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(f"  ! say failed for {out_path}: {proc.stderr.strip()}\n")
        return False
    return True


def synthesize_clone(text_path, out_path, ref, lang, clone_python, device, speed):
    """Delegate to scripts/clone_tts.py running in the TTS venv (which has the
    model). Kept in a subprocess so build_podcast.py itself needs no heavy deps.
    Output streams through so the user sees per-chunk progress on long runs."""
    if not os.path.exists(clone_python):
        sys.stderr.write(
            f"  ! clone interpreter not found: {clone_python}\n"
            "    set up once with:\n"
            "      python3 -m venv .venv-tts\n"
            "      .venv-tts/bin/pip install coqui-tts\n")
        return False
    script = os.path.join(ROOT, "scripts", "clone_tts.py")
    cmd = [clone_python, script, "--text", text_path, "--ref", ref,
           "--lang", lang, "--out", out_path, "--device", device]
    if speed and speed != 1.0:
        cmd += ["--speed", str(speed)]
    return subprocess.run(cmd).returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", default=EDITION, help="path to edition.json")
    ap.add_argument("--outdir", default=OUTDIR, help="output directory")
    ap.add_argument("--lang", choices=["en", "zh", "both"], default="both")
    ap.add_argument("--no-audio", action="store_true",
                    help="write scripts + notes only; skip `say` synthesis")
    ap.add_argument("--news-only", action="store_true",
                    help="exclude the research segment from the episode")
    ap.add_argument("--voice-en", default=DEFAULT_VOICE["en"])
    ap.add_argument("--voice-zh", default=DEFAULT_VOICE["zh"])
    ap.add_argument("--rate", type=int, default=None,
                    help="speaking rate in words/min (passed to `say -r`)")
    ap.add_argument("--engine", choices=["say", "clone"], default="say",
                    help="say = macOS built-in voices (default); "
                         "clone = your own voice via local XTTS (needs --ref-*)")
    ap.add_argument("--ref-en", default=None,
                    help="reference recording of YOUR voice for the EN episode")
    ap.add_argument("--ref-zh", default=None,
                    help="reference recording of YOUR voice for the 中文 episode")
    ap.add_argument("--clone-python",
                    default=os.path.join(ROOT, ".venv-tts", "bin", "python"),
                    help="python interpreter that has coqui-tts installed")
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps"],
                    help="clone synthesis device (mps faster, experimental)")
    ap.add_argument("--clone-speed", type=float, default=1.0,
                    help="speaking-rate multiplier for the cloned voice")
    ap.add_argument("--site-url", default=DEFAULT_SITE)
    args = ap.parse_args()

    if not os.path.exists(args.edition):
        sys.exit(f"edition not found: {args.edition} (run the news build first)")
    with open(args.edition, encoding="utf-8") as f:
        ed = json.load(f)
    date = ed.get("date")
    if not date:
        sys.exit("edition.json has no 'date'")

    os.makedirs(args.outdir, exist_ok=True)
    langs = ["en", "zh"] if args.lang == "both" else [args.lang]
    include_research = not args.news_only
    voices = {"en": args.voice_en, "zh": args.voice_zh}
    refs = {"en": args.ref_en, "zh": args.ref_zh}

    have_say = shutil.which("say") is not None
    if not args.no_audio and not have_say and args.engine == "say":
        sys.stderr.write("note: `say` not found (non-macOS?). Writing scripts + "
                         "notes only; re-run on macOS for audio.\n")

    print(f"Edition {date} — building podcast ({', '.join(langs)})")
    for lang in langs:
        script = build_script(ed, lang, include_research)
        notes = build_notes(ed, lang, args.site_url, include_research)
        base = os.path.join(args.outdir, f"{date}.{lang}")

        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(script)
        with open(base + ".notes.md", "w", encoding="utf-8") as f:
            f.write(notes)
        mins = estimate_minutes(script, lang)
        print(f"  [{lang}] script {base}.txt  (~{mins:.1f} min)")
        print(f"  [{lang}] notes  {base}.notes.md")

        if not args.no_audio:
            done = False
            if args.engine == "clone":
                ref = refs.get(lang)
                if ref and os.path.exists(ref):
                    print(f"  [{lang}] cloning your voice (this is slower than say)…")
                    done = synthesize_clone(base + ".txt", base + ".m4a", ref, lang,
                                            args.clone_python, args.device,
                                            args.clone_speed)
                    if done:
                        size = os.path.getsize(base + ".m4a") / 1_000_000
                        print(f"  [{lang}] audio  {base}.m4a  ({size:.1f} MB, cloned voice)")
                    else:
                        print(f"  [{lang}] clone failed — falling back to `say`")
                else:
                    print(f"  [{lang}] no reference clip (pass --ref-{lang} PATH) — "
                          f"using `say`")
            if not done and have_say:
                ok = synthesize(base + ".txt", base + ".m4a", voices[lang], args.rate)
                if ok:
                    size = os.path.getsize(base + ".m4a") / 1_000_000
                    print(f"  [{lang}] audio  {base}.m4a  ({size:.1f} MB, voice={voices[lang]})")

    print("Done. Upload the .m4a files to your podcast platforms; paste the "
          ".notes.md as the episode description.")


if __name__ == "__main__":
    main()
