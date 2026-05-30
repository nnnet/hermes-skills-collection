---
name: chroma-knowledge-base
description: "Build domain knowledge bases in Chroma from GitHub repos, notebooks, and web sources."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [chroma, knowledge-base, vector-search, github, indexing, RAG]
    category: research
    related_skills: [llm-wiki, github-repo-management]
---

# Chroma Knowledge Base Builder

Build persistent, searchable domain knowledge bases in Chroma vector DB by mining
GitHub repos, Jupyter notebooks, and web sources for patterns, code examples,
best practices, and domain concepts.

Unlike the markdown LLM Wiki pattern, this produces vector-embedded documents
optimized for semantic search (RAG) rather than human-navigable hyperlinked notes.

## When This Skill Activates

- Asked to build, populate, or index a knowledge base into a Chroma collection
- Running as a cron expert agent (e.g. `cmf-programming` expert in CMF-YNVRSTY system)
- Mining GitHub repositories for code patterns, best practices, algorithms
- Converting source code / notebooks into searchable knowledge fragments

## Workflow

### Phase 1: Discover Sources

```python
# 1. List org repos via GitHub API (no auth needed for public repos)
GET https://api.github.com/orgs/{org}/repositories
GET https://github.com/orgs/{org}/repositories  # HTML fallback via fetch

# 2. Identify target repos by language
# Python repos: best for code pattern extraction
# Jupyter Notebook repos: algo implementations, data science workflows
# CMake/C++ repos: skip or note for later

# 3. Explore repo structure
GET https://api.github.com/repos/{owner}/{repo}/contents
GET https://api.github.com/repos/{owner}/{repo}/contents/{path}  # subdirectories
```

### Phase 2: Fetch Raw Content

```
# Raw Python/text files (manageable size <20KB)
GET https://raw.githubusercontent.com/{owner}/{repo}/main/{path}

# Jupyter notebooks
# WARNING: notebooks are JSON — cells are nested under "source" arrays
# Small notebooks (< 400KB): fetch full, parse JSON structure
# Large notebooks (> 1MB): use start_index pagination (fetch 6000-8000 chars at a time)
# Notebooks embed base64 images in output cells — skip those sections

# requirements.txt: always fetch — reveals the tech stack
```

### Phase 3: Extract Knowledge Units

Each document = one concept, pattern, or technique. Target size: 500–1500 chars.

**Good chunking strategies:**
- One class per document (with its key patterns explained)
- One function/algorithm per document
- One design pattern per document
- One workflow/pipeline per document
- One "pitfall + fix" per document

**Do NOT** dump entire files as single documents — semantic search degrades badly
on 5000+ char documents.

### Phase 4: Index into Chroma

```python
# CRITICAL PITFALL: metadata dicts must be NON-EMPTY
# This FAILS:
chroma_add_documents(collection, docs, ids, metadatas=[{}, {}, {}])
# Error: "Expected metadata to be a non-empty dict, got 0 metadata attributes"

# This WORKS — always include at least one field:
chroma_add_documents(
    collection_name="my-collection",
    documents=["doc content..."],
    ids=["unique-id-1"],
    metadatas=[{
        "domain": "programming",
        "subdomain": "risk-models",
        "source": "github/repo-name/file.py",
        "level": "intermediate",       # beginner | intermediate | advanced
        "type": "code-pattern",        # code-pattern | algorithm | best-practice | reference | design-pattern
        "language": "python",
        "tags": "GARCH, VaR, arch-library"
    }]
)
```

### Phase 5: Verify

```python
# Check count
chroma_get_collection_count(collection_name)

# Smoke-test semantic search
chroma_query_documents(
    collection_name,
    query_texts=["relevant search query"],
    n_results=3,
    include=["documents", "metadatas"]
)
# Verify top results are semantically relevant
```

## Document ID Conventions

Use hierarchical, readable IDs — never random UUIDs:

```
{repo-short}-{module}-{concept}
# Examples:
is2022-models-garch11
is2022-metrics-pof
algo-core-backtest-engine
cmf-python-stack
```

This makes it easy to identify and update specific documents later.

## Metadata Schema (recommended)

```json
{
  "domain": "programming",          // top-level domain
  "subdomain": "risk-models",       // specific area
  "source": "github/repo/file.py",  // provenance
  "level": "intermediate",          // difficulty: beginner | intermediate | advanced
  "type": "code-pattern",           // content type (see below)
  "language": "python",             // programming language
  "tags": "GARCH, VaR, MLE"        // comma-separated key terms
}
```

**Type values:**
- `code-pattern` — specific implementation technique
- `algorithm` — full algorithmic workflow
- `design-pattern` — OOP / architectural pattern
- `best-practice` — style / correctness guidance
- `reference` — library usage quick-reference
- `testing` — test patterns and strategies

## Batch Size

Add documents in batches of 3–10 per call. Larger batches increase the risk of
stream timeouts in long-running cron sessions. After each batch, continue
immediately — do not wait for user confirmation in cron context.

## Document Template

```markdown
# {Concept Name}

Source: {owner}/{repo}/{file}

```python
{clean, runnable code example}
```

## Pattern: {what makes this notable}
- Key point 1
- Key point 2
- Key point 3

## {When to Use / Algorithm Steps / Best Practice}
- ...
```

## Handling Large Notebooks

Jupyter notebooks embed large base64 images in output cells. Strategy:
1. Fetch first 8000 chars — usually covers imports + first 1-2 cells
2. Identify code structure from imports and class definitions
3. Paginate with `start_index` in 6000-char increments until you hit base64 walls
4. Skip `"image/png"` and `"image/jpeg"` output cells — no useful text content
5. Prioritize `"source"` arrays within `"cell_type": "code"` cells

## Direct HTTP API (when chromadb Python client unavailable)

The `chromadb` Python package is not installed in the Hermes venv. Use the HTTP API directly via `requests`. **Chroma now requires v2 API** — v1 returns `410 Gone`.

```python
import json, requests

BASE = "http://localhost:8005/api/v2"
TENANT = "default_tenant"
DB = "default_database"

# Get collection ID (needed for update/query endpoints)
r = requests.get(f"{BASE}/tenants/{TENANT}/databases/{DB}/collections/{collection_name}")
col_id = r.json()["id"]

# Update documents (enrich metadata)
payload = {"ids": ids, "metadatas": metadatas}
r = requests.post(
    f"{BASE}/tenants/{TENANT}/databases/{DB}/collections/{col_id}/update",
    json=payload
)
assert r.status_code == 200, r.text

# Count documents
r = requests.get(f"{BASE}/tenants/{TENANT}/databases/{DB}/collections/{col_id}/count")
count = r.json()
```

**Metadata value types**: Chroma only accepts `str`, `int`, `float`, `bool`. Stringify any list values before passing:
```python
for meta in metadatas:
    for k, v in meta.items():
        if isinstance(v, list):
            meta[k] = ", ".join(str(x) for x in v)
```

## Regenerating Existing Collections

After initial population, you may need to regenerate collections to:
- Enrich metadata with additional layers (timestamp, provenance, quality scores, connectivity)
- Remove duplicates by SHA256 hash
- Add newly indexed sources (e.g., YouTube transcripts, Google Drive documents)
- Update quality/confidence scores or semantic fields

**Typical regeneration workflow:**

1. **Discover current coverage** — Query Chroma to identify which sources are indexed and which gaps exist (see `references/cmf-sources-coverage-check.md`)
2. **Plan enrichment** — Decide which metadata layers to add and which sources to ingest
3. **Run regeneration script** — Execute the regeneration workflow with 5-layer metadata (see `references/cmf-regeneration-workflow.md` for CMF-YNVRSTY example)
4. **Verify** — Query Chroma after regeneration to confirm all 5 layers are present
5. **Monitor** — Schedule as cronjob for continuous updates (every 15 minutes is typical)

For project-specific regeneration workflows, see the CMF-YNVRSTY reference implementation in `references/cmf-regeneration-workflow.md`.

## Pitfalls

- **Non-empty metadata required**: Chroma rejects `{}` metadata — always include at least `{"domain": "..."}`.
- **Notebook base64 bloat**: Large notebooks are mostly base64 image data. Paginate to find code cells; stop when output is all base64.
- **One-file-one-document anti-pattern**: Indexing whole files as single documents kills search quality. Always chunk by concept.
- **Stream timeouts in cron**: Tools may hit "Stream closed" — this is transient. The next invocation will continue from where the last succeeded. Design batches so each is independently useful.
- **GitHub API rate limits**: Public API allows 60 req/hour unauthenticated. Space calls; prefer `raw.githubusercontent.com` for file content (not rate-limited separately).
- **IDs must be unique**: Duplicate IDs in `chroma_add_documents` silently overwrite existing documents. Use the hierarchical naming convention above.

## Reference Files

- `references/cmf-programming-schema.md` — metadata schema and document examples from the CMF-YNVRSTY programming knowledge base session (2026-05-14)
