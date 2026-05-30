# Profile Crash Diagnosis — Missing Toolsets

## Symptom

A profile starts, runs for 60-120 seconds, then crashes with:
- `exit_code: 1` (nonzero exit)
- `pid not alive` (process killed, no exit code)
- No helpful error message in kanban events

The dispatcher retries (up to `failure_limit` times), each attempt crashes the same way.

## Root cause

The profile's SOUL.md references tools (e.g., `execute_code`, `terminal`, `read_file`, `skill_view`) that require specific toolsets in `config.yaml`, but those toolsets are not configured.

The agent reads the SOUL.md, tries to follow the instructions, discovers the tool isn't available, and either:
1. Crashes trying to call a non-existent tool
2. Times out trying to work around the missing tool
3. Gets killed by the gateway for exceeding timeout

## Diagnosis steps

```bash
# 1. Check what toolsets the profile has
grep -A10 'toolsets:' /opt/data/profiles/<role>/config.yaml

# 2. Check what tools the SOUL.md references
grep -oP '[a-z_]+\(' /opt/data/profiles/<role>/SOUL.md | sort -u

# 3. Cross-reference
# Every tool call in step 2 must map to a toolset in step 1
# See soul-md-authoring skill, references/toolset-tool-mapping.md
```

## Fix

Add the missing toolsets to config.yaml:

```yaml
toolsets:
- hermes-cli
- kanban
- terminal    # if SOUL runs Python or shell
- file        # if SOUL reads/writes files
- skills      # if SOUL loads skills
# ... keep existing ones
```

## Prevention

Before deploying a new profile, run the toolset verification checklist from `soul-md-authoring/references/toolset-tool-mapping.md`.

## Real example (2026-05-16)

task-decomposer profile had:
```yaml
toolsets:
- hermes-cli
- kanban
- moa
- debugging
- image_gen
- video
```

But SOUL.md had:
```python
import sys
sys.path.insert(0, '/opt/data/skills/devops/task-decomposition/scripts')
from decomposer import build_decomposition_prompt
```

Missing: `terminal` (for Python execution), `file` (for file I/O), `skills` (for skill_view).

Result: 6 consecutive crashes. Fix: added `terminal`, `file`, `skills` to toolsets + simplified SOUL.md from ~5KB procedural code to ~3KB protocol.
