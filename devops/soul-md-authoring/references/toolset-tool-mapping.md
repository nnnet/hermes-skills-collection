# Toolset → Tool Mapping

When writing a SOUL.md, every tool call you reference must map to a toolset in the profile's `config.yaml`. This reference documents which toolsets provide which tools.

## Built-in toolsets (Hermes core)

| Toolset | Provides | When to include |
|---|---|---|
| `terminal` | `terminal()`, `execute_code()`, shell commands | SOUL runs Python, shell scripts, installs packages |
| `file` | `read_file()`, `write_file()`, `patch()`, `search_files()` | SOUL reads/writes files, searches code |
| `skills` | `skill_view()`, `skill_manage()`, `skills_list()` | SOUL loads skills for protocol reference |
| `kanban` | `kanban_show()`, `kanban_create()`, `kanban_complete()`, `kanban_block()`, `kanban_comment()`, `kanban_heartbeat()`, `kanban_list()` | SOUL is a kanban worker or orchestrator |
| `hermes-cli` | `hermes` CLI commands | SOUL uses hermes CLI features |
| `web` | `web_search()`, `web_extract()` | SOUL fetches web content |
| `search` | `session_search()`, `hindsight_recall/retain/reflect()` | SOUL needs memory or session history |
| `browser` | `browser_*()` tools | SOUL interacts with web pages |
| `delegation` | `delegate_task()` | SOUL spawns subagents |
| `debugging` | Debug-specific tools | SOUL debugs code |
| `image_gen` | `image_generate()` | SOUL generates images |
| `video` | `video_analyze()` | SOUL processes video |
| `vision` | `vision_analyze()` | SOUL analyzes images |
| `tts` | `text_to_speech()` | SOUL generates audio |
| `cronjob` | `cronjob()` | SOUL schedules recurring tasks |

## MCP toolsets (config.yaml mcp.servers)

Each MCP server in config.yaml provides its own tools. Common ones:

| MCP server | Provides | Example tools |
|---|---|---|
| `chroma` | Vector DB operations | `chroma_add_documents`, `chroma_query_documents`, etc. |
| `sqlite` | SQLite queries | `read_query`, `write_query`, `create_table` |
| `filesystem` | File operations | `read_file`, `write_file`, `list_directory` |
| `git` | Git operations | `git_commit`, `git_diff`, `git_log` |
| `fetch` | URL fetching | `fetch()` |
| `youtube_transcript` | YouTube transcripts | `get_transcript()` |

## Verification checklist

After writing a SOUL.md, run this check:

```bash
# 1. Extract all tool calls from SOUL.md
grep -oP '[a-z_]+\(' /opt/data/profiles/<role>/SOUL.md | sort -u

# 2. Check which toolsets are configured
grep -A20 'toolsets:' /opt/data/profiles/<role>/config.yaml

# 3. Verify each tool call maps to a configured toolset
# If a tool isn't covered → either add the toolset or remove the tool call
```

## Common mismatches

| SOUL.md calls | Missing toolset | Fix |
|---|---|---|
| `execute_code(...)`, `terminal(...)` | `terminal` | Add `terminal` to toolsets |
| `read_file(...)`, `write_file(...)` | `file` | Add `file` to toolsets |
| `skill_view(...)` | `skills` | Add `skills` to toolsets |
| `kanban_show(...)`, `kanban_complete(...)` | `kanban` | Add `kanban` to toolsets |
| `web_search(...)` | `web` | Add `web` to toolsets |
| `delegate_task(...)` | `delegation` | Add `delegation` to toolsets |
