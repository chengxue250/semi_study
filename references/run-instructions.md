# Running this skill on different platforms

The skill is a folder with a `SKILL.md`, scripts, and templates. There is no
binary, no install step, no API key built in. Any agent that can read files,
run Python, and browse the web can drive it. Here's how to wire it up per
platform.

The user-facing prompt is the same everywhere:

> Build today's semiconductor news edition using the skill in this directory.

The agent should then read `SKILL.md` and follow the workflow.

---

## Claude Code (Anthropic)

Two ways.

**A. Project-local skill (no install).** From the project directory:

```bash
cd /Users/hcxj/Documents/CC/semi_news
claude
> Build today's semiconductor news edition using the SKILL.md in this directory.
```

`SKILL.md` is in CWD so Claude reads it directly.

**B. Installed skill (callable from anywhere).** Symlink into the user skills
directory once:

```bash
mkdir -p ~/.claude/skills
ln -s /Users/hcxj/Documents/CC/semi_news ~/.claude/skills/semi-news-daily
```

Then in any Claude Code session: `/skill semi-news-daily` (or just describe
what you want and the description in the frontmatter should trigger it).

**Headless / scheduled:**

```bash
claude -p "Build today's semiconductor news edition." \
       --permission-mode acceptEdits \
       --max-turns 60
```

---

## Cursor / Cursor Agent

Cursor doesn't have a "skills" concept yet, but it reads project files. Drop a
short rule into `.cursorrules` (or `.cursor/rules/semi-news.md`) that points at
`SKILL.md`:

```
When the user asks to build, refresh, or update the semiconductor news site,
read ./SKILL.md and follow the workflow in it exactly. The scripts under
./scripts/ are stdlib-only and safe to run.
```

Then in chat: "build today's edition." The agent loads `SKILL.md` as part of
the project context.

---

## Aider

Aider doesn't load skill frontmatter, but you can `/read` the skill file:

```bash
aider --read SKILL.md --read references/style-guide.md
> Build today's semiconductor news edition using the workflow in SKILL.md.
```

For automation use `--message`:

```bash
aider --read SKILL.md --read references/style-guide.md \
      --message "Build today's edition end to end. Run the scripts. Write all files. No clarifying questions."
```

---

## Cline / Continue / Roo Code

These are VS Code extensions and all of them index workspace files. Open the
folder, then in the chat panel:

> Read SKILL.md and build today's semiconductor news edition.

If the extension supports custom modes or prompts, save the line above as the
default prompt for this workspace.

---

## OpenCode / open-source Claude alternatives

OpenCode and similar projects either (a) read a `SKILL.md` directly, or (b)
read `AGENTS.md` / `.agentrc`. If yours is (b), add a thin pointer file:

```
# AGENTS.md
When working in this directory, read ./SKILL.md and treat it as the operating
manual. The workflow there is the source of truth.
```

The skill itself doesn't change.

---

## "Manual" / no agent at all

If you don't want any LLM in the loop on a given day, you can still get a
crude edition: run the RSS fetcher, hand-write `output/edition.json` based on
its output, and render:

```bash
python3 scripts/fetch_rss.py --since-hours 36 --out /tmp/semi_rss.json
# ...edit /tmp/semi_rss.json down to today's picks and reshape into edition.json...
python3 scripts/build_page.py --edition output/edition.json --template assets/template.html
```

This loses the curation and summarization that an agent provides, but it
proves the pipeline works without any model.

---

## What the agent needs in any platform

If you're porting this to a new platform, confirm the agent has:

1. **File read & write** in the skill directory.
2. **`python3` in PATH**, stdlib only. (No `pip install` required.)
3. **Web fetch** capability (any tool). Used for paywalled / non-RSS stories.
4. **Web search** capability (optional but strongly recommended). Used to
   surface stories RSS misses.

If only #1 and #2 are available, you'll still get an edition — it just won't
include anything that wasn't in RSS that day.
