# Common DAG Patterns

Reusable shapes for task decomposition. Use these as **templates**, not rigid contracts — adapt names/counts to your goal.

The key property of every pattern below: **maximum parallelism**. Independent work is sibling, not sequential.

## Pattern 1 — Gather → Compare → Decide → Plan → Produce

The most common pattern for research/decision projects (e.g. Lazarevskoe land monetization).

```
[gather_A]   [gather_B]   [gather_C]            ← Wave 1, all parallel
       \         |         /
        \        |        /
         → [compare_options] ←                  ← Wave 2
                  ↓
            [select_one]                        ← Wave 3
              /   |   \
             /    |    \
   [plan_X] [plan_Y] [plan_Z]                   ← Wave 4, all parallel
             \    |    /
              \   |   /
            [final_dossier]                      ← Wave 5
```

**I/O contract:**
- `gather_*` outputs: domain-prefixed (`market_data`, `legal_data`, `pricing_data`)
- `compare_options` inputs: all three datasets, output: `option_scorecard`
- `select_one` input: `option_scorecard`, output: `chosen_strategy`
- `plan_*` inputs: `chosen_strategy` + relevant gather output
- `final_dossier` inputs: all plan outputs

**Pitfalls:**
- Don't make `gather_*` tasks chain — they're independent by definition
- Don't reuse the name `data` across gather tasks — instant edge collision

## Pattern 2 — Map → Reduce

Process a list of N items in parallel, then combine.

```
[list_items]                                    ← Wave 1
     │
     ↓ (item_list)
[process_item_1] ... [process_item_N]           ← Wave 2, parallel (N tasks)
     \      |      /
      \     |     /
      [aggregate_results]                       ← Wave 3
```

**When to use:** indexing, transcription, batch enrichment.

**Caveat:** if N is variable (determined at runtime), use a single `process_items_batch` task with a runtime loop inside. Don't try to template N parallel tasks at decomposition time.

## Pattern 3 — Diamond (Split-Process-Merge)

Single source, multiple transformations, single sink.

```
        [source]
       /   |    \
      ↓    ↓     ↓
[xform_A] [xform_B] [xform_C]                   ← Parallel transformations
      \    |    /
       \   |   /
       [merge]
```

**When to use:** producing multiple representations of the same data (e.g. raw + summary + embedding from one document).

## Pattern 4 — Pipeline with Side Channels

Linear main flow + parallel auxiliary checks that feed into a gate.

```
[fetch] → [normalize] → [validate] → [deploy]
              │                ↑
              ↓                │
        [generate_tests]───────┘
              │
              ↓
        [run_security_scan]────┘
```

**When to use:** build/deploy pipelines, quality gates.

## Pattern 5 — Fan-out / Fan-in with Sub-domains

Top-level split into specialist domains, each domain has its own internal DAG, all converge.

```
                    [scoping]
                  /     |     \
            [legal_*]  [tech_*]  [market_*]     ← Each is its own mini-DAG
                  \     |     /
                    [synthesis]
```

**When to use:** multi-expert reviews, cross-functional analyses.

**Decomposition tip:** decompose each domain as a sub-DAG independently, then prefix all names within a domain (`legal_check_pzz`, `legal_check_vri`) to prevent cross-domain output collisions.

## Anti-pattern: Sequential Degeneration

```
[A] → [B] → [C] → [D] → [E]    ← all in single chain, zero parallelism
```

If your task tree looks like this, you almost certainly decomposed wrong. Real-world projects of meaningful scope ALWAYS have some independent work. Ask:
- Can any pair of consecutive tasks actually run at the same time?
- Did you confuse "logical order of presentation" with "causal dependency"?

## Anti-pattern: Star (One Task → Everything)

```
[source] → all 10 other tasks
```

This isn't wrong per se, but often it means `source` is a mega-task. Check: can `source` itself be split? Frequently `source` is "research the topic" and could be 3-5 parallel research tasks.

## Wave count heuristics

For a goal with reasonable scope:
- 5–10 tasks → expect 3–4 waves
- 10–20 tasks → expect 4–6 waves
- 20+ tasks → expect 5–8 waves

If your wave count equals your task count, you've degenerated into a sequence. Re-decompose.

If you have one wave with the entire graph, you're missing dependencies. Look for tasks that need outputs from other tasks.

## Naming conventions for outputs

To survive `validate_unique_output_names`, use domain prefixes:

| ❌ Bad | ✅ Good |
|---|---|
| `data` | `tourist_demand_data` |
| `result` | `legal_compliance_report` |
| `info` | `competitor_pricing_info` |
| `output` | `transcription_text` |
| `report` | `final_decision_dossier` |

The longer name is worth it — phantom edges from collisions are very hard to debug after the fact.
