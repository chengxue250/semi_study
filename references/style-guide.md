# Editorial style guide — Semiconductor News Daily

This file exists because semiconductor coverage has more land mines than most
beats. Confusing wafer starts with chip shipments, treating yields as fixed,
calling every accelerator an "AI chip" — these are the small errors that mark a
news roundup as written by someone who doesn't know the industry. Read this
once; refer back when a story's framing feels off.

## 1. Voice

- Industry-press calm. Assume the reader knows what EUV, HBM, foundry, and node
  shrink mean. Don't define them; don't apologize for them.
- Present tense, active voice. "ASML lifts its 2026 booking guidance" — not
  "ASML has announced that it has raised."
- Lead with the news. The first sentence states what changed. Context follows.
- No "industry observers say." Either attribute, or drop the claim.
- No hype words: revolutionary, game-changing, mind-blowing, killer. The
  numbers carry the weight.

Examples of the bar we're aiming at:
> TSMC's first Arizona fab began limited 4nm production this quarter at yields
> roughly six points behind its Hsinchu twin, according to two suppliers
> briefed on the ramp. Cost per wafer is running ~30% above Taiwan; the gap is
> the central question for Phase 2.

> Samsung delayed the Pyeongtaek P4 Phase 1 ramp by two quarters as HBM3E
> demand from Nvidia kept the existing HBM lines fully booked through 1H 2026.

Not this:
> Chip giant TSMC has reportedly announced exciting news today about their
> revolutionary new Arizona fab! Industry watchers are abuzz...

## 2. The news, not the press release

Companies write press releases to land a frame. The job is to extract the news
underneath:

- "We are pleased to announce a strategic partnership with X" → *what changed?*
  A supply deal? Equity? Co-development? Say which.
- "Industry-leading performance" → cite the benchmark or drop the claim.
- "Expand capacity" → by how many wafer starts per month, when, at which node.

If a release is too thin to support a story, skip it. Empty stories dilute the
edition.

## 3. Common factual landmines

- **Wafer starts ≠ chip output.** A 300mm wafer might yield ~100 large GPUs or
  ~5,000 small MCUs. Reporting "X wafers" without specifying the product
  hides the real capacity story.
- **Yield is a moving target.** A "70% yield" headline is meaningless without
  the die size and time horizon (day-one yield vs. mature yield differ by
  20+ points).
- **Process node names are marketing.** TSMC N3, Intel 18A, Samsung SF3 are
  not directly comparable. Always pair the node name with the company.
- **Capex ≠ capacity.** A $40B capex announcement is a multi-year envelope;
  most of it lands as buildings, not tools. Note the years.
- **"Backside power" and "GAA" are distinct steps.** Don't conflate.
- **Memory bit growth ≠ revenue.** A 25% bit-growth year can be a down revenue
  year if ASPs collapse. Distinguish.
- **Export controls cover specific items.** "Chip ban" is rarely accurate;
  say which tool / node / entity is restricted.

## 4. Featured stories

Mark 1–3 stories per edition as `featured: true`. Criteria:

1. **Materiality**: changes a roadmap, supply picture, or policy.
2. **Surprise**: was not the consensus expectation 24h ago.
3. **Reach**: affects multiple companies, not just one.

A pure earnings beat is rarely featured unless guidance reset expectations. A
new export-control rule almost always is.

## 4a. Challengers & non-incumbents (the Cerebras-class problem)

The default selection bar — "moves a stock," "changes supply" — quietly
filters out companies that don't have stocks or supply chains in the
mainstream sense. Cerebras, Groq, Tenstorrent, SambaNova, Etched, Lightmatter,
Ayar Labs, Celestial AI, EnCharge, Rebellions, Furiosa, Rivos, d-Matrix,
Hailo, Mythic, Esperanto, Rain — these are the companies most likely to
matter in five years and least likely to clear the incumbent bar today.

Apply a **separate, parallel bar** for the `challengers` section. Include a
challenger story when *any one* of these is true:

- **Real silicon shipping or deployed.** A named customer datacenter or
  edge installation, not a press demo. A CS-3 in a Mayo Clinic rack counts;
  "Cerebras announces collaboration with X" does not.
- **A named customer.** Production design wins (Meta on SambaNova, OpenAI on
  AMD MI450, anyone on Etched Sohu) are signal even before silicon ships.
- **Genuinely new architecture.** Wafer-scale, deterministic-LPU,
  spatial-dataflow, photonic compute, in-memory analog — these change the
  shape of the problem and merit coverage even on a slow news day for the
  company.
- **A funding round with a real lead and a real number** — Series B/C+ that
  signals strategic interest from a hyperscaler or a fab.

Do *not* include:

- Generic VC press releases ("X raises $20M to revolutionize AI compute").
- Founder podcast appearances or conference keynotes without new content.
- "X partners with Y" announcements where the deliverable is undefined.
- Speculation pieces by analysts who don't actually cover the company.

**One challenger story is enough on most days; some days will yield none.**
Leave the section empty when nothing qualifies rather than padding — the
section signals "we are watching this layer of the industry," not "we will
manufacture coverage of it daily."

Translation for the section title: `Challengers & New Silicon` / `新势力与新硅`.
For company names, keep the original Latin form in 中文 — don't translate
"Cerebras" or "Groq."

## 5. The daily theme

The masthead headline names the day. Read all your selected stories first, then
ask: *what is the through-line?* It does not have to cover every story — it
should crystallize the single most important shift.

Good themes:
- "TSMC's Arizona Ramp Hits a Cost Wall"
- "Memory's Up-Cycle Meets AI's Bottleneck"
- "Export Controls Tighten the Equipment Stack"
- "Custom Silicon Eats the Hyperscaler"

Avoid:
- "Daily Semiconductor News" (no thesis)
- "Big Day for Chips!" (not a thesis)
- A theme that's just the lead story's headline (waste of the slot)

## 6. Translation conventions (EN → 中文)

The page is bilingual; the 中文 version is not a literal translation but a
re-write for a Chinese-reading audience. Use these renderings consistently so
archived editions remain searchable.

| English                  | 中文                  | Notes |
|--------------------------|----------------------|-------|
| process node / node      | 制程 (preferred) / 工艺 | use 制程 in masthead, either in body |
| foundry                  | 晶圆代工 / 代工厂      | drop 厂 when used as a category |
| wafer starts             | 晶圆投片量            |       |
| yield                    | 良率                  |       |
| EUV lithography          | EUV光刻               | keep EUV in Latin letters |
| backside power delivery  | 背面供电              |       |
| gate-all-around (GAA)    | 全环绕栅极 (GAA)       | first mention spelled out |
| advanced packaging       | 先进封装              |       |
| chiplet                  | 小芯片 / chiplet      | use chiplet on second mention |
| HBM / DRAM / NAND        | HBM / DRAM / NAND     | keep in Latin letters |
| export controls          | 出口管制              |       |
| entity list              | 实体清单              |       |
| capex                    | 资本开支              |       |
| guidance                 | 业绩指引              |       |
| accelerator              | 加速器                |       |
| inference / training     | 推理 / 训练            |       |
| supply chain             | 供应链                |       |
| photoresist              | 光刻胶                |       |

Numerals: keep ASCII digits (3nm, $40B, 25%). Don't convert to full-width.

## 7. Things to actively avoid

- Republishing analyst price targets without source.
- "Sources said" without specifying *kind* of source (supplier, engineer,
  former employee, etc.).
- Top-10 lists, "best of," roundups of roundups.
- Speculation about future products framed as fact.
- AI-generated boilerplate phrases: "this development underscores," "as the
  industry continues to evolve," "stay tuned for more."

## 8. The reader

Implicit reader: a chip industry professional or serious investor. Reads ~5
minutes per day. Already saw the headlines on Twitter/X. Wants: signal, frame,
and one clear sentence of *why this matters* per story. Doesn't want: AI
boilerplate, drama, or being talked down to.
