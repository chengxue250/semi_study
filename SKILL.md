---
name: semi-news-daily
description: Build a daily semiconductor news digest as a self-contained HTML page in the style of myown.news, with an EN/中文 toggle, and a sibling research page covering the latest academic developments in semiconductors and electrical engineering (arXiv, IEEE, Nature Electronics, ISSCC/IEDM/VLSI). Use this skill whenever the user asks for a daily semi/chip industry briefing, a "today's edition," a curated digest of foundry/memory/AI-chip/equipment/packaging stories, an academic-paper reading queue for chips/EE, or wants to (re)generate, refresh, update, or schedule the semiconductor news site. Trigger even when the user just says things like "run the news," "build today's digest," "update the chip news page," "add the research page," or asks to add a source or fix the layout — as long as the work is about the semiconductor news site this directory produces.
---

# Semiconductor News Daily

This skill produces **two** sibling HTML pages from a single `edition.json`:

- `output/index.html` — daily **news** digest, modeled on https://myown.news (centered column, themed daily headline, story cards grouped by section).
- `output/research.html` — weekly-cadence **academic / EE research** digest, denser paper-card layout with authors, venues, and links to arXiv / IEEE / journals.

Both are self-contained (inlined CSS + tiny JS), bilingual (English + 中文 via in-page toggle), cross-linked in the top nav, and share the same brand/color palette (news = amber accent, research = green accent so the two pages are visually distinguishable at a glance).

The skill is platform-agnostic. It runs anywhere an agent can read files, run Python, search the web, and fetch URLs — Claude Code, Cursor, Aider, Cline, Continue, OpenCode, and similar. The bundled Python scripts do the deterministic work (RSS pulling, HTML assembly) so the agent's job is curation, summarization, and theming — the parts that need judgment.

## Required capabilities

- Read & write files in this directory.
- Run `python3` (stdlib only — no pip installs required for the scripts).
- Search the web (any tool; results go through the agent, not a fixed API).
- Fetch a URL and read its main text (any tool).

If a platform lacks web search, fall back to the RSS-only flow in `scripts/fetch_rss.py` — it pulls candidate stories from `references/sources.yaml` without any search engine.

## Workflow

Follow these steps in order. Each step has a clear handoff so a fresh agent can resume mid-run.

### 1. Resolve today's date and prior context

- Use the system date (the agent's current date). Format as `YYYY-MM-DD`.
- If `output/index.html` already exists with today's date in its `<meta name="edition-date">`, ask the user whether to **refresh** (re-run today) or **skip**. Default to refresh.
- **`output/.seen_urls.json`** is the source of truth for "what we've already published." It's a flat `{url: first-seen-date}` map covering both news story URLs and research paper venue URLs. The next steps use it to filter candidates so daily runs don't repeat the same items. Same-day re-runs are explicitly supported — only URLs first seen on a *previous* day are filtered out.
- Read `output/archive/` to see what shape yesterday's edition took (sections, themes) — useful for choosing a complementary theme today.

### 2. Gather candidate stories (cast a wide net)

Combine two sources of candidates so neither single mechanism is a bottleneck:

**a. RSS (deterministic, always run this first):**

```bash
python3 scripts/fetch_rss.py \
  --since-hours 24 \
  --exclude-seen output/.seen_urls.json \
  --out /tmp/semi_rss.json
```

This pulls every feed listed in `references/sources.yaml`, filters to entries newer than 24 hours, drops any URL already published in a previous edition (via `--exclude-seen`), and writes the survivors to the output path as `{title, link, source, published, summary}`.

The 24-hour window matches the daily-run cadence. **Why not the older 36-hour window?** Without `--exclude-seen` the 36h overlap was needed to catch late-publishing items; with `--exclude-seen` the overlap would just re-pull stories we already shipped yesterday. The de-dup filter handles the "late publisher" case correctly: anything still genuinely new (not in `.seen_urls.json`) survives.

**b. Web search (judgment-driven):**

Run 4–6 targeted searches to surface stories RSS misses (paywalled outlets, social-driven scoops, non-English originals). Suggested queries — adapt to current events:

- "semiconductor news today"
- "TSMC OR Samsung OR Intel OR SK hynix news this week"
- "EUV lithography ASML news"
- "AI chip Nvidia AMD news this week"
- "chip export controls China news"
- "HBM memory news this week"

Filter aggressively: skip stories older than ~24h, press-release republishing, and product-review fluff. **Also cross-check every web-search hit against `output/.seen_urls.json`** — if the URL is there with a date < today, drop it. The RSS script does this automatically; web-search results don't pass through the script so the agent must do the check explicitly. Keep the original publisher's URL when possible (Google News redirect URLs are stable enough to use as keys, but prefer the canonical link when known).

### 3. Curate to ~10–15 stories

Aim for a tight, high-signal edition. Drop anything that doesn't pass at least one of these tests: moves a stock, changes a roadmap, affects supply, signals a policy shift, or surfaces meaningful research. **Avoid near-duplicates** — if two outlets cover the same news, pick the primary source (or the most analytical write-up).

Strive for spread across these sections — but don't force-fill empty ones; an edition with only 3 sections is fine if that's the day:

- **AI & Accelerators** — Nvidia, AMD, custom silicon, training/inference hardware
- **Foundry & Manufacturing** — TSMC, Samsung Foundry, Intel Foundry, SMIC, process nodes
- **Memory** — DRAM, HBM, NAND, CXL
- **Equipment & Materials** — ASML, Applied Materials, Lam, Tokyo Electron, wafers, photoresist
- **Policy & Geopolitics** — export controls, CHIPS Acts, sanctions, M&A reviews
- **Earnings & Markets** — quarterly results, guidance, M&A
- **Research & Roadmaps** — papers, conference news (ISSCC, VLSI, Hot Chips, IEDM), 2nm/A14/A10
- **Packaging & Advanced Nodes** — CoWoS, SoIC, glass substrates, chiplets

Mark the 1–3 most important stories as `featured: true` — they render larger at the top.

### 4. Theme the day (the masthead headline)

myown.news names each edition with a short, sharp thematic headline (e.g., "AI's Scarcity Economy Comes Into Focus"). Do the same. Read your curated stories, find the through-line, and write a 4–10 word headline in both languages.

Examples of the voice — incisive, present-tense, no hype:
- "TSMC's Arizona Ramp Hits a Cost Wall" / "台积电亚利桑那的成本之墙"
- "Memory's Up-Cycle Meets AI's Bottleneck" / "存储上行周期撞上AI瓶颈"
- "Export Controls Tighten the Equipment Stack" / "出口管制收紧设备供应链"

Avoid: "Daily Semiconductor News" (boring), "Big Day in Chips!" (childish), or any clickbait.

### 5. Summarize each story

For every selected story, write:

- **Title** — keep the publisher's title unless it's misleading. Translate to 中文 too.
- **Summary** — 2–4 sentences. Lead with the *news* (what changed), not the company's framing. Add one sentence of context (why it matters / who else is affected) if the wire copy doesn't include it.
- **Meta** — source name, publish time (relative: "4h ago" / "4小时前").

See `references/style-guide.md` for tone, common pitfalls (e.g., conflating wafer-start capacity with chip output), and translation conventions for technical terms.

### 6. Assemble the structured edition

Build a JSON object matching this shape and write it to `output/edition.json`:

```json
{
  "date": "2026-05-21",
  "theme": {
    "en": "Memory's Up-Cycle Meets AI's Bottleneck",
    "zh": "存储上行周期撞上AI瓶颈"
  },
  "dek": {
    "en": "HBM3E supply remains the gating factor for H200 and MI300X shipments through Q3.",
    "zh": "HBM3E供给仍是H200和MI300X三季度出货的关键瓶颈。"
  },
  "sections": [
    {
      "id": "ai-accelerators",
      "title": {"en": "AI & Accelerators", "zh": "AI与加速器"},
      "stories": [
        {
          "featured": true,
          "title": {"en": "...", "zh": "..."},
          "summary": {"en": "...", "zh": "..."},
          "source": "SemiAnalysis",
          "url": "https://...",
          "published": "2026-05-21T08:30:00Z"
        }
      ]
    }
  ]
}
```

### 7. Optionally, build the research block

If the user asks for or implies research/academic coverage — or simply if it's been ≥ 5 days since the last `research.html` update — add a `research` block to `edition.json`. See `references/research-guide.md` for the full editorial guide; the short version:

1. Pull arXiv + journal RSS:
   ```bash
   python3 scripts/fetch_rss.py \
     --role research \
     --since-hours 168 \
     --exclude-seen output/.seen_urls.json \
     --out /tmp/semi_research.json
   ```
   The `--role research` flag is honored if the feed entry in `sources.yaml` has `role: research`. Default look-back is **7 days** (168h) rather than 24h because paper diffusion is slower. The same `--exclude-seen` filter applies — `.seen_urls.json` stores both news URLs and research paper venue URLs, so a paper summarized in any prior edition (even months ago) won't be re-summarized today.

2. Select **8–15 papers** across the research sections in `sources.yaml`. Apply the bar in `research-guide.md` § "Selection criteria" — measured silicon over simulation, top venues, real bottlenecks. If a paper looks compelling but isn't in the filtered RSS output, *double-check it isn't in `.seen_urls.json`* before adding it manually — the most common cause of a "missing" paper is that you already wrote it up last week.

3. Write each paper's bilingual summary as a **3–4 sentence "what's new + why it matters + caveats"**, *not* a rephrased abstract. See `research-guide.md` § "Voice."

4. Append a `research` block to `edition.json`:
   ```json
   "research": {
     "window_days": 7,
     "theme":  {"en": "Backside Power Moves From Roadmap to Tape-out", "zh": "..."},
     "dek":    {"en": "...", "zh": "..."},
     "areas": [
       {
         "id": "devices",
         "title": {"en": "Devices & Process", "zh": "器件与工艺"},
         "papers": [
           {
             "title":       {"en": "...", "zh": "..."},
             "authors":     "L. Chen, K. Park, M. Tanaka, et al.",
             "affiliation": "imec / KAIST",
             "venue":       "arXiv:2605.12345",
             "venue_url":   "https://arxiv.org/abs/2605.12345",
             "summary":     {"en": "...", "zh": "..."},
             "published":   "2026-05-19",
             "tags":        ["preprint", "tape-out"]
           }
         ]
       }
     ]
   }
   ```

5. The renderer (step 8) builds `output/research.html` automatically if the `research` block has at least one paper.

### 8. Render the HTML

```bash
python3 scripts/build_page.py
```

This:
- writes `output/index.html` (news);
- if `edition.json` has a `research` block with papers, writes `output/research.html`;
- rotates yesterday's index/research into `output/archive/` and `output/archive/research/` respectively;
- regenerates `output/archive.html`;
- **appends every published URL to `output/.seen_urls.json`** with today's date as first-seen. Existing entries keep their original first-seen date (so a same-day re-run doesn't promote yesterday's URLs to today), and entries older than 90 days are pruned to bound the file size.

The script is idempotent — running it twice on the same day overwrites cleanly without duplicating archive entries.

### 9. Verify

- Open `output/index.html` and confirm: masthead theme renders, EN/中文 toggle flips all blocks, every story has a working source link, the date is today, Headlines/Research nav links work.
- If research was built, open `output/research.html` and confirm: papers render in the right areas, every paper has a venue link, EN/中文 toggle works, "back to today's headlines" footer link works.
- Confirm `output/archive.html` lists today's edition at the top.

### 10. (Optional) Push to the user's phone

If `notify.yaml` exists at the project root, run:

```bash
python3 scripts/notify.py
```

This sends the theme headline + dek as a push notification through whichever channels are configured (currently: ntfy.sh). When the user taps the notification, it opens the public URL of the rendered page (typically GitHub Pages).

Setup is documented in `notify.yaml.example` and `references/automation.md` § "Pushing to your phone." Required capabilities for this step: `python3` and outbound HTTPS (which any platform that runs the rest of the skill already has). No API key needed for ntfy.sh on public topics — the security model is a long, unguessable topic name.

If `notify.yaml` does not exist, skip this step. The skill never refuses to run because notification is unconfigured.

## Editorial defaults the agent should preserve

These keep the publication recognizable day-to-day:

- **Voice**: industry-press, not breathless. Assume the reader knows what a foundry is.
- **No company press-release language**. Never paste vendor blurbs.
- **Numbers**: prefer specifics (yields, wafer starts, capex dollars) over vague adjectives.
- **No top-10 lists, no slideshows, no "you won't believe" framing.**
- **Source attribution is mandatory** — every story links to its publisher.

See `references/style-guide.md` for the long version.

## Customizing the run

- **Add / remove sources** → edit `references/sources.yaml`. The script picks up new feeds on the next run.
- **Change the section taxonomy** → edit the `sections` array you pass to `build_page.py`; the template renders whatever sections you provide.
- **Change look-and-feel** → edit `assets/template.html`. The template uses placeholders like `{{DATE}}`, `{{THEME_EN}}`, `{{SECTIONS}}` — keep them.
- **Different cadence** (weekly, etc.) → change `--since-hours` in step 2. The skill itself is cadence-agnostic.

## Scheduling daily runs

See `references/automation.md` for ready-to-use snippets:
- macOS launchd plist
- Linux/macOS crontab
- GitHub Actions workflow (publishes to GitHub Pages)
- A generic shell script that wraps "have your agent CLI run this skill"

The skill itself does not install any scheduler — that's a system-level choice and varies per user.

## When something goes wrong

- **Empty RSS results** → check `references/sources.yaml` for broken feed URLs. Many outlets quietly move RSS endpoints; `python3 scripts/fetch_rss.py --probe` tests each feed and reports HTTP status.
- **Web search returns yesterday's news** → some search backends are slow to index; widen the search window and lean more on RSS.
- **Chinese translation feels stiff** → see `references/style-guide.md` § "Translation conventions" for the project's preferred renderings (e.g., 制程 vs 工艺 for "process node").
- **A story has no clean URL** (paywall, login wall) → include it only if you can summarize from a freely accessible secondary source, and link to that instead.

## Files in this skill

```
SKILL.md                       (this file)
references/
  sources.yaml                 Curated outlets + RSS feeds + research feeds + section taxonomies
  style-guide.md               Editorial voice for news, translation glossary, common pitfalls
  research-guide.md            Editorial voice for the research page (academic/EE papers)
  automation.md                Cron / launchd / GitHub Actions samples
  run-instructions.md          Per-platform invocation notes
assets/
  template.html                News page template (amber accent)
  research-template.html       Research page template (green accent, denser layout)
scripts/
  fetch_rss.py                 Pulls RSS feeds → JSON (supports --role research)
  build_page.py                Renders edition.json → today's HTML pages + archive
  notify.py                    (Optional) sends ntfy.sh push notification to user's phone
notify.yaml.example            Sample notification config; copy to notify.yaml (gitignored)
output/                        Generated site (this is what you serve)
  index.html                   Today's news edition
  research.html                Today's research digest (only when research block present)
  archive.html                 Listing of past editions
  archive/YYYY-MM-DD.html      Past news editions
  archive/research/YYYY-MM-DD.html  Past research digests
  edition.json                 Today's structured data (news + optional research)
  .seen_urls.json              {url: first-seen-date} for de-dup across daily runs;
                               auto-updated by build_page.py, consumed by --exclude-seen
```
