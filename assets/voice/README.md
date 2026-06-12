# Your reference voice clips go here

Drop a short recording of **your own voice** in this folder to make the podcast
speak in your voice (see `references/voice-clone-guide.md` for the full setup):

```
assets/voice/myvoice.en.wav    # ~30–60 s, English, read the script in the guide
assets/voice/myvoice.zh.wav    # ~30–60 s, 中文, read the 中文 script in the guide
```

Then build the podcast in your voice:

```bash
python3 scripts/build_podcast.py --engine clone \
  --ref-en assets/voice/myvoice.en.wav \
  --ref-zh assets/voice/myvoice.zh.wav
```

**Privacy:** audio files in this folder are git-ignored on purpose — your voice
is personal data and never gets committed or pushed. Only this README is tracked.
