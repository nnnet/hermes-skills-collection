# CMF-YNVRSTY Programming Knowledge Base — Session Reference
# Date: 2026-05-14 | Collection: cmf-programming | Final count: 36 documents

## Metadata Schema Used

```json
{
  "domain": "programming",
  "subdomain": "<see list below>",
  "source": "github/<repo-name>/<file>",
  "level": "beginner | intermediate | advanced",
  "type": "code-pattern | algorithm | design-pattern | best-practice | reference | testing",
  "language": "python",
  "tags": "comma, separated, key, terms"
}
```

## Subdomain Values Used

- `risk-models` — VaR, ES, GARCH, RiskMetrics, HistoricalSimulation
- `backtesting` — POF test, IF test, walk-forward, event-driven simulation
- `loss-functions` — quantile loss, pinball loss
- `data-pipeline` — Dataloader, returns, gdown, Binance API
- `design-patterns` — Strategy pattern, Iterator protocol, Template method
- `trading-framework` — Feed, IStrategy, Backtest, Position, P&L
- `trading-strategies` — Pair trading, mean-reversion, z-score, Bollinger Bands
- `technical-analysis` — TA-Lib, Bollinger Bands, moving averages
- `performance-metrics` — Sortino ratio, Sharpe, max drawdown, return%
- `optimization` — Optuna, Bayesian hyperparameter search, multiprocessing
- `testing` — pytest patterns, setup_class, np.allclose, regression tests
- `libraries` — CMF Python stack: pandas, numpy, scipy, arch, gdown
- `numerical-computing` — NumPy array operations, matrix math, boolean indexing
- `data-manipulation` — pandas time series, rolling windows, covariance
- `visualization` — matplotlib, backtest P&L plots, signal overlays
- `financial-data` — log vs simple returns, pct_change, portfolio construction
- `time-series` — rolling window, walk-forward, look-ahead bias
- `architecture` — project structure, separation of concerns, data flow
- `macro-analysis` — FRED API, GDP, inflation, correlation matrices
- `best-practices` — type hints, assertions, reproducibility, tqdm
- `volatility-modeling` — GARCH workflow, conditional volatility, ARCH effects test
- `statistical-testing` — scipy norm/chi2, likelihood ratio, p-values

## Document ID Naming Convention

```
{repo-short}-{module}-{concept}

Repo short names:
  is2022    → importance-sampling-2022
  algo      → algo-hedge-fund
  cmf       → synthesized CMF best practices

Examples:
  is2022-models-riskmetrics
  is2022-metrics-pof
  algo-core-backtest-engine
  algo-pair-trading-strategy
  algo-optuna-hyperopt
  cmf-python-stack
  cmf-garch-workflow
```

## Source Repositories Indexed

| Repo | Files | Documents |
|------|-------|-----------|
| cmf-team/importance-sampling-2022 | models.py, metrics.py, data.py, multivariate_models.py, test.py, requirements.txt | 15 |
| cmf-team/algo-hedge-fund/Materials | core.py, pair_ma.ipynb | 13 |
| cmf-team/macro-time-series-2022 | README | 1 |
| Synthesized best practices | — | 7 |

## GitHub API Endpoints Used

```
# Org repo list
https://github.com/orgs/cmf-team/repositories  (HTML, fetch)
https://api.github.com/orgs/cmf-team/repositories  (JSON API)

# Directory listing
https://api.github.com/repos/cmf-team/{repo}/contents
https://api.github.com/repos/cmf-team/{repo}/contents/{path}

# Raw file content
https://raw.githubusercontent.com/cmf-team/{repo}/main/{filepath}
```

## Key Pitfall Encountered

**Chroma non-empty metadata**: First batch failed with:
```
Error: Expected metadata to be a non-empty dict, got 0 metadata attributes in add.
```
Caused by passing `metadatas=[{}, {}, {}]`. Fix: always include at least one metadata field.

## Notebook Pagination Notes

`pair_ma.ipynb` (381KB) required start_index pagination:
- 0–8000: imports + MA strategy class definition
- 8000–14000: get_plot_lines, Binance data fetching cells
- 14000–20000: data merging, first backtest run output
- 20000+: mostly base64 image data interspersed with Optuna trial logs
- 300000+: Optuna output (trial logs, best params)
- 306000+: more trial logs

Strategy: skip base64 sections, look for `"cell_type": "code"` → `"source"` arrays.
