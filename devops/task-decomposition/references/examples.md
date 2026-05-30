# Worked Examples

Three complete decompositions showing the full Goal → tasks_spec contract. Use as references for the producer side of the prompt.

## Example 1 — Index YouTube playlist into Chroma

### Goal (input)

```json
{
  "statement": "Index 50+ CMF YouTube videos into Chroma with domain-tagged metadata",
  "success_criteria": [
    "Every video has a Chroma doc",
    "Each doc has source URL + author + duration + domain tag",
    "Russian speech transcribed at >= medium Whisper model"
  ],
  "constraints": ["Russian content", "math-heavy speech"],
  "out_of_scope": ["Translation", "Summarization"],
  "subgoals": [
    {"id": "ingest", "description": "Fetch the raw videos"},
    {"id": "process", "description": "Transcribe and clean"},
    {"id": "index", "description": "Store into knowledge base"},
    {"id": "verify", "description": "Quality gate"}
  ]
}
```

### tasks_spec (output, 5 tasks, 3 waves)

```json
{
  "tasks": [
    {
      "name": "list_videos",
      "description": "Enumerate all video IDs and basic metadata from the CMF playlist",
      "subgoal_id": "ingest",
      "inputs": [{"name": "playlist_url", "type": "external", "description": "CMF playlist URL"}],
      "outputs": [{"name": "video_list", "type": "any", "description": "List of {id, title, duration}"}]
    },
    {
      "name": "download_and_transcribe",
      "description": "Fetch audio and produce Russian transcripts using a >= medium model",
      "subgoal_id": "process",
      "inputs": [{"name": "video_list", "type": "any"}],
      "outputs": [{"name": "raw_transcripts", "type": "any", "description": "{video_id: text}"}]
    },
    {
      "name": "clean_and_tag",
      "description": "Strip filler artifacts and add per-video domain tags for filtering",
      "subgoal_id": "process",
      "inputs": [{"name": "raw_transcripts", "type": "any"}],
      "outputs": [{"name": "clean_docs", "type": "any", "description": "Cleaned + tagged docs"}]
    },
    {
      "name": "index_chroma",
      "description": "Upsert clean docs into the cmf_videos Chroma collection with metadata",
      "subgoal_id": "index",
      "inputs": [{"name": "clean_docs", "type": "any"}],
      "outputs": [{"name": "indexed_count", "type": "any", "description": "Number of docs upserted"}]
    },
    {
      "name": "verify_count",
      "description": "Assert that indexed_count equals video_list length; produce delta report",
      "subgoal_id": "verify",
      "inputs": [
        {"name": "video_list", "type": "any"},
        {"name": "indexed_count", "type": "any"}
      ],
      "outputs": [{"name": "verification_report", "type": "any"}]
    }
  ]
}
```

### Resulting waves

```
Wave 1: list_videos
Wave 2: download_and_transcribe
Wave 3: clean_and_tag
Wave 4: index_chroma
Wave 5: verify_count
```

Note: this is mostly sequential because each step truly depends on the prior one. Don't force parallelism where it doesn't exist. `verify_count` consumes outputs from two different waves, demonstrating multi-parent edges.

## Example 2 — Land monetization research (Lazarevskoe)

### Goal (input, trimmed)

```json
{
  "statement": "Pick a monetization strategy for 12-sotka ИЖС plot in Lazarevskoe, <= 24 month exit, ROI >= 2x CB key rate, fully legal, hands-off",
  "subgoals": [
    {"id": "context", "description": "Establish legal + market context"},
    {"id": "options", "description": "Characterize candidate strategies"},
    {"id": "decision", "description": "Compare and select"},
    {"id": "plan", "description": "Detail the chosen strategy"}
  ]
}
```

### tasks_spec (illustrative — Pattern 1: Gather → Compare → Decide → Plan)

```json
{
  "tasks": [
    {
      "name": "check_pzz_rules",
      "description": "Determine current zoning rules and permitted uses for the parcel",
      "subgoal_id": "context",
      "inputs": [{"name": "parcel_address", "type": "external"}],
      "outputs": [{"name": "zoning_rules", "type": "any"}]
    },
    {
      "name": "research_rental_market",
      "description": "Collect short-term and long-term rental price ranges in Lazarevskoe",
      "subgoal_id": "context",
      "inputs": [{"name": "parcel_address", "type": "external"}],
      "outputs": [{"name": "rental_market_data", "type": "any"}]
    },
    {
      "name": "research_sale_market",
      "description": "Collect comparable sale prices for plots and houses in the area",
      "subgoal_id": "context",
      "inputs": [{"name": "parcel_address", "type": "external"}],
      "outputs": [{"name": "sale_market_data", "type": "any"}]
    },
    {
      "name": "option_guesthouse",
      "description": "Characterize the guesthouse monetization option with bounds on cost and revenue",
      "subgoal_id": "options",
      "inputs": [
        {"name": "zoning_rules", "type": "any"},
        {"name": "rental_market_data", "type": "any"}
      ],
      "outputs": [{"name": "guesthouse_option", "type": "any"}]
    },
    {
      "name": "option_premium_resale",
      "description": "Characterize the premium-build-and-sell option with bounds on cost and exit price",
      "subgoal_id": "options",
      "inputs": [
        {"name": "zoning_rules", "type": "any"},
        {"name": "sale_market_data", "type": "any"}
      ],
      "outputs": [{"name": "premium_resale_option", "type": "any"}]
    },
    {
      "name": "compare_options",
      "description": "Score all options against ROI, time-to-exit, risk, and hands-off constraints",
      "subgoal_id": "decision",
      "inputs": [
        {"name": "guesthouse_option", "type": "any"},
        {"name": "premium_resale_option", "type": "any"}
      ],
      "outputs": [{"name": "option_scorecard", "type": "any"}]
    },
    {
      "name": "select_strategy",
      "description": "Pick a single strategy with explicit justification and risk-aware notes",
      "subgoal_id": "decision",
      "inputs": [{"name": "option_scorecard", "type": "any"}],
      "outputs": [{"name": "chosen_strategy", "type": "any"}]
    },
    {
      "name": "detail_chosen_plan",
      "description": "Produce a phased implementation plan for the chosen strategy with milestones",
      "subgoal_id": "plan",
      "inputs": [{"name": "chosen_strategy", "type": "any"}],
      "outputs": [{"name": "implementation_dossier", "type": "any"}]
    }
  ]
}
```

### Resulting waves

```
Wave 1: check_pzz_rules, research_rental_market, research_sale_market   (3 parallel)
Wave 2: option_guesthouse, option_premium_resale                         (2 parallel)
Wave 3: compare_options
Wave 4: select_strategy
Wave 5: detail_chosen_plan
```

Note the unique output names: `rental_market_data` and `sale_market_data` — not both `market_data`. This is the rule that prevents phantom edges.

## Example 3 — Bug investigation (anti-pattern, then fix)

### Goal (input)

```json
{
  "statement": "Find root cause of intermittent test failures in CI for module X",
  "subgoals": [
    {"id": "reproduce", "description": "Make the failure reliable"},
    {"id": "isolate", "description": "Narrow down to the responsible component"},
    {"id": "fix", "description": "Patch and verify"}
  ]
}
```

### ❌ Bad decomposition (Sequential Degeneration)

```json
{
  "tasks": [
    {"name": "collect_logs", "...": "..."},
    {"name": "find_pattern", "...": "depends on collect_logs"},
    {"name": "reproduce_locally", "...": "depends on find_pattern"},
    {"name": "bisect", "...": "depends on reproduce_locally"},
    {"name": "fix", "...": "depends on bisect"},
    {"name": "verify", "...": "depends on fix"}
  ]
}
```

Single chain. Zero parallelism.

### ✅ Better decomposition

```json
{
  "tasks": [
    {
      "name": "collect_recent_failures",
      "description": "Gather log artifacts and timing data from the last 50 failed CI runs",
      "subgoal_id": "reproduce",
      "inputs": [{"name": "ci_endpoint", "type": "external"}],
      "outputs": [{"name": "failure_corpus", "type": "any"}]
    },
    {
      "name": "review_recent_changes",
      "description": "Map all merges to module X over the last 30 days against the failure timeline",
      "subgoal_id": "reproduce",
      "inputs": [{"name": "ci_endpoint", "type": "external"}],
      "outputs": [{"name": "change_timeline", "type": "any"}]
    },
    {
      "name": "find_correlations",
      "description": "Cross failure corpus and change timeline to surface candidate triggers",
      "subgoal_id": "isolate",
      "inputs": [
        {"name": "failure_corpus", "type": "any"},
        {"name": "change_timeline", "type": "any"}
      ],
      "outputs": [{"name": "candidate_triggers", "type": "any"}]
    },
    {
      "name": "reproduce_locally",
      "description": "Build a deterministic local repro from the top candidate trigger",
      "subgoal_id": "isolate",
      "inputs": [{"name": "candidate_triggers", "type": "any"}],
      "outputs": [{"name": "local_repro_recipe", "type": "any"}]
    },
    {
      "name": "patch_root_cause",
      "description": "Author a minimal fix and a regression test that fails without the fix",
      "subgoal_id": "fix",
      "inputs": [{"name": "local_repro_recipe", "type": "any"}],
      "outputs": [{"name": "patch_with_test", "type": "any"}]
    }
  ]
}
```

### Resulting waves

```
Wave 1: collect_recent_failures, review_recent_changes   (2 parallel)
Wave 2: find_correlations
Wave 3: reproduce_locally
Wave 4: patch_root_cause
```

The fix: identified that collecting logs and reviewing changes are **independent activities** that can run in parallel. The chain only kicks in after the correlation step.
