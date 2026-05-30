# Hindsight Bank Isolation — API Contract & Patterns

Validated 2026-05-18 against Hindsight server on `localhost:8888`.

## When to use

Per-expert bank isolation is needed when:
- Building a domain-expert team (trading, risk, econometrics, …)
- Each expert must recall only its own domain knowledge, not a shared pool
- MCP `hindsight_recall` is insufficient — it only queries the default `hermes` bank

## API endpoints

All paths relative to `http://localhost:8888`.

| Action | Method | Path |
|---|---|---|
| List all banks | GET | `/v1/default/banks` |
| Create/upsert bank | PUT | `/v1/default/banks/{bank_id}` |
| Add memories (sync or async) | POST | `/v1/default/banks/{bank_id}/memories` |
| Check async operation | GET | `/v1/default/banks/{bank_id}/operations/{operation_id}` |
| Recall memories | POST | `/v1/default/banks/{bank_id}/memories/recall` |

## Bank creation (idempotent)

```bash
curl -s -X PUT http://localhost:8888/v1/default/banks/quants-risk \
  -H "Content-Type: application/json" -d '{}'
# 200 OK — safe to repeat
```

Naming convention: `<project>-<domain>` (e.g. `quants-risk`, `quants-trading`).

## Loading facts — sync vs async

**Sync** (< 5 items or short content):
```json
POST /v1/default/banks/quants-risk/memories
{"items": [{"content": "VaR measures...", "context": "quants-risk domain knowledge"}], "async": false}
```

**Async** (large batches — avoids 60s execute_code timeout):
```json
POST /v1/default/banks/quants-risk/memories
{"items": [...many items...], "async": true}
```
Returns `{"operation_id": "uuid"}`. Poll for completion:
```bash
curl http://localhost:8888/v1/default/banks/quants-risk/operations/<op_id>
```

## Verify facts loaded (run before dispatching onboarding tasks)

```python
import requests, json
banks = requests.get("http://localhost:8888/v1/default/banks").json()
for b in banks:
    if b["id"].startswith("quants-"):
        facts = b.get("facts_count", b.get("size", "?"))
        print(f"{b['id']:30} facts={facts:>4}")
```
All banks must show `facts > 0` before the onboarding wave is dispatched.

## SOUL.md recall snippet (Onboarding Protocol Step 0)

Add as the first step in each expert's `## Onboarding Protocol`:

```markdown
### Step 0 — Recall domain knowledge from Hindsight bank
```python
import requests
r = requests.post(
    "http://localhost:8888/v1/default/banks/quants-<DOMAIN>/memories/recall",
    json={"query": "CMF quantitative finance <domain> knowledge"},
    timeout=20,
)
for m in r.json().get("memories", []):
    print(m.get("content", ""))
```
Store recalled facts as working context before querying Chroma or starting analysis.
```

Replace `<DOMAIN>` with the expert's domain slug (e.g. `risk`, `trading`, `econometrics`).

## Pitfalls

- **MCP `hindsight_recall` ≠ bank isolation.** No `bank_id` param exists in the MCP tool — it always hits `hermes`. Use HTTP for any isolated bank.
- **Verify async ops before dispatch.** `async: true` returns immediately; facts aren't searchable until the op completes. Always poll before creating dependent kanban tasks.
- **Empty PUT body is fine.** `CreateBankRequest` fields are all optional/deprecated — `{}` works.
- **Bank IDs are case-sensitive.** Use lowercase-hyphen convention everywhere.
- **`/api/banks` returns 404.** The correct base path is `/v1/default/banks`, not `/api/banks`.
