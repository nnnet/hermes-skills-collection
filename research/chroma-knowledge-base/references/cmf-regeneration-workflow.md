# CMF Chroma Regeneration Workflow

Project-specific extension for regenerating existing CMF Chroma collections with 5-layer metadata schema.

**Script location:** `/opt/data/workspace/cmf-experts/cron/chroma_regeneration_v2.py`

## When to Use

Use this workflow when:
- Some sources (Google Drive, VK, LinkedIn) are missing entirely
- YouTube is only partially indexed (playlists exist, but individual videos not transcribed)
- Metadata layer is incomplete or outdated
- Documents were added to repos but not yet indexed

**Prerequisites:** Always verify source coverage first using the discovery workflow (see `references/cmf-sources-coverage-check.md`).

## 5-Layer Metadata Schema

1. **Provenance Layer**: source, processor, review_status, timestamp, version
2. **Semantic Layer**: summary, concepts, hashtags, domain
3. **Quality Layer**: validation_score, completeness_score, confidence
4. **Connectivity Layer**: related_docs, dependencies, parent_task
5. **Technical Layer**: hash, language, char_count, token_estimate, schema_version

## Processing Steps

- ✅ **Deduplication**: Removes exact duplicate documents by SHA256 hash
- ✅ **Timestamps**: Adds created_at, updated_at, processed_at to every document
- ✅ **Batch updates**: Updates all collections in parallel
- ✅ **Logging**: Saves detailed JSON log per run

## Launch Instructions

### Option 1: Manual One-Time Run
```bash
cd /opt/data/workspace/cmf-experts
python3 cron/chroma_regeneration_v2.py
```

Output: 
- Console: Full processing log with per-collection stats
- File: `/opt/data/workspace/cmf-experts/cron/logs/regeneration_YYYYMMDD_HHMMSS.json`

### Option 2: Schedule as Cronjob (Every 15 Minutes)
```bash
# Add to /etc/cron.d/cmf-chroma-regen
*/15 * * * * cd /opt/data/workspace/cmf-experts && python3 cron/chroma_regeneration_v2.py >> /opt/data/workspace/cmf-experts/cron/logs/cron.log 2>&1
```

### Option 3: Run with Supervisor (Continuous)
Create `/opt/data/workspace/cmf-experts/cron/chroma_regen_supervisor.py` to continuously monitor and re-run if needed.

## Expected Output

```json
{
  "timestamp": "2026-05-15T22:10:55.123456",
  "collections_processed": 6,
  "documents_enriched": 2847,
  "duplicates_removed": 142,
  "errors": 0,
  "collection_details": {
    "finance-data": {
      "original_count": 450,
      "after_dedup": 445,
      "duplicates_removed": 5,
      "enriched": 445,
      "status": "success"
    }
  }
}
```

## Verification

After regeneration, verify enrichment in Chroma:
```bash
curl -s http://127.0.0.1:8005/api/v1/collections/finance-data/get \
  | jq '.metadatas[0]' | grep -E '(timestamp|provenance|quality|semantic)'
```

Expected: Each document metadata should contain all 5 layer prefixes.

## Dependencies

- Python 3.8+
- `requests`, `chromadb`, `anthropic` libraries
- Chroma running on `127.0.0.1:8005`

```bash
pip install requests chromadb anthropic
```

## Integration Patterns

This script is designed to run:
1. **On demand** (manual trigger)
2. **Scheduled** (cronjob every 15 min)
3. **On event** (webhook trigger when new data arrives)
4. **Supervised** (Chief agent monitors and restarts if failed)

## Pitfalls

- **Chroma not responding**: Check `ps aux | grep chroma-mcp`
- **Collections not updating**: Verify REST API endpoint is correct
- **Missing fields**: Ensure metadatas dict is properly structured
- **Embedding mismatch**: Script preserves original embeddings; verify they're still valid

## Next Steps After Running

1. Monitor logs: `tail -f /opt/data/workspace/cmf-experts/cron/logs/regeneration_*.json`
2. Verify sample documents in Chroma admin UI (chromadb-admin sidecar on port 8001)
3. Enable continuous cronjob for autonomous operation
4. Update Chief supervisor to coordinate with other workers
