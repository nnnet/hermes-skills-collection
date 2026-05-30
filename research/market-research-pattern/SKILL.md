---
name: market-research-pattern
description: "4-source pattern for discovering unmet developer/IT pain-points."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Research, Market, PainPoints, DevTools, Discovery]
    related_skills: [arxiv, blogwatcher]
---

# Market Research — 4-Source Pain-Point Pattern

Use this when asked to "find market needs", "discover inefficiencies", "what
do users complain about", "validate a problem space", or any pain-point
hunting task. Produces a structured ranked list of complaints with sources.

## Inputs

- `topic` — narrow domain (e.g. "k8s observability", "git workflow", "CI/CD slowness")
- `target_persona` — who feels the pain (e.g. "platform engineer", "indie dev")
- `n_findings` (default 5) — how many top pains to surface

## Required Tools

- `mcp_fetch_fetch` — HTTP GET for JSON APIs and HTML pages
- `mcp_playwright_browser_*` — render JS-heavy pages (G2, Capterra reviews)
- `mcp_filesystem_write_file` — persist findings to `/opt/data/workspace/`
- `mcp_memory_*` — store entities/relations for cross-session reuse

## Pattern: 4 Parallel Sources

### 1. Reddit harvest (free, no auth)

```
GET https://www.reddit.com/r/<sub>/top.json?t=month&limit=50
```

Subreddits by persona:
- Devs: `programming`, `ExperiencedDevs`, `webdev`, `learnprogramming`
- DevOps/IT: `devops`, `sysadmin`, `kubernetes`, `homelab`
- AI/ML: `MachineLearning`, `LocalLLaMA`, `LangChain`

Keep posts where `title` OR top comment contains: `frustrating, painful,
terrible, broken, hate, waste, nightmare, doesn't work, why is, anyone
else`. Capture: title, score, num_comments, permalink, top-1 quoted excerpt.

### 2. Hacker News (Algolia API, free)

```
GET https://hn.algolia.com/api/v1/search?query=<topic>&tags=story&numericFilters=points>30,num_comments>50
```

For each story, also fetch comments:
```
GET https://hn.algolia.com/api/v1/items/<objectID>
```

Mine comments with high-rating ratio for complaint-pattern phrases.

### 3. Product reviews (Playwright)

```
mcp_playwright_browser_navigate("https://www.g2.com/products/<slug>/reviews?filters[rating][]=1&filters[rating][]=2")
mcp_playwright_browser_snapshot()
```

Same for Capterra, TrustRadius. Filter to 1-2 star reviews. Pattern of
phrases: "doesn't work when…", "impossible to…", "missing…", "wish it could…".

### 4. GitHub WONTFIX / closed-no-merge (signal of unmet need)

```
GET https://api.github.com/search/issues?q=repo:<owner>/<repo>+is:closed+is:issue+label:wontfix
```

Popular dev-tools repos: `microsoft/vscode`, `kubernetes/kubernetes`,
`docker/cli`, `prometheus/prometheus`, `grafana/grafana`. A closed
"won't-do" with many `+1` reactions = strong unmet-need signal.

## Output Schema

For each finding, emit JSON to `/opt/data/workspace/findings_<date>.jsonl`:

```json
{
  "pain": "1-sentence summary of the user pain",
  "quote": "verbatim user quote (<= 240 chars)",
  "source": "https://...",
  "persona": "platform-engineer | indie-dev | ml-eng | ...",
  "frequency_signal": "high|med|low",
  "frequency_evidence": "e.g. 12 reddit threads in 90 days, 240 HN comments",
  "captured_at": "ISO-8601"
}
```

Also persist to memory graph via `mcp_memory_create_entities` so future
sessions can build on prior findings. Entity name = short pain slug, type
= `pain_point`, observations = quote + source + persona.

## Final Step

Rank top `n_findings` by frequency × specificity × actionability and
produce a markdown summary at `/opt/data/workspace/research_<topic>_<date>.md`
ready for next stage (idea-scoring-pattern).
