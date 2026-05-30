---
name: workflow-templates
description: "Preset Goal+TaskTree+Workflow patterns for common multi-agent scenarios. Use in chief-manager Phase 2 to avoid decomposing from scratch. 5 templates: research pipeline, YouTube indexing, expert ensemble, audit/review, self-evolving monitoring system."
metadata:
  hermes:
    tags: [orchestration, templates, kanban, multi-agent, workflow]
    category: devops
    related_skills: [chief-manager, task-decomposition, workflow-synthesis, failure-recovery, profile-design, workflow-postmortem]
---

# Workflow Templates — preset DAG patterns for chief-manager

When chief-manager reaches **Phase 2** (subgoals → task tree), check this skill
FIRST. If the goal matches one of the 4 templates below, adapt the template
instead of building the DAG from scratch.

**This skill is NOT a replacement for task-decomposition.** Templates provide
starting points; you still adapt names, counts, and I/O to the specific goal.
Always run `validate_tasks_spec` after adapting.

## When to load

- chief-manager Phase 2: "Before decomposing from scratch, check workflow-templates"
- User describes a goal that sounds like one of the 4 patterns below
- You need a quick DAG skeleton to reason about parallelism

## Template selection

```
Goal arrives with subgoals
  │
  ├─ "Research X, compare options, recommend"
  │   └─ → TEMPLATE 1: Research Pipeline
  │
  ├─ "Download/index/transcribe YouTube content"
  │   └─ → TEMPLATE 2: YouTube Indexing Pipeline
  │
  ├─ "Have multiple experts analyze from different angles"
  │   └─ → TEMPLATE 3: Expert Ensemble
  │
  ├─ "Inspect/review/test a codebase or system"
  │   └─ → TEMPLATE 4: Audit / Review
  │
  ├─ "Build autonomous system that monitors data, predicts, logs, and self-improves"
  │   └─ → TEMPLATE 5: Self-Evolving Monitoring System
  │
  └─ No match
      └─ → Use task-decomposition to build from scratch
```

---

## Template 1 — Research Pipeline

**Use when:** Goal is "research a topic, compare alternatives, recommend a decision."

**DAG shape:** Gather → Compare → Decide → Plan → Produce (from task-decomposition patterns.md, Pattern 1)

### Goal template

```json
{
  "statement": "Research {TOPIC} and recommend {DECISION}",
  "success_criteria": [
    "At least 3 alternatives compared with quantitative scoring",
    "Decision justified with evidence from each domain",
    "Actionable plan for the chosen alternative"
  ],
  "out_of_scope": [
    "Implementation of the chosen alternative",
    "Stakeholder buy-in (that's a separate workflow)"
  ],
  "constraints": [],
  "subgoals": [
    {"id": "gather", "description": "Collect data from all relevant domains"},
    {"id": "compare", "description": "Score and compare alternatives"},
    {"id": "decide", "description": "Select best option with justification"},
    {"id": "plan", "description": "Create action plan for chosen option"},
    {"id": "produce", "description": "Assemble final dossier"}
  ]
}
```

### Tasks spec template

```json
[
  {
    "name": "gather_domain_a",
    "description": "Research {TOPIC} from domain A perspective (e.g. market, legal, technical)",
    "outputs": ["domain_a_data"],
    "subgoal_id": "gather"
  },
  {
    "name": "gather_domain_b",
    "description": "Research {TOPIC} from domain B perspective",
    "outputs": ["domain_b_data"],
    "subgoal_id": "gather"
  },
  {
    "name": "gather_domain_c",
    "description": "Research {TOPIC} from domain C perspective",
    "outputs": ["domain_c_data"],
    "subgoal_id": "gather"
  },
  {
    "name": "compare_options",
    "description": "Build decision matrix: score each alternative across all domain dimensions",
    "inputs": ["domain_a_data", "domain_b_data", "domain_c_data"],
    "outputs": ["option_scorecard"],
    "subgoal_id": "compare"
  },
  {
    "name": "select_option",
    "description": "Apply decision criteria to scorecard, select best option, justify",
    "inputs": ["option_scorecard"],
    "outputs": ["chosen_strategy"],
    "subgoal_id": "decide"
  },
  {
    "name": "build_action_plan",
    "description": "Create step-by-step implementation plan for chosen strategy",
    "inputs": ["chosen_strategy"],
    "outputs": ["action_plan"],
    "subgoal_id": "plan"
  },
  {
    "name": "assemble_dossier",
    "description": "Merge all research + comparison + decision + plan into final deliverable",
    "inputs": ["domain_a_data", "domain_b_data", "domain_c_data", "option_scorecard", "chosen_strategy", "action_plan"],
    "outputs": ["final_dossier"],
    "subgoal_id": "produce"
  }
]
```

### Capability hints

| Task | Preferred profile type | Skills needed |
|---|---|---|
| `gather_*` | Domain-specific researcher | web-search, arxiv, industry tools |
| `compare_options` | Analyst / quant | data analysis, scoring |
| `select_option` | Chief or decision-maker | domain expertise |
| `build_action_plan` | Planner | planning, project management |
| `assemble_dossier` | Synthesizer | workflow-synthesis (report pattern) |

### Synthesis pattern

→ **Report synthesis** (workflow-synthesis Pattern 1): merge domain findings into structured report with executive summary, per-domain sections, cross-cutting themes, recommendations.

### Adaptation guide

- **More domains?** Add more `gather_*` tasks (domain_d, domain_e...), update `compare_options` inputs.
- **Fewer domains?** Remove a gather task, update compare inputs.
- **Deeper analysis?** Add sub-tasks under each gather (e.g. `gather_market_demand`, `gather_market_supply` both feeding `domain_market_data`).
- **No decision needed?** Skip `select_option` and `build_action_plan`, go straight to `assemble_dossier`.

---

## Template 2 — YouTube Indexing Pipeline

**Use when:** Goal is "download YouTube content, transcribe, index into knowledge base."

**DAG shape:** Map → Reduce with verification gate (task-decomposition Pattern 2 + Pipeline with Side Channels Pattern 4)

### Goal template

```json
{
  "statement": "Index YouTube playlist {PLAYLIST_URL} into Chroma collection {COLLECTION_NAME}",
  "success_criteria": [
    "All videos from playlist discovered and cataloged",
    "Every video transcribed (whisper medium+ for non-English)",
    "All transcripts indexed into Chroma with domain metadata",
    "Collection count matches expected video count",
    "Spot-check: 3 random queries return relevant results"
  ],
  "out_of_scope": [
    "Video download (audio-only for transcription)",
    "Translation (index in original language)",
    "Content curation or quality filtering"
  ],
  "constraints": [
    "Whisper model: medium minimum for Russian speech",
    "Use yt-dlp-fresh for downloads (auto-updates)",
    "Cookies from Firefox profile for age-gated content"
  ],
  "subgoals": [
    {"id": "discover", "description": "Get complete video list from playlist"},
    {"id": "transcribe", "description": "Transcribe all videos"},
    {"id": "preprocess", "description": "Clean and structure transcripts"},
    {"id": "index", "description": "Index into Chroma with metadata"},
    {"id": "verify", "description": "Verify index integrity and query quality"}
  ]
}
```

### Tasks spec template

```json
[
  {
    "name": "read_playlist",
    "description": "Extract all video IDs, titles, durations from the YouTube playlist URL",
    "outputs": ["video_list"],
    "subgoal_id": "discover"
  },
  {
    "name": "transcribe_videos",
    "description": "Download audio and transcribe each video using Whisper. Output one transcript per video.",
    "inputs": ["video_list"],
    "outputs": ["raw_transcripts"],
    "subgoal_id": "transcribe"
  },
  {
    "name": "preprocess_transcripts",
    "description": "Clean transcripts: remove filler words, fix timestamps, segment by topic, add speaker labels if applicable",
    "inputs": ["raw_transcripts"],
    "outputs": ["clean_transcripts"],
    "subgoal_id": "preprocess"
  },
  {
    "name": "index_to_chroma",
    "description": "Index all clean transcripts into Chroma collection with metadata (video_id, title, duration, domain tags)",
    "inputs": ["clean_transcripts"],
    "outputs": ["chroma_collection_name", "index_count"],
    "subgoal_id": "index"
  },
  {
    "name": "verify_index",
    "description": "Check collection count matches video count, run 3 test queries, verify metadata completeness",
    "inputs": ["chroma_collection_name", "index_count", "video_list"],
    "outputs": ["verification_report"],
    "subgoal_id": "verify"
  }
]
```

### Capability hints

| Task | Preferred profile type | Skills needed |
|---|---|---|
| `read_playlist` | youtube-indexer | youtube-playlist-reader |
| `transcribe_videos` | youtube-indexer | video-preprocessor (yt-dlp + whisper) |
| `preprocess_transcripts` | youtube-indexer | video-preprocessor (text cleaning) |
| `index_to_chroma` | youtube-indexer | video-to-knowledge-base, chroma MCP |
| `verify_index` | chief or reviewer | chroma MCP (query, count) |

### Synthesis pattern

→ **Structured handoff** (workflow-synthesis Pattern 4): collection name + count + verification report + sample queries.

### Adaptation guide

- **Single video, not playlist?** Replace `read_playlist` with a task that takes a single URL as external input. Skip to `transcribe_videos`.
- **Multiple playlists?** Add parallel `read_playlist_*` tasks, merge into one `video_list`.
- **Need translation?** Add `translate_transcripts` task between preprocess and index.
- **Need summarization?** Add `summarize_transcripts` task in parallel with indexing.
- **For batch processing (>50 videos):** Use `kanban_heartbeat` during transcription. Set `max_runtime_seconds` generously (300+ per video on CPU).

### Pitfalls

- **Whisper base fails on Russian math speech.** Always use `medium` or larger.
- **~37 seconds per minute of audio on CPU.** Budget time accordingly.
- **Age-gated videos need cookies.** Use `--cookies-from-browser firefox:/opt/firefox-profile`.
- **Test 1 video before batch.** Verify the full pipeline works before committing to 100+ videos.

---

## Template 3 — Expert Ensemble

**Use when:** Goal requires analysis from multiple domain experts, each examining the same subject from a different angle.

**DAG shape:** Fan-out / Fan-in with Sub-domains (task-decomposition Pattern 5)

### Goal template

```json
{
  "statement": "Analyze {SUBJECT} from N expert perspectives and synthesize",
  "success_criteria": [
    "Each expert produces a domain-specific analysis report",
    "Cross-cutting themes identified across all domains",
    "Synthesized recommendation with consensus and disagreements",
    "Decision matrix if applicable (scored alternatives)"
  ],
  "out_of_scope": [
    "Implementation of recommendations",
    "Domain-specific deep dives beyond the scope of {SUBJECT}"
  ],
  "constraints": [],
  "subgoals": [
    {"id": "expert_analysis", "description": "Each domain expert analyzes {SUBJECT} independently"},
    {"id": "synthesis", "description": "Combine all expert analyses into unified output"},
    {"id": "delivery", "description": "Format and deliver final product"}
  ]
}
```

### Tasks spec template (3 experts)

```json
[
  {
    "name": "expert_quant_analysis",
    "description": "Analyze {SUBJECT} from quantitative/financial perspective: metrics, risk, return, volatility",
    "outputs": ["quant_analysis"],
    "subgoal_id": "expert_analysis"
  },
  {
    "name": "expert_tech_analysis",
    "description": "Analyze {SUBJECT} from technical/engineering perspective: feasibility, architecture, complexity",
    "outputs": ["tech_analysis"],
    "subgoal_id": "expert_analysis"
  },
  {
    "name": "expert_market_analysis",
    "description": "Analyze {SUBJECT} from market/demand perspective: competition, demand, positioning",
    "outputs": ["market_analysis"],
    "subgoal_id": "expert_analysis"
  },
  {
    "name": "synthesize_expert_outputs",
    "description": "Merge all expert analyses: deduplicate, resolve contradictions, identify cross-cutting themes",
    "inputs": ["quant_analysis", "tech_analysis", "market_analysis"],
    "outputs": ["synthesis_report"],
    "subgoal_id": "synthesis"
  },
  {
    "name": "build_decision_matrix",
    "description": "If alternatives exist: score each option across expert dimensions, compute weighted scores",
    "inputs": ["quant_analysis", "tech_analysis", "market_analysis"],
    "outputs": ["decision_matrix"],
    "subgoal_id": "synthesis"
  },
  {
    "name": "format_deliverable",
    "description": "Assemble final product: executive summary + per-expert sections + synthesis + decision matrix + recommendations",
    "inputs": ["synthesis_report", "decision_matrix"],
    "outputs": ["final_deliverable"],
    "subgoal_id": "delivery"
  }
]
```

### Capability hints

| Task | Preferred profile | Skills needed |
|---|---|---|
| `expert_quant_*` | quant-finance-expert | Domain: quant finance |
| `expert_tech_*` | python-engineer or ml-expert | Domain: engineering |
| `expert_market_*` | researcher or econometrics-expert | Domain: market analysis |
| `synthesize_*` | Chief (or dedicated synthesizer) | workflow-synthesis |
| `build_decision_matrix` | Chief or analyst | workflow-synthesis (decision matrix pattern) |
| `format_deliverable` | Chief or writer | workflow-synthesis (report pattern) |

### Synthesis pattern

→ **Decision matrix** (workflow-synthesis Pattern 3) if alternatives exist.
→ **Report synthesis** (workflow-synthesis Pattern 1) if single-subject analysis.

### Adaptation guide

- **More experts?** Add more `expert_*` tasks, update `synthesize_expert_outputs` inputs.
- **2 experts instead of 3?** Remove one, update inputs. Still works.
- **No decision matrix needed?** Skip `build_decision_matrix`, feed `synthesis_report` directly to `format_deliverable`.
- **Experts need shared data?** Add a `prepare_data` task before expert fan-out. All experts take `prepared_data` as additional input.
- **Experts need to talk to each other?** That's not an ensemble — that's a discussion. Use sequential tasks with feedback loops instead.

### Pitfalls

- **Don't let experts overlap.** Each expert's SOUL.md must define clear domain boundaries. "Quantitative analysis" and "financial analysis" can collide — be specific.
- **Don't average scores blindly.** A 5 from a risk expert means "low risk"; a 5 from a cost expert means "high cost" — opposite semantics. Always label what scores mean.
- **Synthesis is not concatenation.** The synthesizer MUST restructure, deduplicate, and resolve contradictions.

---

## Template 4 — Audit / Review

**Use when:** Goal is to inspect a codebase, system, or process and produce findings + recommendations.

**DAG shape:** Pipeline with Side Channels (task-decomposition Pattern 4)

### Goal template

```json
{
  "statement": "Audit {TARGET} and produce findings with prioritized recommendations",
  "success_criteria": [
    "All critical issues found and categorized by severity",
    "Each finding has evidence (file paths, logs, metrics)",
    "Recommendations prioritized by impact × effort",
    "Executive summary suitable for non-technical stakeholder"
  ],
  "out_of_scope": [
    "Fixing the issues (separate workflow)",
    "Performance benchmarking under load"
  ],
  "constraints": [],
  "subgoals": [
    {"id": "inspect", "description": "Run automated checks and manual inspection"},
    {"id": "categorize", "description": "Classify findings by severity and type"},
    {"id": "recommend", "description": "Prioritize and recommend remediation"},
    {"id": "report", "description": "Produce final audit report"}
  ]
}
```

### Tasks spec template

```json
[
  {
    "name": "static_analysis",
    "description": "Run linters, type checkers, dependency scanners on {TARGET}",
    "outputs": ["static_findings"],
    "subgoal_id": "inspect"
  },
  {
    "name": "security_scan",
    "description": "Check for known vulnerabilities, secrets, unsafe patterns",
    "outputs": ["security_findings"],
    "subgoal_id": "inspect"
  },
  {
    "name": "architecture_review",
    "description": "Review project structure, dependency graph, separation of concerns",
    "outputs": ["architecture_findings"],
    "subgoal_id": "inspect"
  },
  {
    "name": "test_coverage_check",
    "description": "Measure test coverage, identify untested critical paths",
    "outputs": ["coverage_findings"],
    "subgoal_id": "inspect"
  },
  {
    "name": "categorize_findings",
    "description": "Merge all findings, deduplicate, assign severity (critical/high/medium/low), group by type",
    "inputs": ["static_findings", "security_findings", "architecture_findings", "coverage_findings"],
    "outputs": ["categorized_findings"],
    "subgoal_id": "categorize"
  },
  {
    "name": "prioritize_recommendations",
    "description": "For each finding: estimate remediation effort, compute priority = severity × impact / effort",
    "inputs": ["categorized_findings"],
    "outputs": ["prioritized_recommendations"],
    "subgoal_id": "recommend"
  },
  {
    "name": "produce_audit_report",
    "description": "Assemble: executive summary + per-category findings + prioritized recommendations + appendix",
    "inputs": ["categorized_findings", "prioritized_recommendations"],
    "outputs": ["audit_report"],
    "subgoal_id": "report"
  }
]
```

### Capability hints

| Task | Preferred profile | Skills needed |
|---|---|---|
| `static_analysis` | python-engineer | Linters, type checkers in terminal |
| `security_scan` | python-engineer or security-expert | Security scanning tools |
| `architecture_review` | python-engineer or codebase-inspector | codebase-inspection skill |
| `test_coverage_check` | python-engineer | pytest, coverage tools |
| `categorize_findings` | Chief or reviewer | Analysis, deduplication |
| `prioritize_recommendations` | Chief or product-minded analyst | Effort estimation |
| `produce_audit_report` | Chief or writer | workflow-synthesis (report pattern) |

### Synthesis pattern

→ **Report synthesis** (workflow-synthesis Pattern 1): structured audit report with severity-sorted findings and prioritized recommendations.

### Adaptation guide

- **Not a codebase?** Replace inspection tasks: for a process audit, use `interview_stakeholders`, `observe_workflow`, `review_documentation` instead of `static_analysis`, `security_scan`, etc.
- **Quick audit?** Merge the 4 inspection tasks into 2: `automated_checks` (linter+security+coverage) and `manual_review` (architecture+design).
- **Compliance audit?** Add `compliance_check` task with specific regulatory requirements as inputs (external).
- **Security-only audit?** Drop `architecture_review` and `test_coverage_check`, expand `security_scan` into multiple sub-scans.

---

## Template 5 — Self-Evolving Monitoring System

**Use when:** Goal is "build an autonomous system that continuously monitors a data source, runs analysis/predictions, logs findings to an external artifact (Sheet, DB, dashboard), tracks outcomes, and self-improves over time." Key verb: the system must EVOLVE — not just report once.

**DAG shape:** Cyclical — Scanner → Analyzer → Journal → Tracker → Evolution Engine (feeds back to Analyzer)

### Goal template

```json
{
  "statement": "Build an autonomous system that monitors {DATA_SOURCE}, predicts {OUTCOME_TYPE}, logs to {OUTPUT_ARTIFACT}, and improves over time",
  "success_criteria": [
    "Real data from {DATA_SOURCE} API (no fabricated IDs)",
    "At least {N} prediction entries in {OUTPUT_ARTIFACT} within first week",
    "Each entry has full justification: model estimate vs observed, edge calculation, reasoning",
    "Outcome tracking: for closed events, record actual outcome and P&L",
    "Evolution metrics: weekly aggregates showing hit rate, edge, coverage trajectory",
    "Cron automation: new signals appear in {OUTPUT_ARTIFACT} without human input"
  ],
  "out_of_scope": [
    "Real-money execution (paper/simulation only)",
    "Manual data entry or human-triggered analysis"
  ],
  "constraints": [],
  "subgoals": [
    {"id": "scan", "description": "Continuously fetch and filter candidates from {DATA_SOURCE}"},
    {"id": "predict", "description": "Run prediction ensemble to estimate true probabilities"},
    {"id": "journal", "description": "Log signals with full justification to {OUTPUT_ARTIFACT}"},
    {"id": "track", "description": "Monitor outcomes: price drift, resolution, P&L"},
    {"id": "evolve", "description": "Weekly: aggregate metrics, adjust parameters, expand coverage"}
  ]
}
```

### Tasks spec template

```json
[
  {
    "name": "build_scanner",
    "description": "Fetch active markets/events from {DATA_SOURCE} API. Filter by volume, liquidity, time-to-close. Categorize by domain. Output structured candidate list.",
    "outputs": ["scanner_script", "candidate_list"],
    "subgoal_id": "scan"
  },
  {
    "name": "build_prediction_engine",
    "description": "Multi-strategy prediction ensemble: Strategy A (LLM analysis with web context), Strategy B (base rates from historical data), Strategy C (microstructure/momentum signals). Weighted average → final probability.",
    "outputs": ["prediction_engine"],
    "subgoal_id": "predict"
  },
  {
    "name": "build_signal_generator",
    "description": "Edge detection (model_prob vs market_price), threshold filtering, position sizing (fractional Kelly on paper bankroll). Max single position cap.",
    "outputs": ["signal_generator"],
    "subgoal_id": "predict"
  },
  {
    "name": "setup_output_artifact",
    "description": "Create/configure {OUTPUT_ARTIFACT} (Google Sheet, DB, etc.) with proper schema: trade entries, weekly metrics, category coverage. Share with operator.",
    "outputs": ["artifact_id", "artifact_url"],
    "subgoal_id": "journal"
  },
  {
    "name": "build_journal_writer",
    "description": "Append new signals to {OUTPUT_ARTIFACT} with all required fields: ID, timestamp, target, model estimate, market price, edge, reasoning, position size.",
    "inputs": ["signal_generator", "artifact_id"],
    "outputs": ["journal_writer"],
    "subgoal_id": "journal"
  },
  {
    "name": "build_price_tracker",
    "description": "For open positions: periodically check current price, compute drift from entry. Update {OUTPUT_ARTIFACT} with drift data.",
    "inputs": ["artifact_id"],
    "outputs": ["price_tracker"],
    "subgoal_id": "track"
  },
  {
    "name": "build_outcome_resolver",
    "description": "When events close: fetch final outcome, compute paper P&L, update {OUTPUT_ARTIFACT}. Mark resolved.",
    "inputs": ["artifact_id"],
    "outputs": ["outcome_resolver"],
    "subgoal_id": "track"
  },
  {
    "name": "build_evolution_engine",
    "description": "Weekly aggregation: hit rate, avg edge, total P&L, markets covered. Parameter adjustment: if hit rate < threshold → tighten filters; if > threshold → loosen. Log all changes. Track per-strategy performance → adjust ensemble weights.",
    "inputs": ["artifact_id", "prediction_engine"],
    "outputs": ["evolution_engine"],
    "subgoal_id": "evolve"
  },
  {
    "name": "setup_cron_automation",
    "description": "Cron jobs: (1) signal scanner every N minutes, (2) price drift updater every M hours, (3) outcome resolver every H hours, (4) weekly evolution on Sunday. All self-contained — no human trigger needed.",
    "inputs": ["scanner_script", "journal_writer", "price_tracker", "outcome_resolver", "evolution_engine"],
    "outputs": ["cron_jobs"],
    "subgoal_id": "evolve"
  },
  {
    "name": "first_live_run",
    "description": "Execute scanner + prediction on real data. Write first N entries to {OUTPUT_ARTIFACT}. Verify entries are correct and visible.",
    "inputs": ["scanner_script", "prediction_engine", "journal_writer"],
    "outputs": ["first_entries"],
    "subgoal_id": "journal"
  }
]
```

### Capability hints

| Task | Preferred profile | Skills needed |
|---|---|---|
| `build_scanner` | python-engineer | Domain API knowledge |
| `build_prediction_engine` | ml-engineer or researcher | LLM prompting, statistics |
| `build_signal_generator` | quant or python-engineer | Kelly criterion, risk mgmt |
| `setup_output_artifact` | python-engineer | google-workspace or DB setup |
| `build_journal_writer` | python-engineer | google-workspace (Sheets append) |
| `build_price_tracker` | python-engineer | API polling, cron |
| `build_outcome_resolver` | python-engineer | API polling, data matching |
| `build_evolution_engine` | ml-engineer or chief | Metrics aggregation, parameter tuning |
| `setup_cron_automation` | python-engineer | Hermes cronjob tool |
| `first_live_run` | Chief (orchestrates end-to-end test) | All of the above |

### Synthesis pattern

→ **Dashboard synthesis** (not report): the output artifact IS the deliverable — a living Sheet/DB/dash that the operator monitors. No separate report needed.

### Adaptation guide

- **Different data source?** Replace `build_scanner` with domain-specific API client. Pattern holds for crypto signals, weather alerts, e-commerce price monitoring, sports betting, job market tracking.
- **Different output?** Replace Google Sheet with Notion database, Airtable, custom dashboard, or Chroma collection. Journal writer adapts.
- **More strategies?** Add `build_strategy_D` task, update `build_prediction_engine` inputs.
- **No evolution needed?** Remove `build_evolution_engine` and `setup_cron_automation` — becomes a static analysis pipeline (but then use Template 1 or 4 instead).
- **Real execution later?** Add `build_executor` task (after paper validation) and `build_risk_manager` task. Gate executor behind evolution metrics threshold.

### Pitfalls

- **"LLM anchoring"** — LLMs tend to agree with market prices (anchoring bias). Force contrarian analysis: explicitly ask "what would make the market WRONG?" before estimating probability.
- **Google Sheets rate limits** — batch append operations; don't call Sheets API per-market. Max ~60 writes/min before hitting 429s.
- **Kelly is aggressive** — full Kelly on small bankrolls causes ruin. Always use fractional Kelly (25-50%) and cap single positions at 5-10% of bankroll.
- **Cron sessions are isolated** — each cron run has no memory of the previous. All state must live in the output artifact or a persistent config file. Don't rely on agent memory.
- **Market resolution lag** — some events don't close cleanly (ambiguous outcomes, delayed resolution). Build a "disputed/pending" state, don't assume binary resolved/not-resolved.
- **Thin markets lie** — low-volume markets have wide spreads and unreliable prices. Filter aggressively on volume/liquidity before analysis.
- **Set up output artifact BEFORE spawning chief.** Create the Sheet/DB, configure schema, share permissions, pass artifact ID in chief brief. If the chief must create the artifact, it often gets permission wrong or structural misalignment with the brief.

### Cron structure (reference)

| Job | Frequency | Purpose |
|---|---|---|
| Signal Scanner | Every 30 min | Scan → predict → journal new signals |
| Price Tracker | Every 4 hours | Update drift for open positions |
| Outcome Resolver | Every 6 hours | Check closures, record P&L |
| Evolution Engine | Weekly (Sunday) | Aggregate metrics, adjust params |

---

## How to use a template

1. **Identify the matching template** (selection tree above)
2. **Copy the Goal template** → adapt statement, criteria, constraints to your specifics
3. **Copy the Tasks spec** → rename tasks/outputs to your domain, add/remove tasks
4. **Run `validate_tasks_spec`** → templates are pre-validated but your edits may break things
5. **Build via chief Phase 3-4** → edges are inferred automatically from I/O matching
6. **Assign profiles** using capability hints as guidance

```python
# After adapting template:
from validator import validate_tasks_spec
errors = validate_tasks_spec(adapted_tasks_spec, adapted_goal_dict)
if errors:
    fix_errors_and_retry()
# Then: chief.build_task_tree → chief.build_plan → capability matrix
```

## Template composition

Templates can be **nested** — use one template as a subtask of another:

```
[main-goal]
  ├── [research-pipeline: investigate X]  ← Template 1
  ├── [expert-ensemble: evaluate X]       ← Template 3
  └── [synthesize: combine research + evaluation]
```

## Anti-patterns

- **"Template as gospel"** — templates are starting points, not contracts. ALWAYS adapt to specifics.
- **"Skip validation because template is pre-validated"** — your edits may have broken I/O contracts. Always re-validate.
- **"Force-fit a goal into a template"** — if none of the 4 match, use task-decomposition from scratch. Bad template fit is worse than no template.
- **"Copy template names verbatim"** — `gather_domain_a` is a placeholder, not a task name. Rename to your domain.
- **"Template = no thinking"** — templates save decomposition time, not thinking time. You still need to understand the goal, identify domains, and choose profiles.

## Relationship to other skills

| Skill | What it does | When to load |
|---|---|---|
| `workflow-templates` | **this skill** — preset DAG patterns | chief-manager Phase 2, before decomposing |
| `chief-manager` | Orchestrator protocol | Calls this skill in Phase 2 |
| `task-decomposition` | Build DAG from scratch | When no template matches |
| `workflow-synthesis` | Combine agent outputs | After template's tasks complete |
| `failure-recovery` | Handle failures during execution | If a template task fails |
| `profile-design` | Create profiles for template roles | If template needs a new profile |

## Files

- This skill: `/opt/data/skills/devops/workflow-templates/SKILL.md`
- Related DAG patterns: `/opt/data/skills/devops/task-decomposition/references/patterns.md`
- Polymarket / prediction market API reference: `references/prediction-market-apis.md` — Gamma API endpoints, CLOB API, market categories, filtering thresholds. Useful context when building Template 5 for prediction markets.
