# FlintTrade Feature Inventory

This is the build-status inventory the project's roadmap calls for: every mission
pillar and feature, categorised as **(a) built & working**, **(b) built but
untested or only partially wired**, or **(c) referenced but not built / blocked**.
It is a living document — update it in the same change that moves a feature
between buckets.

`v0.6.0-beta` is not production ready. The native adapter code for the four
founder brokers (Dhan / Upstox / Kotak Neo / IndMoney) is present and
mock-tested, but only Dhan currently carries an active SDK pin in
`brokers.lock`. Upstox and Kotak Neo stay placeholder-pinned until their wave is
approved with exact SDK hashes, licence evidence, and sandbox evidence; Kotak Neo
is additionally blocked until the upstream SDK licensing is compatible or
explicitly authorised. IndMoney is REST-only and has no SDK pin.

## Legend

| Mark | Meaning |
|---|---|
| ✅ | **(a)** Built & working — wired end-to-end and covered by tests |
| 🟡 | **(b)** Built but untested, partially wired, or honest-sample-only |
| ⛔ | **(c)** Referenced but not built, or externally blocked |

---

## Independence

| Item | Status | Notes |
|---|---|---|
| Native-first backend, gateway contract, safety/gating layer | ✅ | Original work; not a fork |
| Attribution (`NOTICE`, `docs/REFERENCES.md`, AGPL `LICENSE`) | ✅ | Adapted modules carry in-source `Adapted from:` headers |
| Independence statement in README + website | ✅ | `docs/README.md` "Independence & attribution" → site |

## Brokers

| Item | Status | Notes |
|---|---|---|
| OpenAlgo bridge adapter (orders + market data) | ✅ | The only functional **order** adapter; ~45 endpoints |
| Smart routing suggestions | ✅ | Capability metadata + recommendation engine + Account-Manager UI |
| — Dhan: rolling-options history + multi-level depth (L20) | ✅ | Encoded as routing capabilities (`options_history_*`, `depth_levels`) |
| — Upstox: historical-data edge | ✅ | `historical_max_lookback/candles` capabilities |
| — Kotak Neo: low-cost execution metadata | ✅ | `brokerage_free` + `low_cost_execution` use-case |
| Native adapters (Dhan/Upstox/Kotak Neo/IndMoney): identity, capabilities, order + **data** surfaces | 🟡 | Adapter and mapping code is present and mock-tested. Dhan has the active `dhanhq` pin; Upstox/Kotak Neo are placeholder-pinned until exact SDK, licence, approval, and sandbox evidence are recorded; IndMoney is REST-only. |
| Native adapters: **order execution** end-to-end (R13/R14) | 🟡 | The gated path they plug into (`SafetySystem → gate_order → BrokerRouter`) is built + tested. Live native execution remains disabled unless the broker has an active attested pin plus vault credentials; Kotak Neo also needs upstream licence clearance before any pin or install guidance is carried. |
| Multiple brokers per account, per-broker rate limits | ✅ | `BrokerRateLimiter` + live-apply UI (Account Manager) |

## AI Agent

| Item | Status | Notes |
|---|---|---|
| Connect to any model — cloud providers | ✅ | OpenAI/Anthropic/Gemini/Groq/Mistral/… via `LLMProvider` + `LLMSection` |
| Local models — Ollama, LM Studio, Hermes | ✅ | First-class providers in backend + settings UI |
| OpenClaw agents | ✅ | Control-plane widget (deploy / stop / logs) |
| Obsidian vault | ✅ | Read-only browser widget + agent vault context |
| Create strategies | ✅ | StrategyBuilder (legs / payoff / margin / Pine) — Lab "Options Builder" tab; loads templates from the StrategyTemplates widget via explicit strike offsets |
| Backtest strategies (single + portfolio) | ✅ | Lab Backtest + Portfolio tabs (132 runnable by name; 41 selectable in the Lab picker) |
| Optimise overnight + reports + suggestions | ✅ | OvernightOptimiser + report store + Lab Optimize section |
| Pick strategy per market regime | ✅ | `regime_detector` `_REGIME_STRATEGY` → RegimePanel "Suggested Strategy" |

## Manual Trading Terminal

| Item | Status | Notes |
|---|---|---|
| Preset layouts (14) | ✅ | Dockview workspace presets |
| Options-scalper 4-chart layout | ✅ | Index+Futures (centre) / CE+PE (sides) / option chain — per-panel pinned charts; tested |
| Trading + dashboard widgets (~86) | ✅ | Registered in `widgetFactory`, co-located tests |
| Screens: welcome / dashboard / explore / demo | ✅ | Demo mode feeds widgets + dashboard cards from `MockDataEngine` |
| TradingView professional charts + indicators | ✅ | `components/tradingview/` + lightweight-charts |
| Native sandbox + virtual capital + paper orders | ✅ | `SandboxControls` (capital + place paper order) |
| Trade journal | ✅ | `TradeJournalTool` + write path on executed orders |
| Multiple built-in strategies | ✅ | 132 runnable by name (`ALL_STRATEGIES` + `STRATEGY_REGISTRY` + `BUILTIN`); 41 selectable in the Lab picker |
| Option-analysis tabs (GEX / IV-smile / max-pain / OI-profile) | ✅ | Live option chains via OpenAlgo; honest sample fallback |
| Analytics widgets (VWAP / multi-timeframe / correlation pairs / correlation matrix) | ✅ | Live via `/api/v1/history` + screener analysers (`/v1/analytics/*`, `/api/v1/analytics/correlation`); honest "Live"/"Sample data" badge |
| IV-smile-derived widgets (IV skew / Greeks heatmap) | ✅ | Sourced from the live IV-smile feed (`getFtIVSmile`); greeks Black–Scholes-derived (shared with GreeksSurface); pure unit-tested transforms; honest "Live"/"Sample data" badge |
| Vol-surface, straddle-PnL analysis | 🟡 | Honest sample only (need multi-expiry / candle source) |

## Data & Infra

| Item | Status | Notes |
|---|---|---|
| Historical download + time-remaining + safety monitor | ✅ | `HistoricalDownloadPanel` (ETA, free-disk, refused/aborted) |
| Live tick capture to storage | ✅ | `TickRecorder` (opt-in via `FLINTTRADE_TICK_CAPTURE`) |
| Daily DB optimise + tick retention | ✅ | Nightly cron (CHECKPOINT/ANALYZE + prune); scheduler started |
| Per-broker customisable API rate limits | ✅ | Config + live-apply UI |
| Live order-flow footprint | ✅ | Aggregator fed from the tick stream (Lee-Ready side classification); honest synthetic fallback |
| Latency observability (per-broker p50/p95/p99) | ✅ | In-memory `LatencyTracker` fed by the live order path → `/api/v1/latency/stats` → MonitoringSection `LatencyPanel` + ObservabilityDashboard; regression-tested |
| Gated-order-path latency benchmark | ✅ | Tripwire test measures `gate_order → BrokerRouter` overhead against a mocked broker (real measured ms, generous ceiling) |
| Persisted DuckDB latency store (histogram + slowest-N) | 🟡 | `LatencyMonitor` built + unit-tested, admin endpoints dev-only; not yet fed by the production order path (`PLAN.md` two-store dedup) |

## System Components

| Item | Status | Notes |
|---|---|---|
| Account Manager (brokers + daily reauth + OpenAlgo state) | ✅ | `AccountStatusPanel` ↔ `/accounts/status` (live ping); tested |
| Profile Manager (in unified settings, quick-settings + profile button) | ✅ | `ProfileSection`; both entry points tested |
| Notification System (central manager, drives action) | ✅ | NotificationCentre + dispatchers + remediation actions + e2e test |
| Unified Settings | ✅ | `SettingsRoute`, 19 sections, deep-linkable |

## Automation & Multi-Account

| Item | Status | Notes |
|---|---|---|
| Automate pillar (webhooks / flow builder / schedules / monitors / Telegram) | ✅ | `/automate` route → `AutomateRoute` (TradingView/ChartInk webhooks, flow builder, scheduler, kill-switch indicator), backed by the webhooks + automation packages |
| Ditto multi-account mirror (account mirroring / margin / trailing SL / risk manager) | ✅ | `/ditto` route + backend `/ditto/*` (`operations_routes.py`); natively reimplemented AlgoMirror patterns |
| Invest & Learn routes | ✅ | `/invest` (mutual funds / SIP / net worth) and `/learn` (guided learning) protected routes |

## Known backlog (built-but-unreachable / referenced-not-built / blocked)

| Item | Status | Notes |
|---|---|---|
| SmartOrderRouter (liquidity-aware TWAP slicing) | ✅ | Wired end-to-end: `POST /api/v1/orders/smart-route` (background job + live polling) → every child order independently traverses SafetySystem → `gate_order` → `BrokerRouter` via `GatedChildExecutor`; "Smart Order" terminal widget; OFF by default (`brokers.smart_routing.enabled`), live-mode only |
| Analytics endpoints: VWAP bands / pairs / MTF | ✅ | Compute endpoints built + tested **and now reached by their widgets** — live intraday/daily bars via `getHistory`, honest sample fallback |
| Excel export (browser download) | ✅ | Streaming `/export/download` + `downloadExcel` + "Export to Excel" button in the Positions widget (Notification System feedback) |
| Excel portfolio report (browser download) | ✅ | Streaming `/portfolio/report/download` + `downloadPortfolioReport` + "Portfolio Report" button in the Holdings widget (Positions+Holdings+Summary; Notification System feedback) |
| Excel import (browser upload) | ✅ | Multipart `/import/upload` + `uploadExcel` + Settings → Data watchlist import (feeds the historify download watchlist; Notification System feedback) |
| Download-watchlist manager UI | ✅ | Settings → Data: list / add / remove the symbols the bulk downloader fetches (was previously API-only — fresh installs had no way to populate it) |
| Historical option-chain (`getHistoricalChain`/`getHistoricalExpiries`) | ✅ | "Historical Chain" widget — archived expiries → grouped CE/PE chain; honest empty state |
| Position sizing (Fixed % / Kelly / ATR) | ✅ | `PositionSizingWidget` computes all three methods correctly client-side (no backend round-trip — pure calculator, keeps latency low). The `calculatePositionSize` API client is for external callers, not a gap |
| Stock / fundamentals screener | ✅ | `StocksTab` (Invest route) → `useStockScan` → `/v1/stocks/scan`; curated large-cap fundamentals (disclosed as a fixed point-in-time snapshot). The separate `/screener/fundamental/*` clients are a dead duplicate (no consumers) |
| Credential rotation (`rotation/status|schedule|rotate-now`) | ⛔ | **Scaffold, intentionally NOT mounted** — `CredentialsRotator._do_refresh/_do_rotation` only record a timestamp (no real token refresh / key rotation); mounting it would surface a fake "rotated successfully". Real rotation needs per-broker re-auth wired against the native adapters' live broker sessions (pending live-credential testing). Tracked planned-but-not-built |
| Native-SDK **order execution** (R13/R14) | 🟡 | Dhan is the only active native SDK pin today; Upstox/Kotak Neo are deliberately placeholder-pinned until approval evidence is complete, and Kotak Neo is blocked on upstream licence clearance. |
| n8n bridge (health / workflows / webhook trigger) | ✅ | Automate → "n8n Bridge" section (advanced skill tier) wires all five clients (health badge, activate/deactivate with surfaced failures, manual webhook trigger); honest offline + missing-API-key states; `N8N_HOST` is read by the bridge and documented with `N8N_API_KEY` in `.env.example` |
| Overscoped / dead frontend clients | — | Admin user-CRUD (single-principal app → out of scope), QuestDB browser-REST, OTP pair — removal candidates |

---

_Maintained as part of the usability campaign. When you build, wire, or test one
of the 🟡 / ⛔ items, move it to ✅ here in the same change._
