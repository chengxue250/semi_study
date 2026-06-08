# Use your own voice (local, free clone)

The default podcast uses macOS `say`, which is clear but robotic. This guide
switches the audio to **your own voice**, cloned locally with Coqui XTTS-v2 — no
cloud service, no API key, no per-use fees. It runs on your Mac (Apple Silicon
recommended).

> **License.** XTTS-v2 is released under the **Coqui Public Model License
> (CPML)** — it is **non-commercial**. Fine for a personal podcast. If you
> monetize, switch to an MIT-licensed model (see "Commercial use" at the end).
>
> **Consent.** Clone only *your own* voice. Don't clone anyone else's without
> their permission.

## One-time setup (~10 min, ~3 GB)

```bash
# From the project root. Isolated venv so your system Python stays clean.
python3 -m venv .venv-tts
.venv-tts/bin/pip install --upgrade pip wheel
.venv-tts/bin/pip install -r references/voice-clone-requirements.txt
```

The version pins in that file are deliberate — they avoid a dependency clash
(coqui pulls a too-new `transformers`) and a heavier path (newer `torch` would
require system ffmpeg). Both are documented in the requirements file itself.

The XTTS-v2 model weights (~1.8 GB) download automatically the first time you
synthesize, and are cached under `~/Library/Application Support/tts/` after that.

Both `.venv-tts/` and your recordings are git-ignored — they never get committed.

## Record your reference voice (the important part)

Cloning quality is mostly decided by your reference clip. You need **one clip per
language** (English and 中文), because a same-language reference sounds the most
natural. Aim for:

- **30–60 seconds** of you speaking naturally (longer than ~60 s doesn't help).
- A **quiet room**, no music or background voices, consistent distance from the mic.
- Your **normal podcast delivery** — the clone copies your pace and tone, not just timbre.
- Save as **.wav** if you can (the script also accepts .m4a/.mp3 and converts them).

Easiest capture: **Voice Memos** (built in) or **QuickTime → File → New Audio
Recording**. Read the matching script below.

Save the files here (the folder is git-ignored):

```
assets/voice/myvoice.en.wav
assets/voice/myvoice.zh.wav
```

### English reference script (read aloud, ~45 s)

> Welcome to Semi News Daily. I'm your host, and this is the chip-industry
> briefing where we cut through the noise and focus on what actually moved:
> the foundries racing to the next node, the memory makers chasing the AI
> bottleneck, and the policy shifts that quietly redraw the supply chain.
> Some days the story is a record earnings call; other days it's a single
> export rule that changes everyone's roadmap. Whatever it is, I'll give you
> the news first and the context right after — no hype, no filler. Let's get
> into today's edition.

### 中文 reference script（朗读约 45 秒）

> 欢迎收听《半导体每日新闻》。我是主播，这里是聚焦芯片行业的每日简报。
> 我们不堆砌噪音，只关注真正发生变化的事情：奔向下一个制程节点的晶圆厂、
> 追赶人工智能瓶颈的存储厂商，以及悄然重塑供应链的政策变动。
> 有时候，焦点是一份创纪录的财报；有时候，则是一条出口管制规则，
> 改变了所有人的路线图。无论是什么，我都会先讲清楚发生了什么，
> 再补上背后的来龙去脉——不夸大，不注水。让我们开始今天这一期。

## Generate the podcast in your voice

```bash
python3 scripts/build_podcast.py --engine clone \
  --ref-en assets/voice/myvoice.en.wav \
  --ref-zh assets/voice/myvoice.zh.wav
```

- Each language is read in your cloned voice and written to
  `output/podcast/YYYY-MM-DD.{en,zh}.m4a` (the `.txt`/`.notes.md` are unchanged).
- If a reference clip is missing for a language, that language **falls back to
  `say`** with a notice — it never fails the whole run.
- Synthesis is **much slower than `say`** (it's a neural model on CPU): expect a
  few seconds per sentence, so a ~15-minute episode can take 15–40 minutes. This
  is fine for an unattended daily job; for a quick check, add `--news-only` or
  `--lang en`.

### Speed/quality knobs

- `--device mps` — try Apple-GPU acceleration (faster; experimental for XTTS,
  auto-falls back to CPU if an op is unsupported).
- `--clone-speed 1.1` — talk a little faster (multiplier).
- Re-record a cleaner/longer reference if a particular sound is off — the
  reference clip matters more than any flag.

## Tips for a natural result

- Match the reference **style** to the show: read your reference the way you'd
  host, not like a voicemail greeting.
- If numbers or tickers ("HBM4E", "A14", "$6.5B") sound wrong, fix them in the
  `output/podcast/*.txt` before synthesizing — same as the `say` path.
- Keep one good reference per language and reuse it every day; you don't
  re-record daily.

## Commercial use (swap to an MIT-licensed model)

If you'll monetize the podcast, replace XTTS-v2 with a permissively-licensed
cloning model and point `clone_tts.py` at it:

- **OpenVoice v2** (MIT) + MeloTTS — tone-color cloning, EN + 中文.
- **Chatterbox Multilingual** (MIT, Resemble AI) — zero-shot cloning, EN + 中文.

The pipeline (chunking → synth → `afconvert` to m4a, and the `build_podcast.py
--engine clone` integration) stays the same; only the model-loading/synthesis
lines inside `scripts/clone_tts.py` change. Ask and I'll wire whichever you pick.
