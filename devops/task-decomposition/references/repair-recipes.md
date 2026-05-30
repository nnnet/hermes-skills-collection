# Repair Recipes for TaskTree Validation Failures

When `validate_tasks_spec()` returns errors on an existing `task_tree.json`, use these targeted fixes instead of re-decomposing from scratch.

## Recipe 1: SubgoalIdMismatch

**Symptom:** `Task 'X': subgoal_id 'SG-A' not in declared subgoals ['context', 'options', 'decision', 'plan']`

**Cause:** The decomposer invented its own subgoal labels (SG-A, SG-B, ...) instead of using the goal's declared subgoal IDs.

**Fix:** Map old IDs → declared IDs based on the task's domain role:
- `SG-A` (legal/land context) → `sg_context`
- `SG-B` (market research) → `sg_research`
- `SG-C` (monetization schemes) → `sg_options`
- `SG-D` (compare & select) → `sg_decision`
- `SG-E` (implementation planning) → `sg_plan`
- `SG-F` (final deliverable) → `sg_dossier`

**Decision point:** If the goal declares 4 subgoals but the task tree needs 6, expand the goal's subgoals to match the DAG structure. The subgoal structure should reflect parallelism groups, not arbitrary categories.

```python
# One-liner fix for all tasks:
for t in tasks:
    t['subgoal_id'] = sg_id_map.get(t['subgoal_id'], t['subgoal_id'])
```

## Recipe 2: DuplicateOutputs

**Symptom:** `Duplicate output name 'market_data' produced by tasks: ['research_rental_prices', 'research_sale_prices', 'research_tourist_demand']`

**Cause:** The decomposer reused generic output names across tasks. `Plan.from_task_tree()` will silently create phantom edges (one output fans into all consumers, not just the correct one).

**Fix:** Rename with domain prefix to make each output name globally unique:
- `market_data` (×3) → `tourist_demand_data`, `rental_market_data`, `sale_market_data`
- `option_economics` (×5) → `option_a_economics`, `option_b_economics`, ..., `option_e_economics`

**Key constraint:** When you rename an output, you must also update ALL input references that consumed the old name. Use find-and-replace on the entire tasks list.

```python
# Example rename map
rename_map = {
    ('research_tourist_demand', 'market_data'): 'tourist_demand_data',
    ('research_rental_prices', 'market_data'): 'rental_market_data',
    ('research_sale_prices', 'market_data'): 'sale_market_data',
}
for t in tasks:
    for o in t['outputs']:
        key = (t['name'], o['name'])
        if key in rename_map:
            o['name'] = rename_map[key]
    for i in t['inputs']:
        if i['name'] == 'market_data':
            # Find which producer feeds this consumer via edge inference
            # or domain logic
            ...
```

## Recipe 3: OrphanRoot

**Symptom:** `Orphan task 'check_land_category' (no edges in or out)`

**Cause:** A task's outputs aren't consumed by any other task's inputs. It exists in the tree but is disconnected from the DAG.

**Fix:** Wire the orphan into the graph by adding its outputs as inputs to logically-related tasks:
1. Look at what the orphan produces (e.g. `land_category`, `vri`)
2. Find tasks whose domain logically needs that data (e.g. `option_sell_as_is` needs land category, `plan_legal` needs VRI)
3. Add the orphan's output names to those tasks' inputs list

```python
# Example: wire check_land_category into the graph
orphan_outputs = {'land_category', 'vri'}
wiring = {
    'option_sell_as_is': ['land_category'],   # selling land needs category
    'plan_legal': ['land_category', 'vri'],    # legal registration needs both
}
for t in tasks:
    if t['name'] in wiring:
        for param in wiring[t['name']]:
            t['inputs'].append({'name': param, 'type': 'any'})
```

**Verification:** After wiring, re-run the orphan check. The task should now have both in-degree and out-degree > 0.

## Recipe 4: Rebuilding edges + topo order after repair

After any repair, the plan.json (edges + topo_order) must be rebuilt:

```python
from collections import defaultdict, deque

# Build edges by matching output names to input names
all_outputs = {}
for t in tasks:
    for o in t['outputs']:
        all_outputs[o['name']] = t['name']

edges = []
for t in tasks:
    for inp in t['inputs']:
        if inp['name'] in all_outputs:
            edges.append({
                "from_task": all_outputs[inp['name']],
                "to_task": t['name'],
                "via_param": inp['name']
            })

# Kahn's topo sort
adj = defaultdict(set)
indeg = defaultdict(int)
task_names = {t['name'] for t in tasks}
for e in edges:
    if e['to_task'] not in adj[e['from_task']]:
        adj[e['from_task']].add(e['to_task'])
        indeg[e['to_task']] += 1

queue = deque(sorted(n for n in task_names if indeg[n] == 0))
topo = []
while queue:
    node = queue.popleft()
    topo.append(node)
    for neighbor in sorted(adj[node]):
        indeg[neighbor] -= 1
        if indeg[neighbor] == 0:
            queue.append(neighbor)

assert len(topo) == len(task_names), "CYCLE detected!"
```
