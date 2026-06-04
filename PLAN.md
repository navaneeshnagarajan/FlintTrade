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

## In flight — 2026-06-05 post-copy remediation

Driven by the post-copy audit (0 critical, 2 high, 18 medium). See the audit report + `.local/dev-logs/2026-06-05-postcopy-recovery-audit.md`.

- [ ] Real defects: Telegram `/kill` await bug, docker-compose health probe + terminal build, preset/admin-user API `/api/v1` prefix, OrderLadder fabricated-price guard, risk-status ranking, `NotImplementedError`→501.
- [ ] Confirmed-dead cleanup: `portfolio_optimizer` twin, 4 screener `_analytics` twins, duplicate `whatsapp_alerter`/`openclaw_bridge`, orphan `scanner_service`, duplicate `/api/v1/errors` + `/api/v1/health`, stale `.gitignore`/`.dockerignore` paths, `flint.toml [sebi]` overscope flags, `packages/ditto/` debris.
- [ ] Honest-degradation of maintainer-deferred surfaces (truthful "not yet available" states, no fabricated `active:true`).
- [ ] Docs reconciliation to the 4-way nest (CLAUDE.md/AGENTS.md/templates, `package-purposes.yml`, DEVELOPER_GUIDE/ARCHITECTURE/API/USER_GUIDE, counts).

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
- [ ] Wave 1 — **Dhan** (skeleton exists; long-lived JWT + sandbox). Add fail-closed unit test for the gated skeleton.
- [ ] Wave 2 — **Upstox** (OAuth daily). File not yet created.
- [ ] Wave 3 — **Kotak Neo** (TOTP + MPIN). File not yet created.
- [ ] Wave 4 — **IndMoney** (SDK availability needs an audit sub-spec first). File not yet created.
- [ ] Community wave — **Zerodha** (`pykiteconnect`) — no maintainer-owned account; ships on contribution.
- [ ] Build `flinttrade_gateway/reconciliation.py` (`ReconciliationReport` per contract §14; adapters' `reconcile()` currently `NotImplementedError`).
- [ ] Add the functional `OpenAlgoAdapter` to `tests/brokers/test_base.py` ABC-enforcement parametrisation.

### 3. AI / analytics backends (wire or keep demo-honest)
- [ ] `ai/sentiment/summary`, `ai/sentiment/tickers`, `ai/regime` backend routes (panels currently 404 → honest demo state in the interim).
- [ ] Wire `OrderFlowAggregator` (`ORDERFLOW_AGGREGATOR`) to the tick pipeline — Order Flow widget currently serves synthetic data.
- [ ] Invoke `SmartOrderRouter` (liquidity-aware TWAP slicing) from the smart-order path, or label it experimental.
- [ ] Register or delete `order_analytics_bp` (`/analytics/execution`) and `strategy_comparison_bp` (`/backtest/compare`).

### 4. Data layer
- [ ] Finish the journal DuckDB → SQLite + FTS5 migration (data-layer spec §1.1/§6): add `flinttrade_journal/db.py`, switch `trade_journal.py` off DuckDB (migration script + `disable_journal_triggers` already exist but have no runtime consumer).

### 5. Consolidation (lower priority)
- [ ] Consolidate the two OI engines (`oi_analysis` vs `oi_analytics`, both routed) onto one canonical module/blueprint.
- [ ] Pick one backing store for traffic/latency stats (`monitoring_routes` in-memory vs `infra_routes` DuckDB-persisted).

### 6. Test / CI gaps
- [ ] Run `TradeIdeaWidget` tests in an isolated raised-heap CI step (currently excluded from all shards; OOMs at 4 GB).
- [ ] Confirm `nightly-cross-platform.yml` exercises `test_secure_file.py` on `windows-latest` (Windows ACL hardening has no per-push guard; it is validated only on the weekly cross-platform run).
- [ ] Begin tagging tests with `unit`/`integration`/`slow` markers (registered but used by zero tests) or drop the staged-execution language.
- [ ] Drop `flinttrade-design/**` from `test.yml`/`supply-chain.yml` `paths-ignore` (it silently skips the baseline-verification job that consumes `flinttrade-design/baselines`).

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
