# Working dispatch pattern — hermes kanban create via execute_code

Discovered 2026-05-17 during CMF-YNVRSTY Quants KB project.

## Key facts

- `hermes` binary: `/opt/hermes/.venv/bin/hermes` (not in PATH inside execute_code)
- Board env var: `HERMES_KANBAN_BOARD=quants` must be passed via subprocess env
- `kanban create` title is POSITIONAL (no `--title` flag)
- `--json` flag returns structured JSON with task id, status, etc.

## Working Python snippet (copy-paste ready)

```python
import os, subprocess, json

HERMES = "/opt/hermes/.venv/bin/hermes"
env = {**os.environ, "HERMES_KANBAN_BOARD": "quants"}  # swap board slug as needed

def hk_create(title, assignee, body, max_runtime="3600", parents=None):
    cmd = [HERMES, "kanban", "create", title,
           "--assignee", assignee,
           "--body", body,
           "--max-runtime", max_runtime,
           "--json"]
    if parents:
        for p in parents:
            cmd += ["--parent", p]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    try:
        return json.loads(r.stdout)
    except:
        return {"error": r.stderr[:200], "raw": r.stdout[:100]}

# Example Wave 1 (no parents):
t = hk_create("ingest_youtube: transcribe 141 videos", "youtube-indexer",
               "Body text...", max_runtime="28800")
print(t["id"], t["status"])  # t_cddb0fd3  ready

# Example Wave 2 (with parents):
t2 = hk_create("merge_enrich: merge all raw docs", "enricher",
                "Body...", max_runtime="7200",
                parents=["t_cddb0fd3", "t_ae0493b1", "t_841894bd", "t_49cdb1ac"])
```

## Board creation

```bash
/opt/hermes/.venv/bin/hermes kanban boards create quants --switch
# Creates /opt/data/kanban/boards/quants/kanban.db
# Sets current board to 'quants' for CLI session
# execute_code still needs HERMES_KANBAN_BOARD env var
```

## Edge attributes (graph.py)

```python
for e in workflow.plan.edges:
    print(e.from_task, "->", e.to_task, "via", e.via_param)
# NOT: e.source, e.target, e.label — those don't exist
```

## YouTube unique video count (per-playlist enumeration)

Channel-level `yt-dlp @CHANNEL` only returns channel-owned videos.
To get true unique count including external speakers in playlists:

```python
import subprocess, json

playlists = open('/tmp/finance_playlists.txt').read().splitlines()
all_ids = set()
for pl in playlists:
    result = subprocess.run(
        ['yt-dlp', '--flat-playlist', '--dump-json',
         f'https://www.youtube.com/playlist?list={pl}'],
        capture_output=True, text=True)
    ids = [json.loads(l)['id'] for l in result.stdout.splitlines() if l.strip()]
    all_ids.update(ids)
print(f"True unique count: {len(all_ids)}")
# CMF_YNVRSTY: channel-level = 120, per-playlist = 141 (21 external speaker videos)
```
