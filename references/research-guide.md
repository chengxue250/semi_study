# Research-page editorial guide

The news page (`output/index.html`) is for what *happened* in the industry
yesterday. The research page (`output/research.html`) is for what *the
literature said* in the last week — preprints, conference papers, journal
articles, lab announcements. Different cadence, different voice, different
layout. This file is how to write the research page.

## Cadence

Default look-back is **7 days** for research (vs. 24 hours for news), because
papers diffuse more slowly and a single day of arXiv is not enough signal.

The research workflow now runs three fetchers in parallel:

- `scripts/fetch_arxiv.py --days 7` — arXiv preprints, real date range via
  the arXiv Query API. Works on weekends. This replaces the old arXiv RSS
  feeds, which only carried today's announcement batch (empty Sat/Sun).
- `scripts/fetch_semscholar.py --days 14` — conference proceedings and
  journal papers (ISSCC, IEDM, MICRO, IEEE JSSC, Nature Electronics, …) via
  Semantic Scholar. Wider window because publication dates lag the actual
  work by weeks.
- `scripts/fetch_rss.py --role research --since-hours 168` — non-arXiv,
  non-S2 research RSS feeds.

It is fine for the research page to update less often than the news page. If
nothing meaningful landed in a domain this week, leave that section empty
rather than padding. **What changed in this iteration**: the empty-Saturday
problem we hit on 2026-05-23 is gone — `fetch_arxiv.py` returned real papers
that day because it queries an API, not a daily RSS dump.

## Voice

The audience is a working engineer or a grad student. They've read abstracts
before. They want:

1. **What's actually new** in one sentence. Not "the authors propose..." —
   what specifically is novel relative to prior work?
2. **Why it matters** in one sentence — what changes downstream if this holds
   up.
3. **Sober caveats** if the paper is preprint-only, uses a synthetic
   benchmark, or hasn't been replicated.

Do *not* paraphrase the abstract. Abstracts are written to sell the paper; the
job here is to tell the reader whether to spend 20 minutes on it.

Examples of the bar:

> Liu et al. demonstrate a 2T0C gain-cell DRAM bitcell in a 4F² IGZO/Si
> hybrid stack with a measured 100ms retention at 85°C, the first report at
> that footprint outside research-lab silicon. If it scales, the cell sits
> between SRAM and conventional DRAM on density and could plausibly host
> LLM KV-cache. Tape-out test chip only — no manufacturability data yet.

Not this:

> The authors present a novel approach to memory technology that
> demonstrates promising results and may have significant implications for
> the field, building on prior work in the area.

## Don't re-summarize papers we've already covered

The research page shares `output/.seen_urls.json` with the news page. A paper
whose `venue_url` (arXiv abs page, DOI link, journal article URL) is in that
file with a date before today is *already in a past edition* — do not
re-summarize it. `fetch_rss.py --exclude-seen` filters arXiv RSS hits
automatically; if you find a paper through manual search or by following a
citation, check the file yourself before adding it.

Paper-version updates (e.g., arXiv v2 of a paper we covered as v1) count as
the same paper unless the revision is *substantively* different — new
results, fab silicon where there was none, a fundamental change in claims.
If in doubt, skip; the field will surface it again at conference acceptance.

## Selection criteria

Per week, target **8–15 papers across all sections**. Drop anything that
fails *all* of the following:

- Reports measured silicon (not just SPICE/Cadence simulation).
- Touches a sub-7nm node, or addresses a known industry bottleneck (HBM
  bandwidth, GPU memory pressure, thermal density, RF efficiency at mmWave).
- Comes from a lab/group with prior real-silicon track record.
- Was accepted to a top venue: ISSCC, VLSI Symposium, IEDM, MICRO, ISCA,
  HotChips, DAC, ICCAD, HPCA, ASPLOS, Nature/Nature Electronics,
  Science/Science Advances, IEEE EDL/JSSC/TED/TVLSI.

Preprints from strong groups (Stanford SystemX, Berkeley BWRS, MIT MTL, KAIST,
imec, Tsinghua IME, etc.) clear the bar even before peer review.

### Section-specific bars

A few sections have their own criteria layered on top:

- **AI Accelerators & Compute-in-Memory**: prefer measured-macro results over
  paper-only proposals. The interesting question is always "what bitcell,
  what array size, what bit precision, what energy per op." If a paper
  doesn't answer all four, treat it as a survey-class item, not a result.

- **AI Research (hardware-relevant)**: this section is *not* a general ML
  digest. Include only papers where the contribution is something that
  changes what the hardware needs to do — i.e., the paper would belong in
  MLSys, MICRO, ASPLOS, HPCA, ISCA, or the systems track of a top ML venue.
  Concretely, include:
    - Quantization, sparsity, structured pruning that actually move the
      arithmetic-intensity needle.
    - Mixture-of-experts serving systems, KV-cache compression, speculative
      decoding hardware co-design.
    - Training-system papers: communication-collective optimizations, FP8
      training stability, ZeRO-type partitioning that maps to a real
      cluster topology.
    - New transformer/SSM/diffusion variants when they change the dominant
      kernel (e.g., linear-attention work that the hardware community will
      have to absorb).
  Exclude:
    - SOTA-chasing benchmark papers with no systems angle.
    - Alignment, safety, and pure RLHF/agent work.
    - Application-domain papers (medical, finance, etc.) regardless of
      benchmark wins.
    - Pure theory with no implementation.

## What each paper card should include

Render via the template; the fields are:

- `title`     — paper title (EN/中文). Translate technical terms per the
                glossary in `style-guide.md` § 6.
- `authors`   — "L. Chen, K. Park, M. Tanaka, et al." (first three +
                "et al." if longer).
- `affiliation` — "imec / KAIST" or similar — primary institutions only.
- `venue`     — "arXiv:2605.12345", "IEDM 2026", "Nature Electronics 7(5)".
- `venue_url` — direct link to the abstract / PDF / DOI.
- `summary`   — bilingual 3-4 sentences per § Voice above.
- `published` — ISO date.
- `tags`      — optional: ["preprint", "tape-out", "simulation-only"].

## Translation conventions specific to research

In addition to `style-guide.md` § 6, use these for academic writeups:

| English                       | 中文                  |
|-------------------------------|----------------------|
| preprint                      | 预印本                |
| tape-out / test chip          | 流片 / 测试芯片        |
| benchmark                     | 基准测试              |
| ablation study                | 消融实验              |
| compute-in-memory (CIM)       | 存内计算 / 存算一体     |
| ferroelectric                 | 铁电                  |
| chiplet                       | chiplet (保留英文) / 小芯片 |
| backside power delivery       | 背面供电              |
| gate-all-around (GAA)         | 全环绕栅极 (GAA)       |
| spintronic / spin-orbit       | 自旋电子学 / 自旋轨道   |
| photonic integrated circuit   | 光子集成电路 (PIC)     |
| wafer-scale                   | 晶圆级                |
| heterogeneous integration     | 异构集成              |

Author names: keep Latin transliteration on first reference. For Chinese
researchers, if the original paper provides a Chinese name in author notes,
prefer it; otherwise leave the Latin form.

## Common failure modes to flag

- **Cherry-picked benchmark**: paper compares to a 2019 baseline. Note it.
- **Single-cell / single-device demo**: not a manufacturable structure yet.
- **Simulation-only at a new node**: extrapolations from TCAD are weak
  evidence. Mark `["simulation-only"]`.
- **Re-published prior result**: especially common with ferroelectric and
  CIM groups. Cross-check against the group's previous 12 months.

## What the research page is not

- Not a "best papers of the week" rundown — it's a *reading queue* for
  someone who needs to keep up with the field.
- Not a place for hype takes ("paper X solves Y!"). The voice is closer to
  the comments section of a serious paper-reading group than to a press
  release.
- Not a venue for replicating arXiv abstracts. If you can't add signal beyond
  the abstract, drop the paper.
