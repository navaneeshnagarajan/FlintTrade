# FlintTrade Feature Inventory

This is the build-status inventory the project's roadmap calls for: every mission
pillar and feature, categorised as **(a) built & working**, **(b) built but
untested or only partially wired**, or **(c) referenced but not built / blocked**.
It is a living document — update it in the same change that moves a feature
between buckets.

`v0.6.0-beta.8` is not production ready. The native adapter code for the five
founder brokers (Dhan / Upstox / Kotak Neo / INDmoney / Groww) is present and
mock-tested. Dhan and Upstox are the current connectable native set; INDmoney
is read-verified with a locally verified fail-closed planner, but remains disabled
until restart-time regular/smart-parent cancellation can be resolved authoritatively
and a broker-atomic reduce-only close primitive plus funded/live-market order-safety
proof exist. Kotak Neo and Groww are built and catalogued but stay
`connectable=false`; Kotak Neo's fail-closed planner is locally verified but its
live login/read and order-safety proofs remain, while Groww retains its remaining live blockers. Groww's
official `growwapi` SDK is pinned for attestation/reference parity while the
adapter keeps using FlintTrade's tested REST transport; the latest key-secret
probe proves login/account reads but still lacks broker-side market-data/API
permission, static IP, and order-safety evidence.
INDmoney is the only REST-only native with no SDK pin; its dashboard token resets
at the daily 06:00 IST cycle. INDstocks' own FAQ advertises `indstocks-sdk`, but
PyPI and npm currently have no matching package, so the adapter stays REST-native
until a real SDK distribution can be pinned.
Broker SDK source/artifact mirrors can be refreshed into the gitignored
`.local/sdk-audit/` cache with `uv run python scripts/sync_broker_sdk_refs.py --fail-on-drift`;
tracked runtime installation still comes only from `uv.lock` and `brokers.lock`.
Closed-market/no-funds verification does not prove funded live order execution.

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
| OpenAlgo bridge adapter (orders + market data) | ✅ | First-class optional bridge path; ~45 endpoints |
| Smart routing suggestions | ✅ | Capability metadata + recommendation engine + Account-Manager UI |
| — Dhan: rolling-options history + documented L20 depth feed | 🟡 | Rolling-options history is encoded in routing capabilities; Dhan's L20 depth remains feed-only until FlintTrade wires a runtime depth snapshot bridge (`market_depth_runtime_ready=false`). |
| — Upstox: historical-data edge | ✅ | `historical_max_lookback/candles` capabilities |
| — Kotak Neo: low-cost execution metadata | ✅ | `brokerage_free` + `low_cost_execution` use-case |
| Native adapters (Dhan/Upstox/Kotak Neo/INDmoney/Groww): identity, capabilities, order + **data** surfaces | 🟡 | Adapter and mapping code is present and mock-tested. Dhan and Upstox are connectable after live verification and emergency-planner coverage. INDmoney's fail-closed planner is locally verified but it remains coming soon pending an authoritative restart-time regular/smart-parent discriminator, a broker-atomic reduce-only close primitive, and a funded/live-market order-safety proof. Kotak Neo's pinned-SDK-grounded planner is locally verified; live login/read and order-safety proof remain. Groww retains its documented live blockers. |
| Native adapters: **order execution** end-to-end (R13/R14) | 🟡 | The gated path they plug into (`SafetySystem → gate_order → BrokerRouter`) is built + tested. Generic terminal place/modify/cancel now route to the active native account when no OpenAlgo key is configured, but funded live native order placement remains unproven because verification used no-funds/closed-market accounts. |
| Multiple brokers per account, per-broker rate limits | ✅ | `BrokerRateLimiter` + live-apply UI (Account Manager) |

## AI Agent

| Item | Status | Notes |
|---|---|---|
| Connect to any model — cloud providers | ✅ | OpenAI/Anthropic/Gemini/Groq/Mistral/Cerebras/… via `LLMProvider` + `LLMSection` |
| Local models - managed Ollama, Hermes, custom endpoints | ✅ | Ollama runtime is installed on demand with a pinned hash and controlled from Settings; external endpoints remain available through generic providers |
| AI agent backends | ✅ | `agent_backends` registry + AI Backends widget — Claude Code (API/OAuth), Cerebras, Codex (streaming), Hermes/Antigravity (catalogued); replaced the OpenClaw bridge |
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
| Trading + dashboard widgets (101 registered; see `widgetFactory.tsx` for the count of record) | ✅ | Registered in `widgetFactory`, co-located tests |
| Screens: welcome / dashboard / explore / demo | ✅ | Demo mode feeds widgets + dashboard cards from `MockDataEngine` |
| TradingView professional charts + indicators | ✅ | `components/tradingview/` + lightweight-charts |
| Native sandbox + virtual capital + paper orders | ✅ | `SandboxControls` (capital + place paper order) |
| Trade journal | ✅ | `TradeJournalTool` + write path on executed orders |
| Multiple built-in strategies | ✅ | 132 runnable by name (`ALL_STRATEGIES` + `STRATEGY_REGISTRY` + `BUILTIN`); 41 selectable in the Lab picker |
| Option-analysis tabs (GEX / IV-smile / max-pain / OI-profile) | ✅ | Live option chains use strict exchange, expiry, row, Greek and lot-size provenance through the configured broker path; incomplete or contradictory inputs fail closed to a labelled sample/unavailable state |
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
| Credential rotation (`rotation/status|schedule|rotate-now`) | ✅ | **Mounted (Phase 1 G5)** behind the G9 operator-session write guard. `CredentialsRotator` runs over `flinttrade_core.native_rotation.NativeSessionRefresher` — a real per-selector `refresh_token` hook (Dhan renew-in-place via `RenewToken`, vault-credential replay for the rest, raises on failure so `rotate-now` reports honestly). Active registered native adapters get the daily 08:05 IST refresh job (armed on the serve path); stale coming-soon selectors such as Kotak Neo do not schedule false refresh work. |
| Native-SDK **order execution** (R13/R14) | 🟡 | Dhan and Upstox SDK-backed native paths plus INDmoney, Kotak Neo, and Groww REST/native writes are mapped and gated; INDmoney, Kotak Neo, and Groww remain not connectable. INDmoney's fail-closed emergency planner is locally verified, but restart-time regular/smart-parent discrimination, a broker-atomic reduce-only close primitive, and funded/live-market order-safety proof remain. Kotak Neo's fail-closed planner is locally verified, but live login/read and order-safety proof remain. Groww now has approved-key login/account-read proof but still needs market-data/API permission, static-IP, and order-safety proof before promotion. Funded live order placement remains unproven until market/funds conditions allow a live broker write probe. |
| n8n bridge (health / workflows / webhook trigger) | ✅ | Automate → "n8n Bridge" section (advanced skill tier) wires all five clients (health badge, activate/deactivate with surfaced failures, manual webhook trigger); honest offline + missing-API-key states; `N8N_HOST` is read by the bridge and documented with `N8N_API_KEY` in `.env.example` |
| Overscoped / dead frontend clients | — | Admin user-CRUD (single-principal app → out of scope), QuestDB browser-REST, OTP pair — removal candidates |

---

_Maintained as part of the usability campaign. When you build, wire, or test one
of the 🟡 / ⛔ items, move it to ✅ here in the same change._
