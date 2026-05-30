---
name: web-search-service
description: Unified web search and URL fetch with automatic fallback. Load this skill when you need to search the web or read a URL. Do not think about which search tool to use — this skill handles tool selection and retries automatically.
metadata:
  hermes:
    tags: [search, web, fetch, research, fallback]
    category: research
---

# Web Search Service

Single entry point for all web search and URL fetch operations. Handles tool selection and fallback automatically. Do not manually choose between brave_web_search / duckduckgo_search / web_extract — load this skill and follow the protocol.

## When to use

- Any time you need to find information on the web
- Any time you need to read the content of a specific URL
- Any time you need both: search then read top results
- Replace any ad-hoc "which search tool should I use?" decision with this skill

## Domain routing (auto-learning)

Before choosing a fetch backend, the code reads `references/domains.json`.
This file maps known domains to their required backend tier — no hardcoding in SKILL.md.

**Tiers (weakest → strongest):** `web_extract` → `curl` → `playwright` → `skip`

When a backend fails, `record_failure()` auto-escalates the domain in the JSON file so future calls skip the failing tier.

To manually register a new problem domain:

```python
import sys
sys.path.insert(0, '/opt/data/skills/research/web-search-service/scripts')
from search import add_domain

add_domain("somesite.ru", "playwright", "JS SPA, blocks curl")
# backends: "web_extract" | "curl" | "playwright" | "skip"
```

Or from the CLI:
```bash
python /opt/data/skills/research/web-search-service/scripts/search.py \
  --add somesite.ru playwright "JS SPA, blocks curl"
```

The `domains.json` file is the single source of truth — check it when debugging fetch failures.

---

## Protocol

### Step 1 — Run the Python layer (automated: Tavily → SearxNG → curl)

In `execute_code`, import and call the service script:

```python
import sys
sys.path.insert(0, '/opt/data/skills/research/web-search-service/scripts')
from search import search, fetch, search_and_fetch
import json

# Search only — returns top URLs with titles/descriptions
result = search("your query here", limit=5)
print(json.dumps(result, ensure_ascii=False, indent=2))

# Fetch only — read a specific URL you already have
result = fetch("https://example.com")
print(json.dumps(result, ensure_ascii=False, indent=2))

# Full pipeline — search then read top N pages
result = search_and_fetch("your query here", limit=5, fetch_top_n=2)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

### Step 2 — Evaluate result

- `result["error"]` is None AND results non-empty → **done, use the content**
- `result["error"]` set OR results empty → **go to Step 3**

### Step 3 — MCP fallback (if Python layer returned empty)

Try in order, stop when you get results:

**For search:**
1. `brave_web_search(query=..., count=10)` — supports operators: `site:`, `filetype:`, `intitle:`, `-term`
2. `duckduckgo_search(query=..., max_results=10)` — privacy-first, no API key needed

**For fetch:**
1. `duckduckgo_fetch_content(url=..., backend="curl")` — Chrome TLS impersonation, bypasses Cloudflare and most bot-filters
2. `mcp_fetch_fetch(url=..., raw=True)` — raw HTML
3. **Playwright MCP** — full JS render, для JS-heavy и bot-protected страниц:
   ```
   mcp_playwright_browser_navigate(url=...)   ← загрузить страницу
   mcp_playwright_browser_snapshot()          ← accessibility tree (текст + структура)
   mcp_playwright_browser_evaluate(function="() => document.body.innerText")  ← голый текст
   ```
4. **Built-in browser** — альтернатива Playwright, тот же паттерн:
   ```
   mcp_browser_navigate(url=...)
   mcp_browser_snapshot(full=True)            ← полная accessibility tree
   mcp_browser_vision(question="...")         ← визуальный анализ если snapshot неполный
   ```
   Используй `mcp_browser_scroll(direction="down")` для lazy-loaded страниц перед snapshot.

**Когда использовать браузер вместо curl:**
- Сайты недвижимости (ЦИАН, Авито, Домклик) — всегда блокируют curl → сразу Playwright
- Страницы с ленивой загрузкой (infinite scroll) → browser + scroll
- Нужно визуально проверить что на странице → `mcp_browser_vision`
- Cloudflare challenge / JS-рендеринг → Playwright eval

**For local businesses / addresses / places near me:**
Skip Steps 1–3 entirely, go directly to:
- `brave_local_search(query=...)` — returns ratings, hours, phone numbers

## Output format (Python layer)

```json
// search()
{
  "source": "tavily_or_searxng",
  "results": [
    {"url": "https://...", "title": "...", "description": "..."}
  ],
  "error": null
}

// fetch()
{
  "source": "web_extract",
  "content": "... page content in markdown ...",
  "error": null
}

// search_and_fetch()
{
  "search": { "source": "...", "results": [...] },
  "pages": [
    {
      "url": "https://...",
      "title": "...",
      "content": "... page text ...",
      "source": "web_extract",
      "error": null
    }
  ]
}
```

## Decision tree (quick reference)

```
Need to search the web?
  └─► execute_code: search("query", limit=5)
       ├─ got results → use them
       └─ empty/error → brave_web_search → duckduckgo_search

Need to read a specific URL?
  └─► execute_code: fetch("url")
       ├─ got content → use it
       └─ empty/error → duckduckgo_fetch_content(backend="curl")
            └─ still blocked? → mcp_fetch_fetch(raw=True)
                 └─ JS-heavy / bot-protected? → Playwright: navigate → snapshot → evaluate
                      └─ нужен визуальный анализ? → browser: navigate → scroll → vision

Need search + read top results?
  └─► execute_code: search_and_fetch("query", limit=5, fetch_top_n=2)
       └─ apply same fallback chain per page if needed

Looking for a business / restaurant / address?
  └─► brave_local_search("query")   ← skip Python layer entirely
```

## fetch() return values

| `source` | Meaning | What to do |
|---|---|---|
| `web_extract` / `curl` | Success | Use `content` field |
| `playwright_required` | Domain needs browser | Read `instructions` field and call Playwright MCP tools directly |
| `skip` | Domain blacklisted | Don't fetch, find alternative source |
| `none` | All tiers failed unexpectedly | Check error, try `add_domain()` + retry |

When `source == "playwright_required"`, the `instructions` field contains exact MCP tool calls to copy-paste.

## Pitfalls

- `brave_local_search` is for physical locations ONLY — useless for general web content
- If a page is a PDF (arxiv, documents), `fetch()` handles it via `web_extract` automatically — do NOT curl a PDF
- `web_extract` LLM-summarizes pages > 5000 chars; use `duckduckgo_fetch_content` if you need full raw text
- The `search()` function's auto-fallback from Tavily to SearxNG is internal and transparent — you do not need to call them separately
- Do NOT hardcode domain names in SKILL.md or code — add them to `references/domains.json` via `add_domain()`
- Real estate portals (ЦИАН, Авито, etc.) are already in `playwright_required` — `fetch()` will return `playwright_required` immediately for them, no wasted retries
- After using Playwright to successfully fetch a domain, call `add_domain(domain, "playwright", reason)` so the next call skips the lower tiers automatically
- Сайты недвижимости (ЦИАН, Авито, Домклик, realtymag.ru) **всегда** блокируют Python/curl — не трать попытки, сразу Playwright
- Playwright `snapshot()` возвращает accessibility tree — для price listings этого достаточно, eval нужен редко
- После `mcp_playwright_browser_navigate` обязательно дождись загрузки: `mcp_playwright_browser_wait_for(time=2)` перед snapshot на тяжёлых страницах
- `mcp_browser_vision` стоит токенов — используй только если snapshot не читается (таблицы, карты, изображения с ценами)
- Playwright и built-in browser — **разные** MCP серверы, оба доступны; Playwright предпочтительнее для scraping (есть `evaluate` и `network_requests`)
