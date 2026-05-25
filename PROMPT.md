# Curation prompt — write today's `output/edition.json`

You are doing one job today: **picking stories and papers from pre-fetched
JSON files, summarizing each, and writing a single file** at
`output/edition.json`. You will not run any scripts. You will not touch any
other files. The orchestrator handles everything else.

## What's already done for you

- News candidates: `/tmp/preflight/news.json` (~80 most-recent items, all
  guaranteed new — duplicates with past editions are already filtered out)
- Research candidates: `/tmp/preflight/research.json` (~80 most-recent items,
  merged across arXiv, Semantic Scholar, and research RSS feeds —
  covers preprints, IEEE/conference papers, and journal articles)
- Yesterday's edition is at `output/edition.json.previous`. **Do not reuse
  any URL from it.** The validator will reject your work if you do.

## Pick

1. **8–12 news stories** from `/tmp/preflight/news.json`. Aim to spread
   across these sections (use the IDs exactly as written):
   - `ai-accelerators` — Nvidia, AMD, accelerator chips, AI hardware deals
   - `foundry` — TSMC, Samsung Foundry, Intel Foundry, SMIC
   - `memory` — HBM, DRAM, NAND, SK hynix, Micron
   - `equipment` — ASML, Applied Materials, Lam, tools, materials
   - `policy` — export controls, sanctions, M&A reviews
   - `earnings` — quarterly results, guidance changes
   - `challengers` — Cerebras, Groq, Tenstorrent, SambaNova, etc.
   Mark **1–3** of the highest-materiality stories as `"featured": true`.

2. **6–10 research papers** from `/tmp/preflight/research.json`. Across:
   - `devices` — fabrication, materials, transistor work
   - `circuits` — circuit design, architecture, reliability
   - `accelerators` — AI accelerators, compute-in-memory, near-memory
   - `ai-research` — quantization, MoE, KV-cache, inference systems
   - `quantum`, `eda` — when relevant

3. **A theme** for the day — one short, present-tense phrase capturing the
   through-line of the news (5–10 words). And a 1–2 sentence dek elaborating it.

## Summarize each item

- 2–4 sentences each.
- Lead with the news / result. Then why it matters. Avoid PR-speak ("game-
  changing," "revolutionary"). Use specific numbers when the source has them.
- **English is required.** Chinese is optional — if you cannot write
  fluent technical Chinese, set `"zh": ""` and the page will fall back to
  the English text in the 中文 toggle. Do not output low-quality Chinese.

## Save to `output/edition.json` using EXACTLY this structure

```json
{
  "date": "YYYY-MM-DD",
  "theme": {"en": "Short present-tense phrase", "zh": ""},
  "dek":   {"en": "1-2 sentence elaboration of the theme.", "zh": ""},
  "sections": [
    {
      "id": "ai-accelerators",
      "title": {"en": "AI & Accelerators", "zh": "AI与加速器"},
      "stories": [
        {
          "featured": true,
          "title":   {"en": "Story title", "zh": ""},
          "summary": {"en": "2-4 sentences.", "zh": ""},
          "source":  "Publisher name",
          "url":     "https://… (copied verbatim from news.json's 'link' field)",
          "published": "2026-..."
        }
      ]
    }
  ],
  "research": {
    "window_days": 7,
    "theme": {"en": "Short phrase", "zh": ""},
    "dek":   {"en": "1-2 sentences.", "zh": ""},
    "areas": [
      {
        "id": "accelerators",
        "title": {"en": "AI Accelerators & Compute-in-Memory",
                  "zh": "AI加速器与存算一体"},
        "papers": [
          {
            "title":      {"en": "Paper title (you may rephrase for clarity)", "zh": ""},
            "authors":    "L. Chen, K. Park, et al.",
            "affiliation": "",
            "venue":      "arXiv:2605.…",
            "venue_url":  "https://arxiv.org/abs/… (copied verbatim from arxiv.json's 'link' field)",
            "summary":    {"en": "2-4 sentences.", "zh": ""},
            "published":  "2026-..."
          }
        ]
      }
    ]
  }
}
```

## Hard rules (the validator will catch these and abort the publish)

1. The `date` field must be **today's UTC date**. Look at the top of
   `/tmp/preflight/instructions.txt` for it.
2. Every story's `url` and every paper's `venue_url` **must be copied
   verbatim** from the candidate JSON files. Do not paraphrase URLs. Do
   not invent URLs.
3. At least 5 stories total. (Research can be empty if it's a weekend
   and arxiv.json is thin.)
4. ≥50% of URLs in your edition must NOT appear in
   `output/edition.json.previous`. This catches re-stamping yesterday's
   edition with a new date.
5. Don't leave any summary empty or shorter than ~60 characters.

## After you're done

Save the file and exit. The orchestrator will run `validate_edition.py`,
then `build_page.py`, then publish to GitHub Pages. If validation fails,
the orchestrator will tell you exactly which rule was violated; fix only
that and re-save.
