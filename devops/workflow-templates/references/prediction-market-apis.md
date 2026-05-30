# Prediction Market APIs — Reference for Template 5 implementations

## Polymarket (primary prediction market, 2026)

### Gamma API (market discovery — public, no auth)

Base URL: `https://gamma-api.polymarket.com`

**Key endpoints:**
- `GET /markets?active=true&closed=false` — active open markets
- `GET /markets/{condition_id}` — single market by conditionId
- `GET /events` — grouped events (multiple markets per event)
- `GET /markets?tag={tag}` — filter by category tag

**Market object key fields:**
- `conditionId` (string) — the canonical market identifier (use this, NOT internal IDs)
- `question` (string) — market question text
- `outcomes` (list) — e.g. ["Yes", "No"]
- `outcomePrices` (list) — current prices as probabilities, e.g. [0.65, 0.35]
- `volume` (float) — total volume in USD
- `liquidity` (float) — current liquidity in USD
- `endDate` (ISO timestamp) — market close time
- `active` (bool), `closed` (bool)
- `category` (string) — broad category
- `slug` (string) — URL slug, useful for `polymarket.com/event/{slug}`

**Filtering thresholds (recommended starting point):**
- Minimum volume: $1,000
- Minimum liquidity: $500
- Skip markets closing within 1 hour (insufficient time for edge to materialize)

### CLOB API (order book data — public, no auth)

Base URL: `https://clob.polymarket.com`

**Key endpoints:**
- `GET /book?token_id={token_id}` — order book for a market
- `GET /midpoint?token_id={token_id}` — midpoint price
- `GET /price?token_id={token_id}&side={BUY|SELL}` — best price

Note: `token_id` is NOT the same as `conditionId`. Map via the Gamma API market object which includes `clobTokenIds`.

### Market categories (as of 2026)
- Crypto (BTC/ETH price targets, ETF approvals, etc.)
- Politics (elections, policy, geopolitics)
- Sports (NFL, NBA, soccer, etc.)
- Tech (product launches, acquisitions, AI milestones)
- Culture (entertainment, awards, social media events)
- Science (climate, health, space)

### Tips
- Rate limits are generous for public endpoints (~100 req/min)
- Market questions can be ambiguous — parse carefully for LLM prompts
- Prices are probabilities (0-1 scale), not dollar amounts
- Binary markets have Yes/No; multi-outcome markets exist too
- Resolution source varies per market — check the market details for resolution rules
