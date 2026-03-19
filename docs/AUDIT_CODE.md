# FlintTrade Code Audit

**Date:** 2026-03-19
**Auditor:** Claude Code (Opus 4.6)
**Scope:** Full codebase audit covering terminal package, services, Python packages, config, and build integrity.

---

## 1. Terminal File Inventory (`packages/terminal/src/`)

### 1.1 Widgets (13 files)

| File | Category | Status | Notes |
|---|---|---|---|
| `widgets/trading/Dashboard/DashboardWidget.jsx` | Trading | **Working** | Full implementation: indices, funds, positions, orders. Direct API calls (not DataBus). |
| `widgets/trading/Scalper/ScalperWidget.jsx` | Trading | **Working** | Full 3-panel scalper: CE/PE/Spot with charts, one-click trading, keyboard shortcuts. 790 lines. |
| `widgets/trading/Positions/PositionsWidget.jsx` | Trading | **Working** | Positions table with P&L, auto-refresh, market hours awareness. |
| `widgets/trading/Orders/OrdersWidget.jsx` | Trading | **Working** | Order book table with status badges. |
| `widgets/trading/Holdings/HoldingsWidget.jsx` | Trading | **Working** | Holdings with sorting, search, LTP resolution, multi-source fallback. 253 lines. |
| `widgets/trading/TradeBook/TradeBookWidget.jsx` | Trading | **Working** | Trade book with BUY/SELL/ALL filters, time sorting. |
| `widgets/trading/OrderPad/OrderPadWidget.jsx` | Trading | **Working** | Full order entry: symbol search, BUY/SELL, MARKET/LIMIT/SL/SL-M, qty stepper, toast. 508 lines. |
| `widgets/analysis/Chart/ChartWidget.jsx` | Analysis | **Working** | Full chart: LWC v5, symbol search, 9 intervals, OHLCV crosshair legend, H-line drawing, live ticks. 650 lines. |
| `widgets/analysis/Depth/DepthWidget.jsx` | Analysis | **Working** | 5-level depth with bid/ask bars, spread, dominance indicator. |
| `widgets/analysis/Greeks/GreeksWidget.jsx` | Analysis | **ORPHANED** | File exists (442 lines) but **NOT registered** in `widgetFactory.jsx`. Cannot be added via WidgetPicker. |
| `widgets/analysis/OIChart/OIChartWidget.jsx` | Analysis | **Working** | OI horizontal bar chart with ATM, PCR, support/resistance, filters. |
| `widgets/analysis/OptionChain/OptionChainWidget.jsx` | Analysis | **Working** | Full option chain: 3 views (LTP/OI/GREEKS), buy/sell buttons, PCR. |
| `widgets/analysis/Straddle/StraddleWidget.jsx` | Analysis | **Working** | ATM straddle tracker with LWC v5 line chart, overlays, P&L detection. |
| `widgets/utility/Watchlist/WatchlistWidget.jsx` | Utility | **Working** | Persistent watchlist, sparklines, right-click remove, DataBus integration. 660 lines. |

### 1.2 Chrome (4 files)

| File | Status | Notes |
|---|---|---|
| `chrome/TopBar.jsx` | **Working** | Layout tabs, TOOLS/WIDGETS buttons, connection indicator (ping), IST clock. |
| `chrome/TickerBar.jsx` | **Working** | 4 indices (NIFTY, SENSEX, BANKNIFTY, VIX) via DataBus. |
| `chrome/WidgetPicker.jsx` | **Working** | Modal grid picker, reads from `widgetCatalog`. |
| `chrome/ToolsDropdown.jsx` | **Working** | 7 full-page tools dropdown. |

### 1.3 Tools (7 files)

| File | Status | Notes |
|---|---|---|
| `tools/Settings/SettingsTool.jsx` | **Working** | 4 functional sections (General, API, Trading, Risk) + 7 stub sections. 586 lines. |
| `tools/BacktestLab/BacktestLabTool.jsx` | **Stub** | Coming Soon placeholder. |
| `tools/FlowBuilder/FlowBuilderTool.jsx` | **Stub** | Coming Soon placeholder. |
| `tools/MarketIntelligence/MarketIntelligenceTool.jsx` | **Stub** | Coming Soon placeholder. |
| `tools/PnLDashboard/PnLDashboardTool.jsx` | **Stub** | Coming Soon placeholder. |
| `tools/StrategyBuilder/StrategyBuilderTool.jsx` | **Stub** | Coming Soon placeholder. |
| `tools/TradeJournal/TradeJournalTool.jsx` | **Stub** | Coming Soon placeholder. |

### 1.4 Services (5 files + 2 tests)

| File | Status | Notes |
|---|---|---|
| `services/api.js` | **Working (with bugs)** | See bugs section below. |
| `services/websocket.js` | **Working** | Auto-reconnect, sub/unsub, DOM events. |
| `services/dataBus.js` | **Working** | Pub/sub singleton with cache and staleness checks. |
| `services/rateLimiter.js` | **Working** | Token bucket matching OpenAlgo rate limits (10/s, 2/s, 50/s). |
| `services/dataConnector.js` | **Working** | Bridges REST + WS to DataBus, adaptive polling, on-demand fetches. 529 lines. |
| `services/__tests__/dataBus.test.js` | **Working** | 4 tests. |
| `services/__tests__/rateLimiter.test.js` | **Working** | 3 tests. |

### 1.5 Hooks (3 files)

| File | Status | Notes |
|---|---|---|
| `hooks/useDataBus.js` | **Working** | React hook for DataBus subscription with staleness. |
| `hooks/useGlobalKeys.js` | **Working (with bug)** | See bugs section. |
| `hooks/useWebSocket.js` | **Working** | WebSocket subscription hook with instrument diffing. |

### 1.6 Other Files

| File | Status | Notes |
|---|---|---|
| `App.jsx` | **Working** | Root component: layout tabs, tools, FlexLayout, DataConnector lifecycle. |
| `main.jsx` | **Working** | React 19 StrictMode entry point. |
| `index.css` | **Working** | Tailwind v4 theme, FlexLayout dark overrides, scrollbar styling. |
| `components/Chart.jsx` | **Working** | Reusable LWC v5 chart (used by ScalperWidget). Simpler than ChartWidget. |
| `layout/LayoutManager.jsx` | **Working** | FlexLayout wrapper with `addWidget` imperative handle. |
| `layout/widgetFactory.jsx` | **Working (incomplete)** | See finding #2 below. |
| `layout/layoutStore.js` | **Working** | localStorage persistence for layout state. |
| `layout/presets/*.json` (7 files) | **Working** | 7 layout presets (minimal, blank, market-watch, analysis-desk, scalper-zone, risk-monitor, volatility-trading). |

---

## 2. widgetFactory.jsx Registration Audit

### Registered widgets (13):
`dashboard`, `scalper`, `positions`, `orders`, `holdings`, `tradebook`, `orderpad`, `chart`, `optionchain`, `oichart`, `straddle`, `depth`, `watchlist`

### Missing from registry:
- **`greeks`** -- `GreeksWidget.jsx` exists at `widgets/analysis/Greeks/GreeksWidget.jsx` (442 lines, fully implemented) but is **not registered** in the `widgets` map or `widgetCatalog` array. Users cannot add it.

### Verdict:
**1 orphaned widget** (GreeksWidget). All other 13 widgets are registered and correctly lazy-loaded.

---

## 3. App.jsx Import Audit

All imports in App.jsx are correct and resolve to existing files:
- `flexlayout-react` (Model) -- installed in node_modules
- `./services/dataConnector` (startDataConnector, stopDataConnector) -- exists
- `./chrome/TopBar`, `./chrome/TickerBar`, `./chrome/WidgetPicker`, `./chrome/ToolsDropdown` -- all exist
- `./layout/LayoutManager` -- exists
- `./layout/layoutStore` (6 named exports) -- exists
- `./layout/presets/minimal.json` -- exists
- `./hooks/useGlobalKeys` -- exists
- All 7 lazy tool imports -- all exist

**No missing imports.** All tool IDs in the `tools` map match the IDs in `ToolsDropdown.jsx`.

---

## 4. Services Consistency Audit

### api.js
- **BUG: `ping()` uses POST but OpenAlgo docs say `ping` is a GET endpoint.** Currently calls `post("ping")` which sends `{ apikey: ... }` as a POST. Should be `get("ping")`.
- **BUG: `closePosition` signature mismatch.** Defined as `closePosition(strategy = "Flint")` accepting a string. But `useGlobalKeys.js` line 41 calls `closePosition({ product: "MIS" })`, passing an object. The object gets stringified as the strategy field, resulting in `{ apikey, strategy: "[object Object]" }`.
- **BUG: `getOptionChain` accepts only 2 params (symbol, exchange)** but OptionChainWidget, OIChartWidget, and StraddleWidget all call it with 3 params: `getOptionChain(symbol, exchange, expiry)`. The third `expiry` param is silently ignored since `post("optionchain", { symbol, exchange })` doesn't pass it. This means **expiry filtering is non-functional** -- the API always returns the default (nearest) expiry regardless of user selection.

### websocket.js
- Clean implementation. Reconnect with exponential backoff, DOM event dispatch.

### dataBus.js
- Correct pub/sub with cache. Tested.

### rateLimiter.js
- Token bucket algorithm matching OpenAlgo limits. Tested.

### dataConnector.js
- Well-structured bridge layer. Adaptive polling (5s market / 60s off-market for positions). On-demand fetch for option chains and history.
- Uses all services consistently: `api.js`, `websocket.js`, `dataBus.js`, `rateLimiter.js`.

---

## 5. Old `modules/` Directory Check

**Result: `modules/` does NOT exist.** No orphaned files from the old module system. The migration to widgets/ is complete.

---

## 6. package.json Dependency Audit

### Dependencies (6):

| Package | Used? | Where |
|---|---|---|
| `flexlayout-react` | Yes | LayoutManager.jsx, App.jsx |
| `lightweight-charts` | Yes | ChartWidget.jsx, Chart.jsx, StraddleWidget.jsx |
| `lucide-react` | Yes | Every component (30+ files) |
| `react` | Yes | Every component |
| `react-dom` | Yes | main.jsx |
| `recharts` | **UNUSED** | Not imported anywhere in src/. Listed but zero usage. |

### devDependencies (7):

| Package | Used? | Where |
|---|---|---|
| `@tailwindcss/vite` | Yes | vite.config.js |
| `@vitejs/plugin-react` | Yes | vite.config.js |
| `autoprefixer` | **UNUSED** | Not referenced in any config. Tailwind v4 does not use PostCSS plugins. |
| `postcss` | **UNUSED** | Same as above. Tailwind v4 uses `@tailwindcss/vite` directly. |
| `tailwindcss` | Yes | index.css `@import "tailwindcss"`, vite plugin |
| `vite` | Yes | Build tool |
| `vitest` | Yes | Test runner |

### Findings:
- **`recharts` is unused** -- should be removed from dependencies. It was likely planned for chart components but `lightweight-charts` was used instead. This adds ~200KB+ to `node_modules` for nothing.
- **`autoprefixer` and `postcss` are unused** -- Tailwind CSS v4 with `@tailwindcss/vite` doesn't need them. Safe to remove from devDependencies.

---

## 7. Vite Build

**Could not run** `npx vite build` during this audit session due to sandbox permissions. This needs to be run manually:

```bash
cd packages/terminal && npx vite build
```

### Predicted issues based on code review:
1. Build should **succeed** -- all imports resolve, no circular dependencies detected, all lazy imports point to existing files.
2. The unused `recharts` dependency won't cause build failure but will slightly increase bundle analysis noise.
3. The `greeks` widget file will be included in the bundle as dead code (tree-shaking should remove it since nothing imports it).

---

## 8. Vitest Tests

**Could not run** `npx vitest run` during this audit session. Run manually:

```bash
cd packages/terminal && npx vitest run
```

### Test coverage:
- `dataBus.test.js` -- 4 tests (subscribe, unsubscribe, cache, null handling)
- `rateLimiter.test.js` -- 3 tests (within limit, over limit, refill)
- **No tests for:** api.js, websocket.js, dataConnector.js, any widgets, any hooks

---

## 9. `.reference/repos/` .venv Check

**Could not run** `find` for `.venv` directories due to sandbox permissions. The `.reference/repos/` directory contains 9 subdirectories:

```
1cliq, community-openalgo, external-all, indmoney, marketcalls-all,
tier1-core, tier2-ecosystem, tier3-ai-research, tier4-community
```

Run manually to check:
```bash
find .reference/repos/ -name ".venv" -type d
```

The `.gitignore` correctly includes `.reference/repos/` so even if `.venv` directories exist, they won't be committed.

---

## 10. Python Packages Health Check

**Could not run** `pytest` during this audit session. The test file `tests/test_project_structure.py` checks:
- Root files exist (CLAUDE.md, AGENTS.md, README.md, VERSION, LICENSE, .gitignore, .env.example, flint.toml, Makefile)
- All 13 packages have directories with CLAUDE.md and AGENTS.md
- VERSION file has valid semver

Run manually:
```bash
cd /c/Users/navan/Documents/GitHub/FlintTrade && python -m pytest tests/ --tb=short
```

All 13 packages exist under `packages/`: `ai`, `automation`, `backtest`, `backtest-engine`, `core`, `dashboard`, `data`, `ditto`, `engine`, `historical`, `integration`, `screener`, `terminal`.

---

## 11. .env vs .env.example Sync

### .env.example (4 vars, per CLAUDE.md spec):
```
OPENALGO_HOST=http://127.0.0.1:5000
OPENALGO_PORT=5000
OPENALGO_API_KEY=
OPENALGO_WS_PORT=8765
```

### .env (actual, 31+ vars):
```
OPENALGO_HOST, OPENALGO_API_KEY, OPENALGO_WS_PORT, OPENALGO_ZMQ_PORT,
BROKER, BROKER_CLIENT_ID, BROKER_API_KEY, BROKER_API_SECRET, BROKER_TOTP_SECRET,
DATA_DIR, LOG_DIR, AUDIT_LOG_DIR, DUCKDB_PATH, TICK_DATA_DIR,
LLM_PROVIDER, LLM_HOST, LLM_MODEL, LLM_CONTEXT_LENGTH, ANTHROPIC_API_KEY, OPENAI_API_KEY,
OPENCLAW_PORT, OPENCLAW_AUTH_TOKEN, OPENCLAW_MODEL,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ENABLED,
WIREGUARD_ENABLED, WIREGUARD_SERVER_IP, WIREGUARD_PORT,
DDNS_HOSTNAME, DDNS_PROVIDER, DDNS_USERNAME, DDNS_PASSWORD,
WAN_PRIMARY_IP, WAN_FAILOVER_IP,
BLUE_GREEN_ENABLED, OPENALGO_BLUE_PORT, OPENALGO_GREEN_PORT, ACTIVE_COLOR,
SEBI_MAX_OPS, SEBI_AUDIT_RETENTION_YEARS, SEBI_STATIC_IP_REQUIRED,
MACHINE_NAME, MACHINE_ROLE, CONTRIBUTOR_USERNAME
```

### Issues:
1. **SEVERELY out of sync.** `.env.example` has 4 vars, `.env` has 31+.
2. **OPENALGO_PORT missing from .env** -- present in `.env.example` but not in `.env`.
3. **.env contains secrets:** `OPENALGO_API_KEY` has a real 64-char hex key, `OPENALGO_HOST` points to `192.168.8.50` (local network IP). These must never be committed.
4. **.env.example has non-blank values** for `OPENALGO_HOST` and `OPENALGO_PORT` -- CLAUDE.md says "`.env.example` values ALL BLANK" but they have defaults.
5. **CLAUDE.md says only 4 vars** (`OPENALGO_HOST`, `OPENALGO_PORT`, `OPENALGO_API_KEY`, `OPENALGO_WS_PORT`). The actual `.env` has grown far beyond this without updating `.env.example` or CLAUDE.md.

---

## 12. .gitignore Audit

### Correct entries:
- `.env` and `.env.*` (except `.env.example`) -- secrets protected
- `__pycache__/`, `*.py[cod]`, `.venv/`, `venv/` -- Python artifacts
- `node_modules/`, `package-lock.json` -- Node artifacts
- `.vscode/` (with `!.vscode/settings.json` exception) -- IDE
- `.DS_Store`, `Thumbs.db` -- OS
- `*.parquet`, `*.duckdb*`, `*.sqlite`, `*.db` -- data files
- `logs/`, `*.log`, `audit_logs/`, `backtest_results/`, `tick_data/` -- trading artifacts
- `.reference/repos/`, `.reference/screenshots/` -- local reference material
- `.playwright-mcp/` -- testing screenshots

### Potential issues:
- `package-lock.json` is gitignored, which means `npm install` is not reproducible. For a monorepo with multiple contributors, this is risky -- different machines may resolve different versions.
- `yarn.lock` is also gitignored. At least one lock file should be committed.
- No `.reference/repos/.venv` entry but `.venv/` is already a global pattern so it's covered.

---

## Summary of Bugs Found

### Critical (3):

| # | Location | Bug | Impact |
|---|---|---|---|
| 1 | `services/api.js:59` | `ping()` uses POST instead of GET | Ping may fail with some OpenAlgo versions that expect GET. Currently works because OpenAlgo is lenient. |
| 2 | `hooks/useGlobalKeys.js:41` | `closePosition({ product: "MIS" })` passes object as strategy string | Shift+X "exit all positions" shortcut sends malformed request. Strategy field becomes `"[object Object]"`. |
| 3 | `services/api.js:45` | `getOptionChain(symbol, exchange)` ignores third `expiry` param | Option chain, OI chart, and straddle widgets always fetch the default (nearest) expiry regardless of user's expiry selection in the UI dropdown. |

### Medium (2):

| # | Location | Bug | Impact |
|---|---|---|---|
| 4 | `layout/widgetFactory.jsx` | GreeksWidget not registered | 442 lines of working code that users can never access. |
| 5 | `.env` / `.env.example` | Severely out of sync (4 vs 31+ vars) | New contributors get a broken setup. `.env.example` has non-blank defaults violating CLAUDE.md rules. |

### Low (3):

| # | Location | Issue | Impact |
|---|---|---|---|
| 6 | `package.json` | `recharts` dependency unused | ~200KB+ wasted in node_modules, misleading dependency list. |
| 7 | `package.json` | `autoprefixer` + `postcss` devDeps unused | Dead dependencies from Tailwind v3 era. |
| 8 | `.gitignore` | `package-lock.json` gitignored | Non-reproducible builds across machines. |

---

## Recommended Fixes (Priority Order)

### Immediate (before next feature work):

1. **Register GreeksWidget in widgetFactory.jsx:**
   - Add `greeks: lazy(() => import('../widgets/analysis/Greeks/GreeksWidget'))` to the widgets map
   - Add `{ id: 'greeks', name: 'Greeks', icon: 'Activity', category: 'Analysis' }` to widgetCatalog

2. **Fix `getOptionChain` to accept expiry param:**
   ```js
   export const getOptionChain = (symbol, exchange = "NFO", expiry) =>
     post("optionchain", { symbol, exchange, ...(expiry && { expiry }) });
   ```

3. **Fix `ping()` to use GET:**
   ```js
   export const ping = () => get("ping");
   ```

4. **Fix `closePosition` call in useGlobalKeys.js:**
   ```js
   closePosition("Flint").catch(() => {});
   ```

### Soon:

5. Sync `.env.example` -- either expand it to cover all vars (with blank values) or document the two-tier config in `.env.example` comments.
6. Remove `recharts`, `autoprefixer`, `postcss` from package.json.
7. Consider committing `package-lock.json` for reproducible builds.

---

## File Count Summary

| Category | Count |
|---|---|
| Widgets (working) | 13 |
| Widgets (orphaned) | 1 (GreeksWidget) |
| Chrome components | 4 |
| Tools (working) | 1 (Settings) |
| Tools (stubs) | 6 |
| Services | 5 |
| Service tests | 2 (7 test cases) |
| Hooks | 3 |
| Layout files | 3 + 7 presets |
| Other (App, main, index.css, Chart) | 4 |
| **Total source files** | **49** |

---

*End of audit.*
