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

## Running on a weak/cheap LLM (openclaw, ollama, etc.)

The default skill workflow assumes a capable agent that can read SKILL.md, plan, and execute multi-step tasks. Weaker LLMs (small open-source models, GPT-3.5-class, anything where the per-day cost matters) tend to fail in a specific way: they read SKILL.md, see that `output/edition.json` exists, decide nothing needs to change, and just bump the date field. The site then publishes yesterday's content under today's date. We confirmed this empirically on 2026-05-{22..24}.

The fix is the **scripted pipeline**: `scripts/run_daily.sh`. It runs every deterministic step (fetch, dedup, shortlist, render, archive, publish) in bash and only invokes the LLM for one narrow task — writing `output/edition.json` from pre-fetched JSON candidate files. The LLM cannot accidentally skip the work because the work is happening around it, not inside it.

### Pipeline shape

```
scripts/run_daily.sh  (cron triggers this once a day)
  1. git pull origin main
  2. scripts/preflight.py
       - moves output/edition.json → output/edition.json.previous
       - runs fetch_rss.py and fetch_arxiv.py with --exclude-seen
       - shortlists ~80 newest items into /tmp/preflight/{news,arxiv}.json
       - aborts the whole run if fetches returned too few items
  3. scripts/agent-invoke.sh    ← the LLM's only job (writes edition.json)
  4. scripts/validate_edition.py
       - date == today
       - ≥ 5 stories total, fields populated
       - every URL came from /tmp/preflight/{news,arxiv}.json
         (so a re-stamp of yesterday is impossible — yesterday's URLs aren't
         in today's fetch)
       - ≥ 50% of URLs are new vs yesterday's edition
       - if any check fails, abort: do NOT render, do NOT commit, do NOT publish
  5. python3 scripts/build_page.py     (render index.html + research.html)
  6. git add output/ && git commit && git push origin main
  7. scripts/publish_gh_pages.sh main  (safe via temp clone)
```

If step 3 or 4 fails, the live site keeps yesterday's content. Better stale than wrong.

### Setup (one time, ~5 minutes)

1. **Wire your LLM to `scripts/agent-invoke.sh`**:

   ```bash
   cp scripts/agent-invoke.sh.template scripts/agent-invoke.sh
   chmod +x scripts/agent-invoke.sh
   $EDITOR scripts/agent-invoke.sh
   ```

   The template shows four worked examples (Claude Code, openclaw-style agent, Aider, plain OpenAI HTTP). Pick one, fill in your model name and key.

   `scripts/agent-invoke.sh` is gitignored on purpose — each operator's invocation is local.

2. **Smoke-test the pipeline once**:

   ```bash
   DRY_RUN=1 scripts/run_daily.sh   # does everything except git push
   ```

   You should see the six section headers fire in order. If preflight or validation aborts, the error message tells you which rule was violated.

3. **Schedule it.** Pick your scheduler — launchd / cron / GitHub Actions / systemd timer. The wrapper is just `scripts/run_daily.sh` from the project directory. See the platform-specific sections below.

### Why this works for weak LLMs

The PROMPT.md file the agent reads is short (~80 lines) and tightly focused:

- "Read these two JSON files."
- "Pick N stories and M papers."
- "Write to this exact JSON structure."
- "Chinese is optional. If you can't write good Chinese, leave `zh: ""` and the renderer will fall back to English."

No process steps, no shell commands, no decisions about what to fetch or where to publish. The LLM never sees `SKILL.md` (the longer file) at all.

### Catching the openclaw failure mode specifically

The validator's `check_urls_in_candidates` rule is the single most important defense: every URL in `output/edition.json` must appear in the just-fetched `/tmp/preflight/news.json` or `/tmp/preflight/arxiv.json`. If the agent re-stamped yesterday's edition, the URLs would be from yesterday's fetch and wouldn't appear in today's. Validation fails. Site stays at yesterday's content.

The `check_not_a_restamp` rule provides a second layer: ≥50% of URLs must differ from the previous edition. Catches the case where some URLs do persist legitimately (e.g., a follow-on story) but the agent reused too many.

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

# Publish output/ to the gh-pages branch (safe — clones into /tmp first).
# Do NOT replace this with a manual `git checkout --orphan gh-pages …`
# pattern; that leaks any untracked file in the working tree, including
# .gitignored secrets like notify.yaml. See scripts/publish_gh_pages.sh
# for the rationale.
scripts/publish_gh_pages.sh main
```

## Publishing to gh-pages (manual or scripted)

GitHub Pages is set up to deploy from the `gh-pages` branch root. Whenever
you want to push a new edition to the live site, run:

```bash
scripts/publish_gh_pages.sh [source-ref]   # source-ref defaults to "main"
```

The script clones the repo into a temp directory and operates entirely
there, so:

- `.gitignored` files in your working tree (notify.yaml, .env, .claude/,
  etc.) **cannot** end up on gh-pages, even by accident.
- Your working tree is not modified.
- Force-push to `gh-pages` is safe because that branch is derived state.

**Do not** publish gh-pages with the naïve "orphan branch in the project
directory" pattern (`git checkout --orphan gh-pages && git add -A && git
push --force …`). That pattern silently leaks every untracked file at the
project root. We hit this bug twice on 2026-05-23 before writing the
script — once is unlucky, twice means the pattern itself is wrong.

If the script fails, exit codes are:

- `0` — pushed
- `2` — bad input (missing ref, no `output/`, no remote configured)
- `3` — push failed (network, auth, force-push protection, etc.)

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
