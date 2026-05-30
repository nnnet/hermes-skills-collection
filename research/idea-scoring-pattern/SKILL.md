---
name: idea-scoring-pattern
description: "Score product ideas: impact x feasibility x moat (Reach-Impact-Confidence-Effort)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Ideation, Scoring, Prioritization, RICE]
    related_skills: [market-research-pattern, landing-copy-pattern]
---

# Idea Scoring — RICE+Moat Pattern

Use after `market-research-pattern` has surfaced pain-points. Converts each
pain into 1-3 candidate solutions and scores them so the founder can pick
the highest-leverage one to validate.

## When to Use

Triggered by: "rank these ideas", "score ideas", "which idea first",
"prioritize", "what should I build first", "RICE this".

## Inputs

- List of pain-points (typically from `findings_*.jsonl` produced by the
  market-research skill) — read via `mcp_filesystem_read_file`.
- Founder constraints: solo? funded? domain expertise? — ask if unclear.

## Scoring Dimensions

### 1. Reach (R) — how many people share this pain (1-10)

- 10 = >100k devs/IT pros worldwide
- 7  = >10k (niche but real)
- 4  = >1k (tiny niche)
- 1  = <100 (probably not a market)

Evidence: subreddit subscriber counts, HN story scores, GitHub stars on
related repos, Google Trends. Cite the data source per dimension.

### 2. Impact (I) — how badly the pain hurts (1-10)

- 10 = blocks paid work daily, willing to pay $$$
- 7  = weekly friction, would pay $20-50/mo
- 4  = mild annoyance, prefers free
- 1  = nice-to-have

Signal: emotion in quoted complaints, presence of existing paid
alternatives, time-spent estimates from Reddit threads.

### 3. Confidence (C) — how sure are we (0-1)

Multiply by Reach*Impact. Penalize if only 1 data source confirms,
boost if Reddit + HN + reviews all converge.

### 4. Effort (E) — weeks to ship v0.1 MVP (low = better)

- 1 wk = CLI wrapper, prompt template, scraper, simple SaaS form
- 4 wk = mid-complexity SaaS, 1-2 integrations
- 12+ = needs DB, auth, infra, ML model training

### 5. Moat (M) — defensibility multiplier (0.5-2.0)

- 2.0 = proprietary data, network effects, hard tech moat
- 1.0 = decent UX advantage, brand
- 0.5 = pure commodity, anyone with API access can copy in a weekend

## Final Score

```
score = (Reach * Impact * Confidence / Effort) * Moat
```

Sort descending. Top-3 go to next stage (`landing-copy-pattern`) for
smoke-test landing pages.

## Output

Write `/opt/data/workspace/scored_ideas_<date>.md`:

```md
# Scored Ideas — <date>

| Rank | Idea | R | I | C | E | M | Score | Pain-Source |
|------|------|---|---|---|---|---|-------|-------------|
| 1    | …    | 8 | 9 | 0.8 | 2 | 1.5 | 43.2 | reddit:.../perma  |

## #1 — <idea-name>
- **Pain**: <copy from findings.jsonl>
- **Solution**: <1 paragraph proposed approach>
- **Why it scores high**: <reach + impact + moat rationale>
- **Risks**: <top-2 risks>
- **MVP scope (2 weeks)**: <concrete deliverable>
…
```

Also store top entries in memory graph with `relation: derived_from` to
the source pain entity. Surface only top-5 to the founder unless asked
for full list.

## Calibration

After each launch cycle, look at which scored ideas actually got traction
and tune your priors. Promote the calibration notes back to memory so the
next scoring pass is sharper.
