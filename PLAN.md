# FlintTrade — Development Roadmap

> Forward-looking roadmap: what's built, what's in flight, what's planned-but-not-built.
> Read this + `CLAUDE.md` at the start of every session.
> Design specs: `.local/specs/flinttrade-design/` · Design log: `.local/specs/flinttrade-design/DESIGN_LOG.md`
> Latest audit: `.local/audits/audit-2026-06-05-postcopy-restructure.md`
> Historical completion log (pre-v0.6.0 migration): `templates/agent-context/PLAN.md.template`

---

## Current state — v0.6.0-alpha

- **Version:** `v0.6.0-alpha` (alpha restructure; not production-ready — see `disclaimer.md`).
- **Structure:** fat-core 4-way nest under `packages/` — 17 surfaces:
  - `core/` → core, data, historical, indicators (Python) · ticks (Rust/PyO3) · design-system (TS)
  - `services/` → engine, screener, backtest, ai, ditto, automation, journal (Python)
  - `integrations/` → gateway, webhooks (Python)
  - `apps/` → terminal (React/Vite) · site (Next.js/fumadocs)
- **Headline feature (verified solid):** selector-bound principal + gated execution — every reachable live order traverses `SafetySystem` L1–L5 → `gate_order()` (one-shot HMAC `SafetyContext`) → `BrokerRouter` (re-HMAC + field match + ACL) → adapter. No reachable bypass; secrets file-backed + hardened; log redaction disciplined.
- **Broker connectivity:** the **OpenAlgo bridge adapter** is the one functional adapter (forwards place/modify/cancel/reads/quotes to OpenAlgo across 32 brokers). Native SDK adapters are gated skeletons (see roadmap).
- **Modes:** Explore / Practice / Live, server-side JWT-claim enforcement; Practice routes to the native SandboxEngine.
- **Auth:** argon2id, Fernet-encrypted TOTP, JWT (daily IST expiry + jti revocation), HMAC webhooks.
- **Tests/CI:** see `changelog.md` + `docs/CI.md` for current counts and the 7-job per-push matrix. (Re-verify locally with `pytest --collect-only` after `uv sync` + `pnpm install`.)

---

## Shipped — 2026-06-05 post-copy remediation (commit `da32fa0a`)

Driven by the post-copy audit (0 critical, 2 high, 18 medium). See the audit report + `.local/dev-logs/2026-06-05-postcopy-recovery-audit.md`.

- [x] Real defects: Telegram `/kill` await bug, docker-compose health probe + terminal build, preset/admin-user API `/api/v1` prefix, OrderLadder fabricated-price guard, risk-status ranking, `NotImplementedError`→501.
- [x] Confirmed-dead cleanup: `portfolio_optimizer` twin, 4 screener `_analytics` twins, duplicate `whatsapp_alerter`/`openclaw_bridge`, orphan `scanner_service`, duplicate `/api/v1/errors` + `/api/v1/health`, stale `.gitignore`/`.dockerignore` paths, `flint.toml [sebi]` overscope flags, `packages/ditto/` debris.
- [x] Honest-degradation of maintainer-deferred surfaces (truthful "not yet available" states, no fabricated `active:true`).
- [x] Docs reconciliation to the 4-way nest (CLAUDE.md/AGENTS.md/templates, `package-purposes.yml`, DEVELOPER_GUIDE/ARCHITECTURE/API/USER_GUIDE, counts).

## In flight — 2026-06-05 usability campaign (branch `goal/usability-campaign-2026-06-05`)

- [x] Restore terminal typecheck + build (shadcn primitives imported individual `@radix-ui/react-*` packages never declared in package.json → migrated to the unified `radix-ui`; 87 TS errors → 0; `vite build` green). Note: `test.yml`'s `node-core-tests` job *does* gate `tsc --noEmit` + `run build`, so this would have failed CI — it went unnoticed only because Actions is currently disabled on the account (Trust & Safety abuse flag; founder support ticket). No CI change needed.
- [x] Native broker scaffolding + multi-broker suggestions (see §2): `brokers/upstox.py`, `brokers/kotakneo.py` (doc-grounded gated skeletons), `recommendations.py` "which broker for what" engine + `GET /api/v1/broker/recommendations`.

---

## Planned but not built (the roadmap)

### 1. Single enforced execution channel — finish gating every order path
The gate is built and the OpenAlgo bridge dispatches through it. These dormant/deferred paths must be routed through `gate_order` → `BrokerRouter` (mint a per-leg/per-account one-shot `SafetyContext`, `actor_type='agent'`/`'external_intent'`) **before** they are wired live:
- [ ] Basket / split / options-strategy executors (`engine/order_routes.py` per-leg dispatch currently uses `OpenAlgoClient` directly) — then wire `BASKET_EXECUTOR`/`SPLIT_EXECUTOR` in `create_flask_app`.
- [ ] Bracket service (`BRACKET_SERVICE` unwired) + strategy runner (`STRATEGY_RUNNER`/`CRON_SCHEDULER` unwired; scheduler currently stored under `SCHEDULER`).
- [ ] Ditto `PositionMirror` engine (wire into `/ditto/mirror/*`, inject `BROKER_ROUTER` + `actor_id`; drop the httpx fallback once every deployment injects a router).
- [ ] ChartInk webhook auto-trading (`init_webhook_routes()` + gated `_handle_place_order`; keep `actor_id` stable as `external_intent:chartink`, fold `scan_id` into audit metadata not the ACL principal).
- [ ] Fat-core agents — `wheel_live.WheelStrategy` and `autonomous_agent` place via `OpenAlgoClient` directly; route through the gate + register behind the gated runner.
- [ ] Extend `gateway/tests/test_no_legacy_order_path.py` AST/grep guard to also fail on these modules and any MCP-bridge handler.

### 2. Native broker SDK adapters (maintainer-owned accounts first)
Contract is `broker-adapter-contract` spec §3. Prerequisites: build `flinttrade_engine/algo_tag_guard.py` (per-exchange ops counter + `algo_id` relay) and runtime `flinttrade_core/broker_sdk_attest.py` (`attest_all()` + hourly `attest_loop()` → order-halt) before any adapter advertising `algo_tag_required=True` goes live.

> **SDK/docs currency check (2026-06-05, adversarially verified — full report: `.local/reference/broker-currency-check-2026-06-05.md`):**
> Dhan **dhanhq 2.2.0** = latest (pin exact; API server at feature-set v2.5; static-IP required on order APIs; 20-/200-level depth feeds → `DhanCaps.depth_levels=L20`). Upstox **upstox-python-sdk 2.27.0** = latest (build against **v3** classes; V3 protobuf feed; static-IP + `X-Algo-Name` enforced 2026-04-01; populate `brokers.lock`). Kotak Neo → bump **2.0.0 → v2.0.1** (git-pinned `Kotak-Neo/Kotak-neo-api-v2@v2.0.1`; **no PyPI package**; v2.0.1 adds MCX + MTF). IndMoney = **public REST/WS API exists (`api.indstocks.com` v1) but NO official SDK** — hand-roll a REST+dual-WS client; create `.local/reference/broker-docs/indmoney/`. Zerodha = official MIT SDK **kiteconnect 5.2.0** DOES exist (Kite Connect v3; depth 5×5 only; no BO).
- [x] Wave 1 — **Dhan** (skeleton; long-lived JWT + sandbox; doc-grounded `DHAN_CAPABILITIES`).
- [x] Wave 2 — **Upstox** (`brokers/upstox.py` gated skeleton + doc-grounded `UPSTOX_CAPABILITIES`; OAuth daily). Live bodies TODO behind SDK attestation.
- [x] Wave 3 — **Kotak Neo** (`brokers/kotakneo.py` gated skeleton + doc-grounded `KOTAKNEO_CAPABILITIES`; MPIN+TOTP; zero-brokerage `brokerage_free`). Live bodies TODO behind SDK attestation.
- [ ] Wave 4 — **IndMoney / INDstocks** — verified (2026-06-05): a public REST+dual-WS API exists (`api.indstocks.com` v1, docs `api-docs.indstocks.com`) but **there is NO official SDK** (the advertised `indstocks-sdk` pip/npm packages 404). Build a hand-rolled REST+WS client; auth = 24h manual Bearer token + static-IP whitelist. File not yet created.
- [ ] Community wave — **Zerodha** (`kiteconnect` **5.2.0**, official MIT SDK — confirmed to exist; Kite Connect v3; depth 5×5 only; no BO) — no maintainer-owned account; ships on contribution.
- [x] **Multi-broker suggestions** ("which broker for what"): `recommendations.py` ranks brokers per use-case from declared `Capabilities` (zero-brokerage, depth, options, historical, streaming, throughput, advanced orders); `GET /api/v1/broker/recommendations`. UI wiring into the multi-broker setup screen is TODO.
- [ ] Live adapter bodies (login/refresh/place/modify/cancel/reads/quotes/historical/option_chain/stream) — gated behind SDK attestation; verifiable only against live SDKs/creds.
- [~] Reconciliation: the comparison ENGINE already exists and is tested — `flinttrade_engine/reconciliation.py` (`ReconciliationEngine.reconcile_positions/orders` + `BackgroundReconciler`, a 60s async loop detecting drift incl. `CLOSED_MANUAL`). It is NOT wired into the app, and wiring it live is blocked by two real prerequisites, not a quick task: (1) a flinttrade-side net-position ledger INDEPENDENT of the broker (today positions come from OpenAlgo, so "broker vs local" would compare the bridge to itself — meaningless; the trade journal records fills but nothing aggregates them into a live position view); (2) native adapters live (reconciliation only has signal when FlintTrade holds its own position view distinct from the broker's). Until both exist, wiring `BackgroundReconciler` would flood `MISSING_IN_LOCAL`/`CLOSED_MANUAL` noise — worse than not wiring it. The adapter ABC `reconcile()` stub stays `NotImplementedError` (do NOT add a parallel `flinttrade_gateway/reconciliation.py` — it would duplicate the working engine model).
- [ ] Implement real credential rotation + mount `rotation_routes`. `CredentialsRotator` + the `rotation/status|schedule|rotate-now` blueprint are built and tested, but `_do_refresh/_do_rotation` are SCAFFOLDS (record a timestamp only — no real token refresh / key rotation), so the blueprint is **intentionally left unmounted** (mounting it would surface a fake "rotated successfully"). Real rotation needs per-broker re-auth (native adapters → their SDKs). Then add an Account Manager UI to drive it.
- [x] Add the functional `OpenAlgoAdapter` (+ upstox/kotakneo) to `tests/brokers/test_base.py` ABC-enforcement parametrisation.

### 3. AI / analytics backends (wire or keep demo-honest)
- [x] `ai/sentiment/summary`, `ai/sentiment/tickers`, `ai/regime` backend routes — registered and served; the regime route additionally falls back to free daily OHLCV for disconnected/Explore users.
- [x] Wire `OrderFlowAggregator` (`ORDERFLOW_AGGREGATOR`) to the tick pipeline — instantiated in the app factory and fed per-tick by the TickRecorder (Lee–Ready aggressor classification); the Order Flow widget shows real delta while tick capture runs, honest synthetic otherwise.
- [x] Invoke `SmartOrderRouter` (liquidity-aware TWAP slicing) — wired at `POST /api/v1/orders/smart-route` (background job + polling) with every child order independently gated (`GatedChildExecutor`: SafetySystem → `gate_order` → `BrokerRouter`); "Smart Order" widget in the terminal. OFF by default via `brokers.smart_routing.enabled`, live-mode only.
- [x] Register or delete `order_analytics_bp` (`/analytics/execution`) and `strategy_comparison_bp` (`/backtest/compare`) — both registered.

### 3b. Safety depth (cross-path, found by the 2026-06-10 session audit)
- [~] Thread live portfolio state into `SafetySystem.check_order`:
  - [x] **L2 (position count + margin %) on the manual order path** — `_dispatch_live_order` now gathers live positionbook + funds (`_gather_l2_state`, best-effort: a fetch hiccup yields empty state so L2 enforces nothing rather than blocking — availability never degraded) and feeds them in, so "already at max positions" and "margin usage exceeds limit" actually fire. L2's quantity parse hardened to tolerate float-strings.
  - [x] **L2 on the smart-route / agent (GatedChildExecutor) paths** — `GatedChildExecutor` takes an async `portfolio_state_provider` it awaits before each child's `check_order`; smart routes gather ONCE and cache (a route is bounded), the agent fetches FRESH per order (long-lived session, low frequency). Best-effort (a failing provider → empty state → L2 no-op, never a blocked order). `gather_portfolio_state` is OpenAlgo-scoped like the manual path.
  - [ ] **L4 (daily P&L)** — NOT fed from the hot path on purpose: L4 *latches* its kill switch, and CLAUDE.md notes broker PNL is unreliable for some brokers, so a noisy per-order daily_pnl could spuriously latch the breaker. Needs a reliable LOCAL daily-P&L (computed from the tradebook) before it can drive L4.
  - [ ] **L3 (net delta / vega)** — needs per-position option greeks (chain data the OpenAlgo bridge does not expose); stays 0 until a greeks source exists (L3 cannot enforce what it cannot measure).
- [ ] Multi-worker (gunicorn ≥2) story for the in-memory job/runner state: the smart-route `_JOBS` cap/dup-guard/cancel and the agent `_RUNNER` single-session slot are process-local, so under >1 worker they are per-worker (cancel can 404 on the non-owning worker). Single-process Waitress (the default) is correct; document or move to a shared store if multi-worker is adopted (auth_state already is DuckDB-backed for the same reason).

### 3c. Frontend↔backend contract audit + backend-features-awaiting-UI (2026-06-10)
A mechanical contract audit (AST route-extract + client-call diff, both directions, adversarially verified) established that **every frontend call resolves to a registered backend route (97/97)** and fixed 8 real divergences the prior thematic audits missed: the audit-log viewer (wrong log), the backtest metrics-card crash (`sharpe`→`sharpe_ratio` + `expectancy`), blank ban reasons, broken webhook delete (`id`/`type` + `<path:>` converter), OI `strike_count` silently dropped, `verifyOtp` missing `broker`, the advisor help-pill 500 (object context), and the volcone widget wired to its real HV backend.

The **inverse** diff (registered routes with no SPA caller) was classified per cluster (`feature-wiring-classify` workflow, evidence-grounded + adversarially verified):
- [x] **Volatility Cone — WIRED** (`f60fb365`): `/v1/analytics/volcone` is real (rolling-HV percentiles); the widget showed sample with a wrong-path comment. Now live HV cone from `getHistory` returns, sample fallback badged.
- [x] **OI analytics — BUILT** (OISignalsWidget, 89th widget): `/v1/oi/analysis` (LB/SC/SB/LU) + `/v1/oi/unusual` (z-score) now have a UI — price-direction-driven signals table + unusual-OI footer, TanStack Query gated on `useBrokerConnected`, sample fallback badged. (`/v1/oi/heatmap` is real but the existing OIHeatmap recomputes the same client-side — consolidate or repoint, see §5.)
- [x] **Portfolio optimiser — BUILT** (PortfolioOptimiserWidget, 90th widget): `/v1/portfolio/optimise` now has a UI — method selector (Markowitz/Max-Sharpe/Min-Variance/Risk-Parity/Equal-Weight), ~1y multi-symbol basket fetch with return series aligned to the common length (the misalignment risk handled), weights + return/vol/Sharpe/diversification, sample fallback. **`/v1/portfolio/frontier` is also surfaced** — the widget renders the efficient frontier as a scatter (vol vs return, selected portfolio marked) from the same aligned return series.
- [x] **Backtest compare — BUILT**: `/api/v1/backtest/compare` (real comparator + inverse-variance optimal blend) now has a UI — the Lab's Results tab keeps every run this session (per strategy) and a "Compare runs" card posts them for side-by-side metrics, the weighted-composite winner, and the suggested blend. A backend contract test pins the exact terminal payload shape. (This also delivers the Results tab's previously-promised "multi-run comparison".)
- **Backtest walk-forward — LEAVE (principled, not built)**: `/v1/backtest/walkforward` only walk-forwards a **built-in buy-and-hold baseline** (custom strategies are programmatic-only per its docstring). A "walk-forward" UI that silently tests only buy-and-hold — not the user's strategy — would MISLEAD (same line drawn on the credential-rotation scaffold: don't ship misleading functionality), and the Lab already surfaces real strategy robustness via `RobustnessCard`. Left unwired by design.
- [x] **Scanner backend — UI BUILT** (ConditionScannerWidget, 91st widget): after the live-fetcher fix, `/v1/scanner/{prebuilt,run}` gained a purpose-built consumer — prebuilt-scan selector with condition chips, run, results table, and a RESPONSE-driven Live/Sample badge (the run response reports whether the backend scanned live broker OHLCV or sample bars). The pre-market Scanner dashboard widget is intentionally untouched (different feature, founder-scoped out). Bonus fix: WidgetPicker's ICON_MAP was missing 38/64 catalogue icons (silent Box fallback) — completed + a sync-pinning test.
- [x] **Economic calendar — WIRED**: the widget now sources events from `/v1/economic/calendar` (bundled sample only as offline fallback). The provider is itself sample-only (no live macro feed), so the honest badge stays — the wiring buys single-source-of-truth: a future live provider lights the widget up with no frontend change.
- **Earnings — feature already wired**: `EarningsCalendarWidget` consumes `/api/v1/earnings/calendar`; the uncalled `by-date`/`by-symbol` routes are redundant query variants of the same sample calendar (API conveniences, not an unbuilt feature).
- **LEAVE (honesty/redundancy):** breadth-history (`/v1/breadth/history` is sample-only; charting fake history beside the REAL `/breadth/current` would blend live and fabricated series), `/api/v1/regime/current` (redundant twin of the wired `/ai/regime` — consolidation §5), `/v1/oi/heatmap` (OIHeatmap computes the same client-side — consolidation §5).
- **Not actionable (verified):** pivots (`PivotPointsWidget` self-computes correctly via `getHistory`, real data when connected; the `/v1/pivots/calculate` route is a redundant duplicate — candidate for removal, low priority), `/api/v1/regime/current` (real macro classifier but needs VIX/DXY/FII inputs the SPA lacks; `/api/v1/ai/regime` IS reachable via `RegimePanel`), TradingView analysis (`/v1/tv/*` real but `tradingview-ta` is an undeclared dep → 502 until installed; no SPA surface).
- `ai/refine-strategy`: real backend, but the frontend client was deliberately removed as dead (`0d9955b5`); re-surfacing is a product decision, not a wiring fix.

### 4. Data layer
- [ ] Finish the journal DuckDB → SQLite + FTS5 migration (data-layer spec §1.1/§6): add `flinttrade_journal/db.py`, switch `trade_journal.py` off DuckDB (migration script + `disable_journal_triggers` already exist but have no runtime consumer).

### 5. Consolidation (lower priority)
- [ ] Consolidate the two OI engines (`oi_analysis` vs `oi_analytics`, both routed) onto one canonical module/blueprint.
- [ ] Pick one backing store for traffic/latency stats (`monitoring_routes` in-memory vs `infra_routes` DuckDB-persisted).

### 6. Test / CI gaps
- [ ] Run `TradeIdeaWidget` tests in an isolated raised-heap CI step (currently excluded from all shards; OOMs at 4 GB).
- [ ] Confirm `nightly-cross-platform.yml` exercises `test_secure_file.py` on `windows-latest` (Windows ACL hardening has no per-push guard; it is validated only on the weekly cross-platform run).
- [ ] Begin tagging tests with `unit`/`integration`/`slow` markers (registered but used by zero tests) or drop the staged-execution language.
- [x] Drop `flinttrade-design/**` from `test.yml` `paths-ignore` — a baseline-only change no longer skips the baseline-verification job + `test_baseline_artifacts.py` that consume those artefacts. Left ignored in `supply-chain.yml` ON PURPOSE: a baseline-CSV change has zero supply-chain relevance, so running dependency scans on it is the waste the right-sized-CI policy forbids.

---

## Future / someday (post-v0.6.x)

Mobile app (`/v0.7.0`), Unsloth QLoRA fine-tuning, social/copy trading (`social_trading.py` is a labelled foundation), blue-green deployment, additional second-wave brokers (Angel One, Fyers, XTS-shared set, Groww, ICICI Breeze, Paytm Money, Sharekhan) on demand/contribution.

---

## Standing constraints

- **no-overscope:** personal-use open-source (operator == user == data principal). No DPDPA / IT-Act-§65B / CERT-In / RBI / grievance / nominee / SDF / vendor ceremony. Only AGPL licence compliance + OpenAlgo-parity observability apply. SEBI personal-use carve-out: register your static IP at your broker (operator action), no FlintTrade-side ceremony.
- **OpenAlgo quirks to work around:** sandbox can send real orders (verify isolation); `closeposition` ignores strategy (track per-strategy); WS drops without heartbeat (ping/pong preserved); PNL wrong for some brokers (compute locally); MCX symbol format inconsistent (normalise via `symbol_utils`); never touch OpenAlgo's SQLite directly.
- **Ports:** terminal 5173 (Vite), FlintTrade backend 5100, OpenAlgo 5000, WS 8765. Never consolidate 5100 with OpenAlgo's 5000–5009 range.
- **Review pipeline:** claude (ultracode multi-agent panels) → maintainer. Codex retired from the loop.

---

*Living roadmap — supersedes the historical completion log in `templates/agent-context/PLAN.md.template`. Tick items as they ship; move shipped features into `changelog.md`.*
