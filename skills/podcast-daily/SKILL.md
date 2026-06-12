---
name: podcast-daily
description: Turn the day's semiconductor digest (output/edition.json) into a bilingual daily podcast — an English episode for Apple Podcasts / Spotify and a 中文 episode for 小宇宙 / 喜马拉雅 / 网易云 — plus a spoken-script .txt and a show-notes .md (with source links) for each. Audio is synthesized offline with macOS's built-in `say` command, and the spoken script is assembled deterministically from the already-bilingual edition.json, so there is NO third-party/cloud TTS API and NO extra LLM tokens. Use this skill whenever the user asks to make, generate, refresh, or schedule a podcast / audio version / 播客 / 音频 of the semiconductor news, or says things like "turn today's edition into a podcast," "make the audio version," "生成今天的播客," or wants the EN and 中文 episodes for different platforms. Run it after the news edition (semi-news-daily) has produced output/edition.json.
---

# Daily Semiconductor Podcast (bilingual, zero-cost)

Produces, from a single `output/edition.json`, **four files per language** under
`output/podcast/`:

| File | What it is | Where it goes |
|------|------------|---------------|
| `YYYY-MM-DD.en.m4a` | English audio (AAC) | Apple Podcasts, Spotify, Overcast |
| `YYYY-MM-DD.zh.m4a` | 中文 audio (AAC) | 小宇宙, 喜马拉雅, 网易云音乐 |
| `YYYY-MM-DD.{en,zh}.txt` | the spoken script | edit before re-rendering if you want |
| `YYYY-MM-DD.{en,zh}.notes.md` | show notes w/ every source link | paste as the episode description |

## Why this costs nothing extra

Two deliberate design choices keep the running cost at **$0 and 0 tokens**:

1. **The script is templated, not generated.** `edition.json` already contains every
   title and summary in both English and 中文 (the news run wrote them). So
   `scripts/build_podcast.py` *assembles* the spoken script with fixed connective
   phrasing ("First up…", "Turning to…", "首先…", "接下来…") — it never calls an LLM.
   No tokens are spent turning the edition into a script.
2. **TTS is local.** Audio is rendered by macOS's built-in `say` command, which is
   offline and free. No ElevenLabs / OpenAI / Google / Azure TTS, no API key, no
   per-character billing. Output is AAC-LC `.m4a` (`--data-format=aac`), which every
   podcast platform accepts — and no `ffmpeg` is required.

The only requirement beyond the news run is that audio generation happens on **macOS**
(for `say`). On a non-Mac box the script still writes the `.txt` + `.notes.md`; re-run
`--no-audio` is implied automatically and you render the audio later on a Mac.

## Workflow

### 1. Make sure today's edition exists

This skill reads `output/edition.json`. If it's missing or stale, run the
`semi-news-daily` skill first (it produces `edition.json` + the HTML pages). The
podcast uses the **same** curated stories and research, so the episode always matches
the published site.

### 2. Generate the podcast

```bash
python3 scripts/build_podcast.py
```

That writes both languages (script + notes + audio) to `output/podcast/`. The command
prints each file path and an estimated runtime (~13–15 min for a typical 12-story +
8-paper edition).

Common variants:

```bash
python3 scripts/build_podcast.py --lang en        # English episode only
python3 scripts/build_podcast.py --lang zh        # 中文 episode only
python3 scripts/build_podcast.py --no-audio       # scripts + notes only, skip `say`
python3 scripts/build_podcast.py --news-only      # drop the research segment
python3 scripts/build_podcast.py --rate 190       # faster speaking pace (words/min)
python3 scripts/build_podcast.py --voice-en Ava --voice-zh Meijia   # other voices
```

### 3. (Optional) Tweak the script and re-render just the audio

The `.txt` is the source of truth for the audio. If you want to fix a pronunciation
or trim a story, edit `output/podcast/YYYY-MM-DD.en.txt`, then re-render only that one
file without rebuilding everything:

```bash
say -v Samantha --file-format=m4af --data-format=aac \
  -o output/podcast/2026-06-01.en.m4a \
  -f output/podcast/2026-06-01.en.txt
```

### 4. Publish to each platform

- **English** (`.en.m4a` + `.en.notes.md`) → Apple Podcasts Connect / Spotify for
  Podcasters / Overcast. Paste the notes markdown as the episode description.
- **中文** (`.zh.m4a` + `.zh.notes.md`) → 小宇宙 / 喜马拉雅 / 网易云音乐 创作者后台.

The `.m4a` files are what you upload; the `.notes.md` gives you a ready-made,
link-rich episode description. Audio is **not** committed to git (it's in
`.gitignore`) — these platforms host the audio for you, so there's no need to keep
multi-megabyte files in the repo. The `.txt` and `.notes.md` are small and are kept.

## Choosing voices

List installed voices with `say -v '?'`. Defaults are the always-present
**Samantha** (en_US) and **Tingting** (zh_CN). For more natural delivery, install a
free *premium / enhanced* voice once via **System Settings → Accessibility → Spoken
Content → System Voice → Manage Voices** (e.g. *Ava (Enhanced)* for English,
*Meijia* for 中文), then pass `--voice-en` / `--voice-zh`. There's no cost — these are
on-device neural voices Apple ships for free; they're just a large one-time download.

See `references/podcast-guide.md` for the editorial voice, what gets read aloud vs.
left to the show notes, and the text-normalization rules.

## Honest tradeoff

macOS `say` is **clear and correct but recognizably synthetic** — fine for a daily
briefing, not indistinguishable from a human host. That is the price of zero cost and
zero tokens. If you ever decide higher-fidelity narration is worth a bill, the
`.txt` scripts this skill produces are exactly the input a paid TTS service wants —
you can switch the synthesis step without changing anything upstream.

## Scheduling

To make the podcast every day right after the news, append this skill's step to the
existing daily automation (see the main project's `references/automation.md`). The
one line to add **after** the news build + publish is:

```bash
python3 scripts/build_podcast.py
```

It is idempotent — re-running on the same day overwrites that day's files cleanly.

## Files

```
scripts/build_podcast.py        the generator (stdlib only; no pip, no network)
references/podcast-guide.md      editorial + normalization notes
output/podcast/                  generated episodes (.m4a gitignored; .txt/.notes.md kept)
```
