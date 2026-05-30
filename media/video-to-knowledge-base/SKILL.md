---
name: video-to-knowledge-base
description: "Store preprocessed video document into Chroma collection + create/update wiki page. Input: structured doc from video-preprocessor. Universal — domain and paths are parameters."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [chroma, wiki, indexing, knowledge-base, video, lecture]
    category: media
    related_skills: [video-preprocessor, youtube-playlist-reader, llm-wiki, chroma-knowledge-base]
---

# Video → Knowledge Base

Store a preprocessed video document into:
1. **Chroma** — for semantic search
2. **Wiki** — human-readable lecture summary page

**Input:** structured document from `video-preprocessor` skill.

## When to use
After `video-preprocessor` returns a document dict, load this skill to persist it.

## Prerequisites

```python
COLLECTION_NAME = "cmf-mathematics"       # Chroma collection name
WIKI_PATH = "/opt/data/workspace/wiki"    # universal wiki root
WIKI_DOMAIN_DIR = "finance"               # subdir inside wiki: finance | ml | econometrics
```

## Step 1: Verify Chroma baseline

```python
# Use chroma_get_collection_count tool:
# count_before = chroma_get_collection_count(collection_name=COLLECTION_NAME)
# If collection doesn't exist:
# chroma_create_collection(collection_name=COLLECTION_NAME)
# count_before = 0
```

## Step 2: Check for duplicate in Chroma

```python
# Use chroma_get_documents tool to check if already indexed:
# existing = chroma_get_documents(collection_name=COLLECTION_NAME, ids=[doc["id"]])
# if existing["ids"]:
#     print(f"Already indexed: {doc['id']} — skipping Chroma")
#     chroma_skip = True
```

## Step 2.5: Validate Layer 1 metadata (data-governance-metadata-schema)

Before writing to Chroma, verify mandatory Layer 1 fields are present and non-empty:
```python
REQUIRED_LAYER1 = ["source_url", "source_type", "source_created_date", "author",
                   "processor_agent", "processed_date", "language", "project_id"]
missing = [f for f in REQUIRED_LAYER1 if not doc["metadata"].get(f)]
if missing:
    pass  # → kanban_block(reason=f"Layer 1 metadata missing: {missing}")
# domains must be a list, not a string
if not isinstance(doc["metadata"].get("domains", []), list):
    pass  # → kanban_block(reason="metadata.domains must be a list")
```
Layer 1 failure → block. Do not write partial metadata to Chroma.

## Step 3: Add to Chroma

```python
# Use chroma_add_documents tool:
# chroma_add_documents(
#     collection_name=COLLECTION_NAME,
#     documents=[doc["text"]],
#     ids=[doc["id"]],
#     metadatas=[doc["metadata"]]
# )
```

## Step 4: Verify Chroma insertion

```python
# count_after = chroma_get_collection_count(collection_name=COLLECTION_NAME)
# if count_after <= count_before:
#     → kanban_block(reason=f"INTEGRITY FAILURE: count unchanged {count_before}→{count_after} for {doc['id']}")
```

**Never call kanban_complete before this check.**

## Step 5: Create wiki page

Generate a lecture summary page in the domain subdirectory.

```python
from hermes_tools import read_file, write_file
import os, re
from datetime import date

def slug(title):
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60]

def create_wiki_page(doc, wiki_path, domain_dir):
    today = date.today().isoformat()
    video_slug = slug(doc["title"])
    page_path = f"{wiki_path}/{domain_dir}/{video_slug}.md"

    # Don't overwrite existing page — update instead
    if os.path.exists(page_path):
        print(f"Wiki page exists: {page_path} — updating")
        # Read existing, append new section with updated date
        # (simple update: bump updated: date in frontmatter)
        content = open(page_path).read()
        content = re.sub(r'updated: \d{4}-\d{2}-\d{2}', f'updated: {today}', content)
        write_file(page_path, content)
        return page_path

    # Build concise summary from transcript (first 1500 chars as proxy)
    transcript_excerpt = doc["transcript"][:1500] if doc.get("transcript") else ""

    page = f"""---
title: "{doc['title']}"
created: {today}
updated: {today}
type: lecture
domain: {doc.get('domain', domain_dir)}
tags: []
sources: [raw/transcripts/{doc['id']}.md]
confidence: medium
---

# {doc['title']}

**Source:** [{doc['url']}]({doc['url']})
**Duration:** {doc.get('duration_seconds', 0) // 60} min
**Language:** {doc.get('language', 'unknown')}

## Summary

> Auto-generated from transcript. Review and expand with domain expertise.

{transcript_excerpt}{'...' if len(doc.get('transcript','')) > 1500 else ''}

## Key Concepts

<!-- Fill in after reviewing transcript -->

## Related Pages

<!-- Add [[wikilinks]] to at least 2 related pages -->

## Visual Content

{doc.get('visual_notes', '(no frame analysis)') or '(no frame analysis)'}
"""
    write_file(page_path, page)
    return page_path
```

## Step 6: Save raw transcript

```python
def save_raw_transcript(doc, wiki_path):
    from datetime import date
    raw_path = f"{wiki_path}/raw/transcripts/{doc['id']}.md"
    if os.path.exists(raw_path):
        return raw_path  # immutable — never overwrite

    import hashlib
    body = doc.get('transcript', '')
    sha = hashlib.sha256(body.encode()).hexdigest()

    content = f"""---
source_url: {doc['url']}
ingested: {date.today().isoformat()}
sha256: {sha}
---

{body}
"""
    write_file(raw_path, content)
    return raw_path
```

## Step 7: Update wiki index.md

```python
def update_wiki_index(doc, wiki_path, domain_dir, page_path):
    from datetime import date
    index_path = f"{wiki_path}/index.md"
    rel_path = page_path.replace(wiki_path + "/", "")
    video_slug = os.path.basename(page_path).replace('.md', '')
    entry = f"- [[{domain_dir}/{video_slug}]] — {doc['title'][:70]} ({doc.get('duration_seconds',0)//60} min)"

    content = open(index_path).read()
    # Find the right domain section and insert
    section_header = f"## {domain_dir.capitalize()}"
    if section_header in content:
        content = content.replace(section_header, f"{section_header}\n{entry}")
    else:
        content += f"\n{section_header}\n{entry}\n"

    # Update header stats
    page_count = content.count('\n- [[')
    today = date.today().isoformat()
    content = re.sub(r'Last updated: \S+', f'Last updated: {today}', content)
    content = re.sub(r'Total pages: \d+', f'Total pages: {page_count}', content)

    write_file(index_path, content)
```

## Step 8: Append to log.md

```python
def append_log(doc, wiki_path, page_path):
    from datetime import date
    log_path = f"{wiki_path}/log.md"
    entry = f"\n## [{date.today().isoformat()}] ingest | {doc['title'][:60]}\n- Source: {doc['url']}\n- Wiki page: {page_path}\n- Chroma id: {doc['id']}\n"
    with open(log_path, 'a') as f:
        f.write(entry)
```

## Full flow

```python
# After video-preprocessor returns doc:

save_raw_transcript(doc, WIKI_PATH)
page_path = create_wiki_page(doc, WIKI_PATH, WIKI_DOMAIN_DIR)
update_wiki_index(doc, WIKI_PATH, WIKI_DOMAIN_DIR, page_path)
append_log(doc, WIKI_PATH, page_path)

print(f"Indexed: Chroma={COLLECTION_NAME} | Wiki={page_path}")
```

## Domain → Chroma collection mapping (CMF example)
```
finance/       → cmf-quantitative-finance
econometrics/  → cmf-econometrics
ml/            → cmf-machine-learning
```
This mapping belongs in the orchestrator's SOUL.md, not in this skill.

## Pitfalls
1. **Never overwrite `raw/transcripts/`** — these are immutable source files
2. **Duplicate Chroma IDs** — check before inserting; yt-dlp video IDs are stable unique keys
3. **Wiki page must have 2+ wikilinks** — remind the agent to fill in Related Pages
4. **count_after == count_before** → BLOCK, don't complete
5. **index.md section must exist** — SCHEMA.md defines domain sections; add missing ones before inserting
