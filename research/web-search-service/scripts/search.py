"""
Web Search Service — unified search/fetch with automatic fallback.

fetch() reads references/domains.json before choosing a backend:
  - Known playwright-required domains → skip directly to Playwright instructions
  - Known curl-bypass domains → skip web_extract, start at curl
  - Unknown domains → start at web_extract, auto-escalate on failure

Usage from execute_code:
    import sys
    sys.path.insert(0, '/opt/data/skills/research/web-search-service/scripts')
    from search import search, fetch, search_and_fetch, add_domain

Functions:
    search(query, limit=5)                          -> dict
    fetch(url, max_length=8000)                     -> dict
    search_and_fetch(query, limit=5, fetch_top_n=2) -> dict
    add_domain(domain, backend, reason)             -> None  # register a new domain rule
"""
import json
import os
import sys

_SCRIPTS_DIR = os.path.dirname(__file__)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from domain_config import add_domain, get_backend, record_failure  # noqa: E402


def search(query: str, limit: int = 5) -> dict:
    """
    Search the web. Auto-fallback: Tavily -> SearxNG (built into web_search).

    Returns:
        {
            "source": str,
            "results": [{"url": str, "title": str, "description": str}],
            "error": str | None
        }
    """
    from hermes_tools import web_search

    try:
        raw = web_search(query, limit=limit)
        results = raw.get("data", {}).get("web", [])
        if results:
            normalized = [
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "description": r.get("description", ""),
                }
                for r in results
            ]
            return {"source": "tavily_or_searxng", "results": normalized, "error": None}
        return {"source": "web_search", "results": [], "error": "empty_results"}
    except Exception as e:
        return {"source": "web_search", "results": [], "error": str(e)}


def fetch(url: str, max_length: int = 8000) -> dict:
    """
    Fetch a URL. Reads domain_config to determine starting backend tier,
    then falls back upward: web_extract → curl → playwright.
    Failures are recorded to domains.json for future calls (auto-learning).

    Returns:
        {
            "source": "web_extract" | "curl" | "playwright_required" | "skip" | "none",
            "content": str,
            "error": str | None,
            "instructions": str  # only when source == "playwright_required"
        }
    """
    from hermes_tools import web_extract, terminal

    tier = get_backend(url)

    if tier == "skip":
        return {"source": "skip", "content": "", "error": "domain_in_skip_list"}

    # --- Tier 1: web_extract ---
    if tier == "web_extract":
        try:
            raw = web_extract(urls=[url])
            results = raw.get("results", [])
            if results:
                content = results[0].get("content", "")
                if content and len(content.strip()) > 100:
                    return {
                        "source": "web_extract",
                        "content": content[:max_length],
                        "error": None,
                    }
        except Exception:
            pass
        record_failure(url, "web_extract")
        tier = "curl"

    # --- Tier 2: curl with Chrome UA ---
    if tier == "curl":
        try:
            r = terminal(
                f'curl -sL --max-time 20 --noproxy "*" '
                f'-H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                f'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" '
                f'"{url}" 2>/dev/null | head -c {max_length}'
            )
            output = r.get("output", "")
            if r.get("exit_code") == 0 and len(output.strip()) > 100:
                return {"source": "curl", "content": output, "error": None}
        except Exception:
            pass
        record_failure(url, "curl")
        tier = "playwright"

    # --- Tier 3: Playwright (instructions for the LLM layer) ---
    # fetch() cannot call Playwright tools directly — return instructions for the caller.
    return {
        "source": "playwright_required",
        "content": "",
        "error": "requires_playwright",
        "instructions": (
            f"All lightweight backends failed or this domain requires Playwright. "
            f"Use MCP Playwright tools directly:\n"
            f"1. mcp_playwright_browser_navigate(url='{url}')\n"
            f"2. mcp_playwright_browser_snapshot()  — structured text (preferred)\n"
            f"   OR mcp_playwright_browser_take_screenshot() + vision_analyze() — for visual content\n"
            f"3. If content is behind JS: mcp_playwright_browser_evaluate("
            f"function='() => document.body.innerText')\n"
            f"4. Scroll if needed: mcp_playwright_browser_scroll(direction='down')\n"
            f"After success, call: add_domain('<root-domain>', 'playwright', '<reason>')"
        ),
    }


def search_and_fetch(query: str, limit: int = 5, fetch_top_n: int = 2) -> dict:
    """
    Full pipeline: search then fetch top N result pages.
    Pages requiring Playwright return instructions instead of content.

    Returns:
        {
            "search": { ...search result... },
            "pages": [{"url", "title", "content", "source", "error", "instructions"?}]
        }
    """
    search_result = search(query, limit=limit)
    pages = []

    for r in search_result.get("results", [])[:fetch_top_n]:
        fetch_result = fetch(r["url"])
        page = {
            "url": r["url"],
            "title": r.get("title", ""),
            "content": fetch_result.get("content", ""),
            "source": fetch_result["source"],
            "error": fetch_result.get("error"),
        }
        if "instructions" in fetch_result:
            page["instructions"] = fetch_result["instructions"]
        pages.append(page)

    return {"search": search_result, "pages": pages}


# Re-export add_domain so callers can do: from search import add_domain
__all__ = ["search", "fetch", "search_and_fetch", "add_domain"]


# CLI: python search.py "query" | python search.py --fetch "https://..." | python search.py --add domain backend reason
if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"error": "Usage: search.py <query> | --fetch <url> | --add <domain> <backend> <reason>"}))
        sys.exit(1)

    if args[0] == "--fetch":
        if len(args) < 2:
            print(json.dumps({"error": "Missing URL after --fetch"}))
            sys.exit(1)
        print(json.dumps(fetch(args[1]), ensure_ascii=False, indent=2))

    elif args[0] == "--add":
        if len(args) < 3:
            print(json.dumps({"error": "Usage: --add <domain> <backend> [reason]"}))
            sys.exit(1)
        reason = args[3] if len(args) > 3 else ""
        add_domain(args[1], args[2], reason)
        print(json.dumps({"ok": True, "domain": args[1], "backend": args[2]}, ensure_ascii=False))

    else:
        query = " ".join(args)
        print(json.dumps(search(query), ensure_ascii=False, indent=2))
