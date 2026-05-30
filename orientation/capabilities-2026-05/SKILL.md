---
name: capabilities-2026-05
description: "Lists capabilities added 2026-05-15 — persistent memory (Hindsight), web search (Tavily/SearxNG), YouTube downloads, kanban Aegis attestation, cost analytics. Load when the user asks what new things you can do, or for orientation in the active stack."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [capabilities, orientation, memory, web, kanban, youtube, cost]
    related_skills: [kanban-worker]
---

# Hermes capabilities — added 2026-05-15

This skill is the short reference for what the Hermes agent gained on
2026-05-15. Load it when:

- The user asks "что ты теперь умеешь" / "what's new" / "what can you do".
- You're orienting yourself at the start of a session and the conversation
  touches memory, web search, YouTube, or kanban review.
- You're about to do something that one of these capabilities replaces
  (e.g. about to `web_search` with a stale provider, or about to skip
  the Aegis handoff before blocking a kanban task).

---

## 1. Persistent memory — Hindsight

**Provider:** `hindsight` on `127.0.0.1:8888` (local_external).
**Fact extractor:** LM Studio `gpt-oss-20b`.
**Tools:** `hindsight_retain`, `hindsight_recall`.

**When to retain:** stable preferences, project decisions, recurring
constraints, domain facts that aren't already obvious from the
codebase. NOT every chitchat detail; the writer is rate-limited and the
recall budget is finite.

**When to recall:** at the start of a continuing topic, before
answering "did we discuss X?", or whenever the user references
something from a past session.

**Example — retain a preference:**

> User: I prefer `dataclass` over `pydantic` for internal models.

```python
hindsight_retain(
    text="User preference: dataclass over pydantic for internal-only models (no validation needs).",
    metadata={"topic": "preferences", "scope": "python"},
)
```

**Example — recall before answering:**

> User: How did we decide to key the rate limiter again?

```python
hits = hindsight_recall(query="rate limiter key user_id IP decision", limit=5)
# then summarize hits in the reply
```

---

## 2. Web search — Tavily primary, SearxNG fallback

**Tools:** `web_search`, `web_extract` (the same two tools regardless
of backend — routing is configured server-side via `web.backend`).

**Tavily (primary)** — `web.backend: tavily`. Better quality,
citation-aware, supports extract on individual URLs (incl. PDFs).
Rate-limited by API key quota.

**SearxNG (fallback)** — `127.0.0.1:8506`. Use when:
- Tavily quota is exhausted (you'll see an explicit quota error).
- Query is sensitive/internal and zero-logging at provider side matters.
- You want a meta-search across DuckDuckGo, Bing, etc.

To swap, edit `web.backend` in `~/.hermes/config.yaml` (or ask the user
to do it). The tool names don't change.

**Example — find recent docs:**

> User: Find the latest Python release notes.

```python
web_search(query="Python 3.14 release notes 2026", limit=5)
```

**Example — read a specific page:**

```python
web_extract(urls=["https://docs.python.org/3.14/whatsnew/3.14.html"])
```

---

## 3. YouTube downloads — `yt-dlp-fresh` with live Firefox cookies

**Command:** `yt-dlp-fresh` (host shell, NOT a hermes tool). Auto-runs
`yt-dlp -U` when the installed yt-dlp is more than ~24h old, so format
selectors and signature decryption stay current.

**Cookie path:** the wrapper mounts the user's Firefox profile and
passes `--cookies-from-browser firefox:/opt/firefox-profile`. Age-gated
and member-only videos work without any manual cookie file.

**Example:**

```bash
yt-dlp-fresh -f "bv*+ba/b" -o "%(title)s.%(ext)s" "https://www.youtube.com/watch?v=XXXXXXXXXXX"
```

Do NOT use `uvx yt-dlp` or `pip install yt-dlp` — those snapshots go
stale within days and YouTube breaks signature extraction on the old
binary.

---

## 4. Aegis-attestation handshake (kanban QA)

When you finish a kanban task that produced files, post a structured
handoff comment **before** blocking the task for review. Aegis polls
blocked tasks, verifies the declared deliverables, posts a signed
attestation, and auto-unblocks on PASS.

**Without the handoff comment** → Aegis skips your task → it sits in
`blocked` until a human notices.

**Handoff shape:**

```python
import json, os

kanban_comment(
    task_id=os.environ["HERMES_KANBAN_TASK"],
    body="review-required handoff:\n" + json.dumps({
        "changed_files": [
            "rate_limiter.py",
            "tests/test_rate_limiter.py",
        ],
        "tests_run": 14,
        "tests_passed": 14,
    }, indent=2),
)
kanban_block(
    reason="review-required: rate limiter shipped, 14/14 tests pass",
)
```

`changed_files` paths are relative to the kanban workspace root. See
the `kanban-worker` skill for the full pitfalls list around metadata
shape, retries, and `created_cards`.

---

## 5. Cost visibility — dashboard Analytics

`dashboard.show_token_analytics: true` exposes per-model token usage
and cost in the dashboard Analytics + Models tabs. Be deliberate about
expensive aux calls:

- Compression / summarization with the main model — costs per turn add up.
- `web_extract` on large pages (multi-page PDFs, long-form articles)
  triggers LLM summarization on top of fetch.
- Prefer the cheaper path when accuracy is comparable (e.g. a short
  Tavily snippet over a full extract).

No tool change here — just a reminder that you can see the bill now,
and so can the user.
