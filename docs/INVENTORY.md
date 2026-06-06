# FlintTrade Feature Inventory

This is the build-status inventory the project's roadmap calls for: every mission
pillar and feature, categorised as **(a) built & working**, **(b) built but
untested or only partially wired**, or **(c) referenced but not built / blocked**.
It is a living document — update it in the same change that moves a feature
between buckets.

`v0.6.0-alpha` is not production ready. The one feature that genuinely *cannot*
be completed inside this repository is native-broker **order execution** (the
real Dhan/Upstox/Kotak SDKs are not present — the pins in `brokers.lock` are
`PLACEHOLDER`); everything else below is in-repo work.

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
| — Kotak Neo: zero-brokerage execution | ✅ | `brokerage_free` + `low_cost_execution` use-case |
| Native adapters (Dhan/Upstox/Kotak): identity, capabilities, **data** facades | 🟡 | Gated SDK-free skeletons; e.g. Upstox intraday facade present; mapping confirmed-at-activation |
| Native adapters: **order execution** end-to-end (R13/R14) | ⛔ | **Externally blocked** — real broker SDKs absent. The gated path they plug into (`SafetySystem → gate_order → BrokerRouter`) is built + tested |
| Multiple brokers per account, per-broker rate limits | ✅ | `BrokerRateLimiter` + live-apply UI (Account Manager) |

## AI Agent

| Item | Status | Notes |
|---|---|---|
| Connect to any model — cloud providers | ✅ | OpenAI/Anthropic/Gemini/Groq/Mistral/… via `LLMProvider` + `LLMSection` |
| Local models — Ollama, LM Studio, Hermes | ✅ | First-class providers in backend + settings UI |
| OpenClaw agents | ✅ | Control-plane widget (deploy / stop / logs) |
| Obsidian vault | ✅ | Read-only browser widget + agent vault context |
| Create strategies | ✅ | StrategyBuilder (legs / payoff / margin / Pine) |
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
| Ditto multi-account mirror (copy-trading / margin / trailing SL / risk manager) | ✅ | `/ditto` route + backend `/ditto/*` (`operations_routes.py`); natively reimplemented AlgoMirror patterns |
| Invest & Learn routes | ✅ | `/invest` (mutual funds / SIP / net worth) and `/learn` (guided learning) protected routes |

## Known backlog (built-but-unreachable / referenced-not-built / blocked)

| Item | Status | Notes |
|---|---|---|
| SmartOrderRouter (liquidity-aware TWAP slicing) | 🟡 | Built + unit-tested; not routed — wiring it is a **safety-critical** new order path (must mint a `SafetyContext` through the gate) |
| Analytics endpoints: VWAP bands / pairs / MTF | ✅ | Compute endpoints built + tested **and now reached by their widgets** — live intraday/daily bars via `getHistory`, honest sample fallback |
| Excel export / import (`exportToExcel`, `importFromExcel`, `createPortfolioReport`) | 🟡 | Backend built + tested; server-side file generation — no browser button yet |
| Historical option-chain (`getHistoricalChain`/`getHistoricalExpiries`) | 🟡 | Backend built; no widget consumes it |
| Fundamentals screener (search / screen / detail) | 🟡 | Backend built + tested; no UI surface |
| Native-SDK **order execution** (R13/R14) | ⛔ | **Externally blocked** — real broker SDKs absent |
| Overscoped / dead frontend clients | — | Admin user-CRUD (single-principal app → out of scope), n8n client, QuestDB browser-REST, OTP pair — removal candidates |

---

_Maintained as part of the usability campaign. When you build, wire, or test one
of the 🟡 / ⛔ items, move it to ✅ here in the same change._
