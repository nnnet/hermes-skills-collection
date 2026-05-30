---
name: workflow-synthesis
description: "Combine outputs from multiple subagents into a unified deliverable. Patterns: report assembly, Chroma collection indexing, decision matrix, structured handoff. Load when all parallel tasks complete and chief needs to synthesize results."
metadata:
  hermes:
    tags: [orchestration, synthesis, multi-agent, workflow, output-combination]
    category: devops
    related_skills: [chief-manager, profile-design, failure-recovery, workflow-templates]
---

# Workflow Synthesis — combining multi-agent outputs

When chief-manager dispatches parallel tasks and all complete, this skill
decides **how to combine** their outputs into a single deliverable.

## When to load this skill

- All parallel kanban tasks are `done` → need to combine results
- Multiple expert agents produced independent outputs → merge into one
- Research pipeline completed → need to assemble final report
- Audit finished → need structured handoff with findings

## Synthesis strategy selection

```
Outputs collected from N agents
  │
  ├─ All outputs are data artifacts (files, collections, DBs)?
  │   └─ → INDEX PATTERN (Chroma collection / directory assembly)
  │
  ├─ Outputs are text/analysis from different domains?
  │   └─ → REPORT PATTERN (merge sections, deduplicate, structure)
  │
  ├─ Outputs are evaluations/scores from multiple experts?
  │   └─ → DECISION MATRIX PATTERN (score aggregation, consensus)
  │
  ├─ Output goes to another agent or kanban task?
  │   └─ → STRUCTURED HANDOFF PATTERN (metadata + summary)
  │
  └─ Mixed outputs (some data, some text)?
      └─ → STAGED PATTERN (index data first, then report on indexed data)
```

## Pattern 1 — Report synthesis

**Use when:** Multiple agents analyzed different aspects of the same topic.

**Steps:**
1. Collect all agent summaries (from `kanban_show` metadata or workspace files)
2. Identify overlapping findings → deduplicate
3. Identify contradictions → flag for human or resolve via evidence
4. Structure into unified outline:
   - Executive summary (1-2 paragraphs)
   - Per-domain findings (each agent's contribution)
   - Cross-cutting themes (patterns that span agents)
   - Recommendations (synthesized from all agents)
   - Appendix (raw agent outputs, if needed)

**Anti-pattern:** Concatenating outputs verbatim. The synthesis MUST add value — restructure, deduplicate, resolve contradictions.

**Example:**
```
Agent 1 (quant): "Volatility clustering in returns"
Agent 2 (econometrics): "GARCH(1,1) fits well"
Agent 3 (ML): "LSTM outperforms GARCH on test set"

Synthesis: "Returns exhibit volatility clustering (quant). 
GARCH(1,1) provides a good baseline fit (econometrics), 
but LSTM models achieve superior out-of-sample performance (ML). 
Recommendation: Use GARCH for interpretability, LSTM for prediction."
```

## Pattern 2 — Chroma collection indexing

**Use when:** Agents produced documents, transcripts, or structured data that should be searchable.

**Steps:**
1. Identify target collection (create if needed via `chroma_create_collection`)
2. For each agent's output:
   - If already indexed → verify with `chroma_get_collection_count`
   - If raw documents → index via `chroma_add_documents`
3. Cross-reference: add metadata linking each doc to its source agent
4. Verify final count matches expected total
5. Test with `chroma_query_documents` — query should find content from all agents

**Metadata convention:**
```json
{
  "source_agent": "<profile-name>",
  "task_id": "<kanban-task-id>",
  "domain": "<agent's domain>",
  "indexed_at": "<ISO timestamp>"
}
```

**Anti-pattern:** Indexing without verification. Always check count after batch add.

## Pattern 3 — Decision matrix

**Use when:** Multiple experts evaluated the same options from different angles.

**Steps:**
1. Extract each agent's evaluation (scores, rankings, or qualitative assessments)
2. Normalize to common scale (e.g., 1-5 or Low/Medium/High)
3. Build decision matrix:

```
Option    | Agent1 (cost) | Agent2 (risk) | Agent3 (feasibility) | Weighted
----------|---------------|---------------|----------------------|--------
Option A  |      4        |      2        |         5            |   3.7
Option B  |      3        |      4        |         3            |   3.3
Option C  |      5        |      1        |         2            |   2.7
```

4. If weights are defined → compute weighted score
5. If no weights → present unweighted with recommendation to define weights
6. Flag: if agents disagree significantly (>2 points spread) → highlight for human review

**Anti-pattern:** Averaging without context. A 5 from a risk expert means "low risk"; a 5 from a cost expert means "high cost" — these are opposite! Always label what the score means.

## Pattern 4 — Structured handoff

**Use when:** Output goes to another agent, kanban task, or downstream system.

**Steps:**
1. For each agent's output, extract:
   - `summary`: 1-2 sentence human-readable description
   - `metadata`: machine-readable facts (changed_files, tests_run, findings, etc.)
   - `artifacts`: paths to files, collection names, DB records
2. Combine into unified handoff:

```json
{
  "synthesis_summary": "3 agents completed: quant analysis, econometric modeling, ML evaluation",
  "agents": [
    {"profile": "quant-finance-expert", "task_id": "T-123", "summary": "...", "artifacts": [...]},
    {"profile": "econometrics-expert", "task_id": "T-124", "summary": "...", "artifacts": [...]},
    {"profile": "ml-expert", "task_id": "T-125", "summary": "...", "artifacts": [...]}
  ],
  "cross_cutting_findings": ["...", "..."],
  "recommendations": ["...", "..."]
}
```

3. Post to kanban as comment or deliver to user

**Anti-pattern:** Dumping raw agent outputs into the handoff. The downstream consumer needs the synthesis, not the raw data.

## Pattern 5 — Staged synthesis

**Use when:** Mixed outputs — some agents produced data, others produced analysis.

**Steps:**
1. **Stage 1:** Index data artifacts (Pattern 2)
2. **Stage 2:** Report synthesis (Pattern 1) — reference indexed collections
3. **Stage 3:** Structured handoff (Pattern 4) — combine both

**Example:**
```
Stage 1: youtube-indexer indexed 50 transcripts → Chroma
Stage 2: research-agent analyzed patterns across transcripts
Stage 3: Handoff includes Chroma collection name + analysis report
```

## Quality gates

Before delivering synthesis:

- [ ] All expected agent outputs collected (no missing tasks)
- [ ] Contradictions identified and resolved or flagged
- [ ] Deduplication performed (no repeated findings)
- [ ] Output format matches downstream expectation (report / collection / matrix / handoff)
- [ ] Machine-readable metadata included (for downstream automation)

## Anti-patterns

- **"Concatenation is synthesis"** — just joining outputs verbatim. Synthesis MUST restructure.
- **"Ignore contradictions"** — agents disagree → must resolve or flag. Don't hide disagreements.
- **"No verification"** — indexing without count check, report without reading it.
- **"One-size-fits-all"** — different output types need different patterns. Match strategy to output.
- **"Skip the summary"** — downstream consumers need the TL;DR, not the raw data.

## Relationship to other skills

| Skill | What it does | When to load |
|---|---|---|
| `workflow-synthesis` | **this skill** — combine agent outputs | All parallel tasks done, need to merge |
| `chief-manager` | Dispatches tasks, monitors completion | Before synthesis (dispatch phase) |
| `failure-recovery` | Handles agent failures | If an agent failed, recover before synthesizing |
| `profile-design` | Creates profiles for new roles | If synthesis reveals missing capability |

## Files

- This skill: `/opt/data/skills/devops/workflow-synthesis/SKILL.md`
- Related: `/opt/data/skills/devops/chief-manager/SKILL.md`
