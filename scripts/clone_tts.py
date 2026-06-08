#!/usr/bin/env python3
"""Offline voice cloning for the daily podcast — your own voice, no API, no fees.

Reads a podcast script (the .txt produced by build_podcast.py) and re-speaks it
in YOUR voice, cloned zero-shot from a short reference recording, using Coqui
XTTS-v2 running locally. Output is .wav, then converted to .m4a with macOS's
built-in `afconvert` (so no ffmpeg and no cloud service are involved).

  python3 scripts/clone_tts.py \
    --text output/podcast/2026-06-07.en.txt \
    --ref  assets/voice/myvoice.en.wav \
    --lang en \
    --out  output/podcast/2026-06-07.en.m4a

Run it with the project's TTS venv interpreter (it has the model installed):
  .venv-tts/bin/python scripts/clone_tts.py ...
build_podcast.py --engine clone does this for you.

LICENSE NOTE: XTTS-v2 ships under the Coqui Public Model License (CPML), which
is NON-COMMERCIAL. Fine for a personal podcast. If you monetize, switch to an
MIT-licensed model — see references/voice-clone-guide.md.

Cloning uses only YOUR OWN recorded voice (consent assumed). Do not clone
someone else's voice without their permission.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import wave

SR = 24000  # XTTS-v2 output sample rate
LANG_MAP = {"en": "en", "zh": "zh-cn"}
# Per-language soft chunk size (chars). XTTS has a low char limit for zh-cn, so
# keep Chinese chunks short; English can be longer.
CHUNK_MAX = {"en": 220, "zh": 80}
DEFAULT_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


def split_sentences(text, lang):
    text = text.strip()
    if not text:
        return []
    if lang == "zh":
        # keep the terminal punctuation attached to each sentence
        parts = re.split(r"(?<=[。！？!?])", text)
    else:
        parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p and p.strip()]


def chunkify(text, lang):
    """Group sentences into model-sized chunks, splitting over-long sentences."""
    limit = CHUNK_MAX[lang]
    chunks, cur = [], ""
    for sent in split_sentences(text, lang):
        # a single sentence longer than the limit: hard-split on commas/spaces
        while len(sent) > limit:
            cut = sent.rfind("，", 0, limit)
            if cut < 0:
                cut = sent.rfind(",", 0, limit)
            if cut < 0:
                cut = sent.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            piece, sent = sent[:cut + 1].strip(), sent[cut + 1:].strip()
            if piece:
                chunks.append(piece)
        if not sent:
            continue
        if len(cur) + len(sent) + 1 <= limit:
            cur = (cur + " " + sent).strip() if cur else sent
        else:
            if cur:
                chunks.append(cur)
            cur = sent
    if cur:
        chunks.append(cur)
    return chunks


def ensure_wav_ref(ref_path):
    """XTTS wants a wav reference. Convert m4a/mp3/aiff via afconvert if needed.
    Returns (wav_path, tempfile_to_cleanup_or_None)."""
    if not os.path.exists(ref_path):
        sys.exit(f"reference audio not found: {ref_path}")
    if ref_path.lower().endswith(".wav"):
        return ref_path, None
    if not shutil_which("afconvert"):
        sys.exit("reference is not .wav and `afconvert` is unavailable to convert it.")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    subprocess.run(["afconvert", ref_path, "-f", "WAVE", "-d", "LEI16", tmp.name],
                   check=True)
    return tmp.name, tmp.name


def shutil_which(name):
    from shutil import which
    return which(name)


def write_wav(path, audio_float, sr=SR):
    import numpy as np
    audio = np.clip(np.asarray(audio_float, dtype="float32"), -1.0, 1.0)
    pcm = (audio * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def to_m4a(wav_path, m4a_path):
    if not shutil_which("afconvert"):
        # No afconvert (non-macOS): leave the wav next to the requested path.
        alt = os.path.splitext(m4a_path)[0] + ".wav"
        if os.path.abspath(alt) != os.path.abspath(wav_path):
            import shutil
            shutil.copyfile(wav_path, alt)
        sys.stderr.write(f"  note: afconvert missing; wrote {alt} instead of m4a\n")
        return alt
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", wav_path, m4a_path],
                   check=True)
    return m4a_path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", required=True, help="podcast script .txt")
    ap.add_argument("--ref", required=True, help="your reference voice clip (wav/m4a)")
    ap.add_argument("--lang", required=True, choices=["en", "zh"])
    ap.add_argument("--out", required=True, help="output .m4a path")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps"],
                    help="cpu is reliable; mps is faster but experimental for XTTS")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()

    if not os.path.exists(args.text):
        sys.exit(f"script not found: {args.text}")
    with open(args.text, encoding="utf-8") as f:
        text = f.read()
    chunks = chunkify(text, args.lang)
    if not chunks:
        sys.exit("nothing to speak (empty script)")

    # Accept the model license non-interactively (personal use).
    os.environ.setdefault("COQUI_TOS_AGREED", "1")

    try:
        import numpy as np
        from TTS.api import TTS
    except Exception as e:  # noqa: BLE001
        sys.exit(f"TTS not importable — run with the venv python "
                 f"(.venv-tts/bin/python). Underlying error: {e}")

    ref_wav, ref_tmp = ensure_wav_ref(args.ref)
    lang_code = LANG_MAP[args.lang]

    sys.stderr.write(f"Loading XTTS-v2 on {args.device} (first run downloads ~1.8 GB)…\n")
    tts = TTS(args.model)
    try:
        tts.to(args.device)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"  {args.device} unavailable ({e}); falling back to cpu\n")
        tts.to("cpu")

    sil = np.zeros(int(0.25 * SR), dtype="float32")
    pieces = []
    n = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        sys.stderr.write(f"  [{args.lang}] chunk {i}/{n} ({len(chunk)} chars)…\n")
        sys.stderr.flush()
        wav = tts.tts(text=chunk, speaker_wav=ref_wav,
                      language=lang_code, split_sentences=False, speed=args.speed)
        pieces.append(np.asarray(wav, dtype="float32"))
        pieces.append(sil)
    audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype="float32")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_wav.close()
    try:
        write_wav(tmp_wav.name, audio)
        final = to_m4a(tmp_wav.name, args.out)
    finally:
        for p in (tmp_wav.name, ref_tmp):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    dur = len(audio) / SR / 60.0
    size = os.path.getsize(final) / 1_000_000 if os.path.exists(final) else 0
    sys.stderr.write(f"Done: {final}  (~{dur:.1f} min, {size:.1f} MB, your voice)\n")
    print(final)


if __name__ == "__main__":
    main()
