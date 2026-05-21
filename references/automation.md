# Scheduling daily runs + getting it to your phone

The skill itself does not install any scheduler or push anything — that's a
system-level choice. This file documents the recipes.

The daily pipeline has up to four steps:

1. **Build** — agent runs the skill: `python3 scripts/fetch_rss.py …`,
   `python3 scripts/build_page.py`.
2. **Publish** (optional, but needed if you want the phone-link form of
   notifications) — push `output/` to GitHub Pages or similar.
3. **Notify** (optional) — `python3 scripts/notify.py` sends a push to the
   user's phone with the theme headline + a link to the public URL.
4. **Schedule** — the OS-level cron/launchd/Actions trigger that fires the
   whole chain once a day.

You can pick any subset. The simplest is just step 1 (build, view locally).

---

## Pushing to your phone (ntfy.sh + GitHub Pages)

This is the recommended setup. Free, no signup, works on iOS/Android, and the
public Pages URL doubles as a permalink you can share.

### One-time setup

**A. ntfy.sh topic (your "phone destination"):**

1. Pick a long, unguessable topic name. The ntfy security model is "secret
   URL" — anyone who knows the topic can read/write to it, so it has to be
   unguessable. Examples that work: `semi-news-hcxj-x4k29q-7m8`, `news-${UUID}`.
   Generate one with:
   ```bash
   uuidgen | tr 'A-Z' 'a-z' | sed 's/^/semi-news-/'
   ```
2. Install the ntfy app on your phone (iOS App Store / Google Play /
   F-Droid). Or just bookmark https://ntfy.sh in your phone browser as a PWA.
3. In the app, tap "Subscribe to topic" and paste your topic name. Done.

**B. GitHub Pages (your "public URL"):**

1. Create a GitHub repo (public is fine; private + Pages requires a paid plan).
   Push the entire `semi_news/` folder to it.
2. In repo Settings → Pages, set:
   - **Source**: GitHub Actions (recommended) or Deploy from a branch.
   - If branch-based, point Pages at the `main` branch, `/output` folder. The
     `actions/deploy-pages` workflow below uploads `output/` directly, so you
     don't need a separate branch.
3. After the first deploy, your URL is `https://<user>.github.io/<repo>/`.

**C. Local config:**

```bash
cp notify.yaml.example notify.yaml
$EDITOR notify.yaml      # paste your ntfy topic + Pages URL
```

`notify.yaml` is in `.gitignore` so the topic name (which is your secret)
does not leak into the repo.

**D. Test:**

```bash
python3 scripts/notify.py --dry-run     # see what would be sent
python3 scripts/notify.py               # actually send — should ping your phone
```

If the dry-run looks right and you don't see the phone notification, check
that you're subscribed to the same topic in the ntfy app and that
`notify.yaml` has `enabled: true`.

### Per-day flow

After this is set up, every run ends with `python3 scripts/notify.py` and your
phone gets:

- **Title**: the daily theme headline (EN).
- **Body**: the dek + a `[date] N stories · M papers` counter.
- **Tap**: opens the public URL of `index.html`.

---

## macOS — launchd

Recommended on macOS because cron quietly stopped being the supported path.
Save as `~/Library/LaunchAgents/news.seminews.daily.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>news.seminews.daily</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>/Users/hcxj/Documents/CC/semi_news/scripts/run_daily.sh</string>
  </array>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>7</integer>
    <key>Minute</key><integer>30</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>/Users/hcxj/Documents/CC/semi_news/output/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/hcxj/Documents/CC/semi_news/output/launchd.err.log</string>

  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

You'll also want `scripts/run_daily.sh` — a wrapper that invokes the agent.
Below is a template for Claude Code; substitute your CLI of choice:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /Users/hcxj/Documents/CC/semi_news

# Build (requires an agent CLI available in PATH)
claude -p "Build today's semiconductor news edition using the SKILL.md in this directory. Run all scripts to completion. Then exit." \
       --permission-mode acceptEdits --max-turns 60

# Notify (no-ops if notify.yaml is absent)
python3 scripts/notify.py

# Commit & push so GitHub Pages picks it up (optional — comment out if local-only)
git add output/
git commit -m "edition $(date -u +%F)" || echo "no changes"
git push origin main
```

`chmod +x scripts/run_daily.sh`, then load the plist:

```bash
launchctl load -w ~/Library/LaunchAgents/news.seminews.daily.plist
```

Unload to disable:

```bash
launchctl unload -w ~/Library/LaunchAgents/news.seminews.daily.plist
```

---

## Linux / macOS — crontab

`crontab -e` and add:

```cron
30 7 * * *  /Users/hcxj/Documents/CC/semi_news/scripts/run_daily.sh
```

Notes:
- cron has a minimal `PATH`. Either set `PATH=` at the top of the crontab, or
  make `run_daily.sh` set its own (`export PATH=/usr/local/bin:/usr/bin:/bin`).
- macOS Catalina+ requires giving `cron` Full Disk Access in System Settings,
  or use launchd instead.

---

## GitHub Actions — end-to-end (build + Pages + ntfy push)

A turnkey one-file workflow lives at `.github/workflows/daily.yml`. The
high-level flow:

1. Cron triggers at 11:30 UTC (07:30 ET / 19:30 SGT).
2. Job checks out the repo, installs the agent CLI.
3. Agent runs the skill end-to-end.
4. The committed `output/` is uploaded as a Pages artifact and deployed.
5. After deploy, a final `curl` posts to ntfy.sh with the theme headline +
   the now-live Pages URL.

Required GitHub secrets:
- `ANTHROPIC_API_KEY` — for the Claude Code CLI. If you use a different
  agent, swap in the appropriate key (`OPENAI_API_KEY`, etc.).
- `NTFY_TOPIC` — your ntfy topic name.
- `NTFY_TOKEN` — only if your ntfy server uses auth (most public uses don't).

See `.github/workflows/daily.yml` for the exact YAML.

---

## Anything else (systemd, Windows Task Scheduler, etc.)

The unit of work is always `bash scripts/run_daily.sh` from the project
directory. Wire whatever scheduler you have at that command.

---

## Verifying the schedule

After the first run:

1. `output/index.html` has today's date in its `<meta name="edition-date">`.
2. `output/archive.html` lists today's edition at the top.
3. `output/run.log` (or launchd/Actions log) has no Python tracebacks.
4. If push is configured, your phone receives a notification within a few
   seconds of `notify.py` completing.

If you set up Pages, you can also check:
- `https://<user>.github.io/<repo>/` shows today's edition.
- The "Pages" tab in repo Settings shows the last successful deploy time.

If something silently doesn't fire:
- ntfy: run `python3 scripts/notify.py --dry-run`; if the request looks right
  but the phone is silent, re-subscribe to the topic in the ntfy app.
- Pages: check the Actions tab; failed builds appear there.
- launchd: `launchctl list news.seminews.daily` — exit code should be 0.
