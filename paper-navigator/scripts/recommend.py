#!/usr/bin/env python3
"""Get paper recommendations from Semantic Scholar.

Given seed papers (positive examples, optionally negative examples),
returns semantically similar papers.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

from utils import (
    S2_BASE,
    S2_RECOMMEND_BASE,
    s2_headers,
    request_with_retry,
    normalize_paper_id,
)

S2_FIELDS = "paperId,externalIds,title,authors,year,citationCount,influentialCitationCount,isOpenAccess,openAccessPdf"


def _resolve_to_s2_id(client: httpx.Client, paper_id: str) -> str:
    """Resolve any paper ID format to S2 paperId."""
    try:
        data = request_with_retry(
            client, f"{S2_BASE}/paper/{paper_id}", {"fields": "paperId"}, s2_headers()
        )
        return data.get("paperId", paper_id)
    except Exception:
        return paper_id


def recommend(
    positive_ids: list[str], negative_ids: list[str] | None = None, limit: int = 10
) -> list[dict]:
    """Get recommendations based on seed papers."""
    with httpx.Client() as client:
        # Resolve all IDs to S2 format
        pos_s2 = [
            _resolve_to_s2_id(client, normalize_paper_id(pid)) for pid in positive_ids
        ]
        neg_s2 = [
            _resolve_to_s2_id(client, normalize_paper_id(pid))
            for pid in (negative_ids or [])
        ]

        body: dict = {
            "positivePaperIds": pos_s2,
        }
        if neg_s2:
            body["negativePaperIds"] = neg_s2

        data = request_with_retry(
            client,
            f"{S2_RECOMMEND_BASE}/papers/",
            params={"fields": S2_FIELDS, "limit": min(limit, 500)},
            headers=s2_headers(),
            method="POST",
            json_body=body,
        )
    return data.get("recommendedPapers", [])


def format_paper(p: dict, idx: int) -> str:
    title = p.get("title", "Unknown")
    year = p.get("year", "?")
    citations = p.get("citationCount", 0)
    authors = p.get("authors", [])
    author_str = ", ".join(a.get("name", "") for a in authors[:3])
    if len(authors) > 3:
        author_str += " et al."

    tldr = ""
    if p.get("tldr") and p["tldr"].get("text"):
        tldr = f"\n  > {p['tldr']['text']}"

    ext = p.get("externalIds", {})
    arxiv = ext.get("ArXiv", "")
    pid = p.get("paperId", "")
    id_str = f"arXiv:`{arxiv}`" if arxiv else f"S2:`{pid[:12]}…`"

    pdf = ""
    if p.get("openAccessPdf") and p["openAccessPdf"].get("url"):
        pdf = " 📄"

    return f"{idx}. **{title}** — {author_str} ({year}) — ⭐{citations}{pdf} — {id_str}{tldr}"


def main():
    parser = argparse.ArgumentParser(
        description="Get paper recommendations from Semantic Scholar"
    )
    parser.add_argument(
        "--positive",
        "-p",
        required=True,
        help="Comma-separated seed paper IDs (positive examples)",
    )
    parser.add_argument(
        "--negative",
        "-n",
        help="Comma-separated paper IDs to avoid (negative examples)",
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=10, help="Max results (default 10)"
    )
    parser.add_argument(
        "--min-citations",
        type=int,
        default=0,
        help="Filter papers with fewer citations (default 0 = no filter). Use 50-100 to surface canonical works.",
    )
    parser.add_argument(
        "--canonical",
        action="store_true",
        help="Shortcut for --min-citations 50 + larger pool. Surfaces foundational papers instead of recent preprints.",
    )
    parser.add_argument(
        "--year-max",
        type=int,
        help="Filter papers published after this year (e.g. --year-max 2023 excludes 2024-2026).",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    positive = [p.strip() for p in args.positive.split(",") if p.strip()]
    negative = (
        [p.strip() for p in args.negative.split(",") if p.strip()]
        if args.negative
        else None
    )

    if not positive:
        print("Error: at least one positive paper ID required", file=sys.stderr)
        sys.exit(1)

    # Determine pool size and min-citations
    min_cites = args.min_citations
    if args.canonical:
        min_cites = max(min_cites, 50)

    # Over-fetch if we're filtering (S2 returns newest first)
    pool_size = args.limit
    if min_cites > 0 or args.year_max:
        pool_size = max(args.limit * 10, 100)

    papers = recommend(positive, negative, pool_size)

    # Filter by min_citations
    if min_cites > 0:
        papers = [p for p in papers if (p.get("citationCount") or 0) >= min_cites]

    # Filter by year_max
    if args.year_max:
        papers = [p for p in papers if (p.get("year") or 0) <= args.year_max]

    # Sort by citations when filtering (canonical mode wants high-impact first)
    if min_cites > 0 or args.canonical:
        papers.sort(key=lambda p: p.get("citationCount", 0), reverse=True)

    papers = papers[: args.limit]

    if not papers:
        if min_cites > 0:
            print(
                f"⚠ No recommendations passed --min-citations {min_cites}. "
                f"S2's recommend endpoint returns recent preprints (typically 0-citation). "
                f"For canonical similar papers, try: `scholar_search.py --query '<topic>' --sort-by citations`",
                file=sys.stderr,
            )
        else:
            print("No recommendations found.", file=sys.stderr)
        sys.exit(0)

    if args.json:
        print(json.dumps(papers, indent=2))
        return

    print("# Paper Recommendations\n")
    print(f"Seeds: {', '.join(f'`{p}`' for p in positive)}")
    if negative:
        print(f"Avoid: {', '.join(f'`{n}`' for n in negative)}")
    print(f"\nFound **{len(papers)}** recommendations\n")
    for i, p in enumerate(papers, 1):
        print(format_paper(p, i))
    print()


if __name__ == "__main__":
    main()
