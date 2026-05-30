---
name: chief-load-balancing
description: Chief load-balancing strategy — distribute tasks across multiple subagent profiles, monitor queue depth, rebalance on bottlenecks
metadata:
  type: skill
  applies_to: [Chief, Orchestrator roles in high-task-volume systems]
  tags: [kanban, orchestration, load-balancing, queue-management, subagent-dispatch]
  related_skills: [chief-manager, workflow-synthesis]
---

# Chief Load-Balancing Strategy

**When:** You have more tasks than subagents (e.g., 16 domain tasks, 1 cmf-expert). Without balancing, one agent gets overloaded and others sit idle.

**Why:** Sequential execution of 16 tasks on 1 agent takes 16× longer than 4 agents doing 4 tasks in parallel. Idle subagents waste capacity.

**How to apply:** Create specialized subagent profiles, distribute tasks among them, monitor queue depth, rebalance as needed.

---

## Strategy 1: Specialized Subagent Profiles (Recommended)

Instead of one generic `cmf-expert`, create role-specific profiles:

### Step 1: Create Multiple Profiles

```bash
# Each profile gets its own SOUL.md + config

/opt/data/profiles/cmf-indexer/
  ├── SOUL.md        (Focus: Chroma indexing, source analysis)
  ├── config.yaml    (Copy from main)
  └── entrypoint.py

/opt/data/profiles/cmf-synthesizer/
  ├── SOUL.md        (Focus: Cross-domain synthesis, pattern extraction)
  ├── config.yaml
  └── entrypoint.py

/opt/data/profiles/cmf-reviewer/
  ├── SOUL.md        (Focus: QA, validation, summary generation)
  ├── config.yaml
  └── entrypoint.py
```

Each profile has identical config but DIFFERENT SOUL.md:
- `cmf-indexer`: "Your job is to index sources into Chroma. Extract raw knowledge, organize by domain."
- `cmf-synthesizer`: "Your job is to synthesize indexed knowledge. Connect patterns, identify gaps, create synthesis docs."
- `cmf-reviewer`: "Your job is to validate indexed collections. Check completeness, quality, metadata accuracy."

### Step 2: Assign Tasks by Type

```python
def assign_domain_task(domain_name, domain_spec):
    """Route task to appropriate subagent based on domain type."""
    
    # Indexing tasks → cmf-indexer (core work)
    if domain_spec['type'] == 'indexing':
        assignee = "cmf-indexer"
    
    # Synthesis tasks → cmf-synthesizer (connects patterns)
    elif domain_spec['type'] == 'synthesis':
        assignee = "cmf-synthesizer"
    
    # Review/validation tasks → cmf-reviewer (quality gates)
    elif domain_spec['type'] == 'review':
        assignee = "cmf-reviewer"
    
    card_id = kanban_create(
        title=f"index {domain_name}: {domain_spec['title']}",
        assignee=assignee,  # ← Explicitly routed
        parents=[chief_task_id],
        body=domain_spec['body']
    )
    
    return card_id
```

**Benefit:** If cmf-indexer gets queue, but cmf-reviewer is idle, idle capacity is still there.

---

## Strategy 2: Monitor Queue Depth

```python
import time

def get_queue_depth(assignee):
    """Count tasks in 'ready' or 'running' status for assignee."""
    # Query Kanban for (assignee, status IN ['ready', 'running'])
    tasks = kanban_list(assignee=assignee, status='ready')
    tasks += kanban_list(assignee=assignee, status='running')
    return len(tasks)

def monitor_load():
    """Poll subagents every 60s, log queue depth."""
    subagents = ['cmf-indexer', 'cmf-synthesizer', 'cmf-reviewer']
    
    while True:
        loads = {}
        for agent in subagents:
            depth = get_queue_depth(agent)
            loads[agent] = depth
        
        # Log for visibility
        busiest = max(loads, key=loads.get)
        idle = min(loads, key=loads.get)
        
        print(f"⚖️  Load snapshot: {loads}")
        print(f"   Busiest: {busiest} ({loads[busiest]} tasks)")
        print(f"   Idle: {idle} ({loads[idle]} tasks)")
        
        # If imbalance > 3 tasks, consider rebalancing
        if loads[busiest] - loads[idle] > 3:
            print(f"   ⚠️  Imbalance detected. Consider rebalance.")
        
        time.sleep(60)
```

---

## Strategy 3: Dynamic Rebalancing

**Problem:** If cmf-indexer has 8 queued tasks and cmf-synthesizer has 0, rebalance by:

```python
def rebalance_queue(overloaded_agent, underutilized_agent, threshold=3):
    """
    Move tasks from overloaded → underutilized if queue depth gap > threshold.
    """
    overloaded_tasks = kanban_list(assignee=overloaded_agent, status='ready', limit=10)
    underutilized_queue = get_queue_depth(underutilized_agent)
    
    if underutilized_queue < 2 and len(overloaded_tasks) > threshold:
        # Pick a task suitable for the underutilized agent
        # (Check task domain, skills required)
        task_to_move = overloaded_tasks[0]
        
        # Move by creating a NEW task card with same content but different assignee
        new_card = kanban_create(
            title=task_to_move['title'],
            assignee=underutilized_agent,
            parents=task_to_move['parents'],
            body=task_to_move['body']
        )
        
        # Archive the old card (or mark as superseded)
        kanban_comment(
            task_id=task_to_move['id'],
            body=f"Rebalanced → {new_card} (assigned to {underutilized_agent})"
        )
        
        print(f"✅ Moved {task_to_move['id']} → {new_card}")
        print(f"   {overloaded_agent} queue: {len(overloaded_tasks)} → {len(overloaded_tasks) - 1}")
        print(f"   {underutilized_agent} queue: {underutilized_queue} → {underutilized_queue + 1}")
```

---

## Strategy 4: Chief's Distribution Loop

Chief should **continuously** monitor and route. Choose between two patterns based on your task set:

### Pattern A: Batch Creation for Independent Tasks (Recommended for known task sets)

When you have a **known, complete set of independent tasks** that don't depend on each other (like 26 domain indexing tasks), create them all together in one batch. This allows the dispatcher to pick them up in parallel immediately:

```python
def batch_create_independent_tasks(domain_tasks, subagents):
    """
    Create all independent tasks together. They all reach 'ready' at the same time,
    allowing the dispatcher to fan them out to subagents in parallel.
    Best when: you know all task names upfront and none depend on each other.
    """
    created_cards = {}
    
    # Create all tasks in one pass
    for domain_name, domain_spec in domain_tasks.items():
        card_id = kanban_create(
            title=f"index {domain_name}: {domain_spec['title']}",
            assignee="cmf-indexer",  # or route based on domain type
            parents=[chief_task_id],
            body=domain_spec['body']
        )
        created_cards[card_id] = domain_name
    
    # All 26 (or N) tasks are now in 'ready' state simultaneously
    # Dispatcher picks them up in parallel across available subagents
    return created_cards
```

### Pattern B: Gradual Feeding Loop (For dynamic task streams)

Keep distributing tasks as agents become available. Use when tasks arrive incrementally or queue depth varies:

```python
def chief_distribution_loop(domain_tasks_todo, subagents):
    """
    Keep distributing tasks as agents become available.
    Feed them steadily based on queue depth.
    Best when: tasks arrive incrementally or you need active load monitoring.
    """
    
    created_cards = {}
    task_queue = list(domain_tasks_todo.items())
    
    while task_queue:
        # Find least-busy subagent
        loads = {agent: get_queue_depth(agent) for agent in subagents}
        least_busy = min(loads, key=loads.get)
        
        # If agent has capacity (queue < 3), assign next task
        if loads[least_busy] < 3:
            domain_name, domain_spec = task_queue.pop(0)
            
            card_id = kanban_create(
                title=f"index {domain_name}: {domain_spec['title']}",
                assignee=least_busy,
                parents=[chief_task_id],
                body=domain_spec['body']
            )
            created_cards[card_id] = domain_name
            
            print(f"📤 Assigned {domain_name} → {least_busy} (queue: {loads[least_busy] + 1})")
        
        # Check for rebalancing opportunities
        if loads[max(loads, key=loads.get)] - loads[min(loads, key=loads.get)] > 3:
            rebalance_queue(
                max(loads, key=loads.get),
                min(loads, key=loads.get)
            )
        
        # Sleep before next check
        time.sleep(30)
        
        # Heartbeat for long-running loop
        kanban_heartbeat(note=f"Distribution: {len(created_cards)} assigned, {len(task_queue)} queued")
    
    return created_cards
```

**Benefit:** Tasks are distributed gradually, not all at once. Agents always have work, but not overwhelmed.

---

## Strategy 5: Avoid Bottlenecks

**Pitfalls:**
- ❌ Creating all 16 cards at once for 1 agent → instant queue of 15
- ❌ Ignoring queue depth → agents idle while others overloaded
- ❌ Static assignment → no adaptation to actual execution time
- ❌ No visibility → you don't know who's busy

**Best practices:**
- ✅ Monitor load every 30–60 seconds
- ✅ Distribute new tasks to least-busy agent
- ✅ Rebalance if gap > 3 tasks
- ✅ Log queue depth per agent (for post-mortem analysis)
- ✅ Heartbeat during loops so dispatcher knows you're alive

---

## Example: CMF-YNVRSTY with 3 Subagents

```
Initial: 16 domain tasks, 3 subagents

Minute 0:
  ├─ cmf-indexer: [Finance, ML, Programming] (queue: 3)
  ├─ cmf-synthesizer: [Math, Economics, Risk] (queue: 3)
  └─ cmf-reviewer: [Testing, Validation, QA] (queue: 3)
     Remaining: 7 tasks in Chief's queue

Minute 30: Finance indexing completes
  ├─ cmf-indexer: [ML, Programming, DataProcessing] (queue: 3)
  ├─ cmf-synthesizer: [Math, Economics, Risk] (queue: 3)
  └─ cmf-reviewer: [Testing, Validation, QA] (queue: 3)

Minute 60: All agents steady
  ├─ cmf-indexer: queue 3 (busy)
  ├─ cmf-synthesizer: queue 2 (steady)
  └─ cmf-reviewer: queue 1 (light)
  → Rebalance: move 1 task from indexer → reviewer

Result: No agent idle, no queue > 3, all 16 tasks flowing through the system.
```

---

## Related skills

- `chief-manager` — main orchestration meta-skill (uses this for Phase 4 load distribution)
- `workflow-synthesis` — combining outputs from multiple agents
