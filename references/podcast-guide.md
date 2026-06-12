# Podcast editorial & normalization guide

Companion to the `podcast-daily` skill and `scripts/build_podcast.py`. This covers
*why* the script reads the way it does, so edits stay consistent.

## What goes in the audio vs. the show notes

| Content | Audio (`.m4a` / `.txt`) | Show notes (`.notes.md`) |
|---------|:----------------------:|:------------------------:|
| Theme + dek | ✅ | ✅ |
| Story title + summary | ✅ | ✅ |
| Source name | ✅ ("From SemiAnalysis:") | ✅ |
| **Source URL** | ❌ (never read aloud) | ✅ (clickable link) |
| Research paper title + summary | ✅ | ✅ |
| Affiliation + venue | ✅ | ✅ |
| **Paper / arXiv URL** | ❌ | ✅ |

Rule of thumb: **URLs are for the eye, not the ear.** Reading a Google-News redirect
or `arxiv.org/abs/2605.12345` aloud is useless, so the synthesizer strips every URL
and the listener is pointed to the show notes instead. The notes carry every link.

## Voice & structure (deterministic, no LLM)

The episode follows a fixed arc so it's recognizable day to day:

1. **Cold open / intro** — "Welcome to Semi News Daily for {weekday, date}."
2. **Theme** — the masthead headline + dek, same wording as the site.
3. **News, section by section** — connective intros rotate so it isn't monotone
   (`First up` → `Next` → `Turning to` → `Also`). The first `featured` story in a
   section gets a "top story" lead-in.
4. **Research desk** — the research theme + dek, then each area's papers
   ("{title}. From {affiliation}, in {venue}. {summary}").
5. **Outro** — points to the show notes for links, signs off.

All phrasing lives in the `PHRASES` dict in `build_podcast.py`. To change the show's
spoken personality, edit those strings — do **not** reach for an LLM; keeping it
templated is what makes the podcast free to produce.

The spoken content (titles, summaries) is copied verbatim from `edition.json`. That
means the podcast inherits the news run's editorial bar and its
**copy-or-verify-never-invent** discipline for facts and numbers — the podcast adds no
new claims of its own.

## Text normalization (`normalize_for_tts`)

The goal is *read cleanly without changing meaning*. The function is deliberately
conservative — it removes things that sound wrong but never rewrites the substance,
so it can't introduce a factual error:

- **Strip URLs** (`https?://…`) and unwrap markdown links `[label](url)` → `label`.
- **`&`** → "and" / "和".
- **Em/en dashes** (` — `, `—`, Chinese `——`) → a comma, which reads as a natural
  pause instead of a long silence.
- **Collapse doubled punctuation** the dash→comma step can create (`，，` → `，`).
- **No space before CJW punctuation**, and no stray ASCII period inside Chinese
  (story lines use `。` in 中文, `. ` in English).
- Drop leftover markdown (`` ` ``, `*`) and collapse whitespace.

Numbers, units, and symbols (`$6.5B`, `2nm`, `HBM4E`) are left **as written** — `say`
pronounces them acceptably, and rewriting them risks corrupting a figure. If a
specific term is consistently mispronounced, fix it in the `.txt` before re-rendering
(step 3 of the skill) rather than adding a global substitution that might misfire
elsewhere.

## Duration

Rough estimate printed by the script: English at ~165 spoken words/min, 中文 at ~240
characters/min. A typical 12-story + 8-paper edition lands around 13–15 minutes per
language. Use `--news-only` (≈ 8–10 min) for a tighter cut, or `--rate` to speed up
delivery.

## Picking better voices (still free)

The bundled `Samantha` / `Tingting` are clear but plainly synthetic. Apple ships
higher-quality on-device neural voices for free; they're a one-time download:

**System Settings → Accessibility → Spoken Content → System Voice → Manage Voices**,
then tick e.g. *Ava (Enhanced)* (English) or *Meijia* (中文). Pass them with
`--voice-en` / `--voice-zh`. Still offline, still no API, still no per-use cost — just
a nicer timbre.
