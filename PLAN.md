# FlintTrade — Development Roadmap

> The single roadmap of record. Read this + `CLAUDE.md` at the start of every session; resume from the current phase — never restart planning.
> Standing orders: `.local/AGENT.md`. Audit deliverables: `.local/specs/audit/` (`state-of-repo.md`, `feature-matrix.md`, `reference-map.md`, `gap-map.md`, raw reports in `raw/`). Lessons: `.local/notes/`.
> Gap IDs (G1…G39) refer to `.local/specs/audit/gap-map.md`. Historical pre-v0.6 completion log: `templates/agent-context/PLAN.md.template`; shipped detail: `changelog.md`.

---

## Current state — v0.6.0-beta.1 (ground-truth audited 2026-07-03 @ `edec745e`)

- **Verification baseline (all green locally):** pytest 10,321 passed / 0 failed; ruff clean; `tsc --noEmit` clean; Vitest 3,688 passed; `vite build` green. Desktop release v0.6.0-beta.1 published with all 9 installers.
- **Diagnosis:** the code is high-quality and heavily tested, but the product breaks in the *unwired / unreachable / silently-degraded* layer that unit tests cannot see (`state-of-repo.md`). Auth core, gated execution, the terminal shell, and the desktop package genuinely work; Practice mode, native broker activation, historical downloads, and several live data paths do not.
- **Safety verdict:** no reachable ungated live order path (`raw/xcut-order-paths.md`); intentionally-raw paths are L5 emergencies on shrinking allowlists. The gate chain (SafetySystem L1–L5 → `gate_order`/`gate_broker_write` → `BrokerRouter` → adapter) is real and guard-tested.
- **Brokers:** OpenAlgo bridge live-tested (32-broker catalogue). Natives: Dhan (attestable — dhanhq 2.2.0 pinned), Upstox + Kotak Neo (lock entries PLACEHOLDER; Kotak blocked on upstream licensing), IndMoney (creds-only by design). **Groww: no native adapter yet** (founder broker per the standing goal). Native *activation plumbing* (credential-replay login + capture UI) is unbuilt — see Phase 1.
- **Modes:** Explore/Practice/Live enforced server-side via JWT claims; PIN mints live-unlock; downgrade revoke-then-mint. Frontend never upgrades Explore→Practice (G1) — Practice trading currently unreachable.

## Phase tracker (standing goal, 2026-07-03)

| Phase | Scope | Status |
|---|---|---|
| 0 | Ground-truth audit, docs corrected, PLAN rewritten | **CLOSED 2026-07-03** (see Phase 0 exit evidence) |
| 1 | Auth end-to-end (app + broker), SEBI-correct | not started |
| 2 | Stabilise everything that exists | not started |
| 3 | Build the unmapped reference backlog | not started |
| 4 | Autonomous loop proven in Practice | not started |
| 5 | Distribution + public surfaces | not started |
| 6 | Release + continuous loop | not started |

A phase closes only after: full multi-agent audit → fix everything → clean re-audit, evidence recorded here.

---

## Phase 0 — Ground-truth audit *(closing)*

- [x] 38-agent audit: per-package sweep, doc-claim verification, order-path + auth cross-traces (raw reports in `.local/specs/audit/raw/`).
- [x] Full local verification run (baseline above) + hands-on fresh-install auth run (`.local/notes/phase0-handrun-auth.md`).
- [x] `state-of-repo.md`, `gap-map.md` written; `feature-matrix.md` assembled from the sweep.
- [x] CLAUDE.md stale claims corrected (14 fixes: shards, gitleaks→grep, hash-chain, TA-Lib/Numba, ticks role, DEK wording, adapter asymmetry, platform dirs, MODE_NOT_ALLOWED, heartbeat location, alias files, Python bound, workspace members, package-map roles). AGENTS.md verified accurate. PLAN.md rewritten (this file) per `raw/doc-plan-md.md` §N corrections.
- [x] `reference-map.md` assembled: 374 rows across 8 sources (227 implemented / 86 partial / 17 unmapped / 22 deferred-candidate / 22 n-a), consolidated §3 backlog of 26 items + 23-row partial-gap annex.
- [x] `.local/notes/` seeded: 9 lessons (hands-on auth run, mock-shape drift, silent degrade, comments-claiming-enforcement, prefix-404 class, fail-open order paths, vitest pool=forks, global test-infra reverts, release machine checks) distilled from the audit + 951-commit history mine (`raw/history-lessons.md`).
- [x] **Exit met — re-audit evidence:** two adversarial passes run. Pass 1 (`wf_c5d9ecff`, 7 verifiers, ~270 claims checked) found 1 high (OpenClaw bridge contract → G38), ~10 medium, ~20 low findings — ALL fixed across the five documents (regrades, G38/G39 added, G4/G8/G12/G21/G27/G28 corrected, phase-mapping fixes, CLAUDE.md CI-caveat/imports-rule corrections). Pass 2 (`wf_09735c5f`, 4 verifiers, ~120 claims) came back with **zero refuted and zero high-severity** findings; the residual 5 documentation slips (P20/P22/P23 mapping, G-ID range, HG tracking, hook-file count, AI1–AI3 citation) were applied immediately after. Feature-matrix final: 371 rows — 194 works / 7 verified / 133 partial / 20 broken / 17 stub, all section sums verified programmatically. **Phase 0 closed 2026-07-03.**

## Phase 1 — Auth end-to-end, SEBI-correct

App auth core already works (hands-on verified): setup → password+TOTP login → mode-scoped JWT (next-08:00-IST expiry, jti revocation) → PIN live-unlock → practice downgrade. The work is the seams and the broker side. Full trace: `raw/xcut-auth-flow.md`.

**App-auth seams**
- [x] G1 — Explore→Practice upgrades the JWT server-side. `/auth/mode` now accepts `explore`|`practice` downgrade targets; `lib/modeAuth.ts` centralises the calls; ModeIndicator (Explore→Practice + Live→Practice), LoginRoute (persisted-Practice reconciliation) wired. Hands-on proven: practice JWT places a sandbox order (200 paper fill) where explore is 403. (`.local/specs/auth-phase1/DESIGN_LOG.md`)
- [x] G2 — LockScreen idle PIN-unlock is mode-preserving. `/auth/pin` takes an optional `mode` (default `live`); LockScreen passes the current UI mode so an idle Practice/Explore session never silently mints a Live-unlocked JWT. Backend + frontend tests + hands-on verified.
- [x] G6 — Auth brute-force limiter now actually fires. Root cause: `@auth_bp.record` ran BEFORE the routes were registered (blueprint deferred-function order), so `view_functions` was empty and the deferred `limiter.limit()(view)` wrapped nothing — login/PIN/setup were unthrottled in production, not just in tests. Fix: `install_auth_rate_limits(app)` called from `create_flask_app` after `register_blueprint(auth_bp)`, replacing each auth view with its Flask-Limiter-wrapped form. The two skipped tests now hard-assert the 429 fires (login 6th, setup 4th). Verified: login burst → `[401×5, 429×3]`.
- [x] G8 — Route-prefix regression test shipped (`tests/test_frontend_route_contract.py`): boots the real app factory (dev flag on so admin routes register), extracts every literal `fetch("/ft-api/…")` from the terminal source, strips the prefix like the WSGI middleware, and asserts each resolves to a real (non-SPA-fallback) `url_map` rule. Built-in negative controls reject wrong-prefix/bogus paths. It independently rediscovered G20 (`/v1/rrg/portfolio`), now carried as a shrinking known-gap with a shrink guard.
- [x] G9 — Broker-management write auth ENFORCED: every POST/PUT/DELETE on `/v1/accounts*` + `/v1/auth/*` + `/v1/rate-limits` (gateway_bp), `/api/v1/native/*`, and `/admin/credentials/rotation/*` requires a valid, unrevoked session JWT (any mode) via `require_operator_session()`; gateway consumes it through `app.config["BROKER_MGMT_WRITE_GUARD"]` (dependency direction). Reads keep the loopback allowance; OAuth callbacks stay state-token-protected GETs. Found + fixed in passing: `gatewayApi.ts` sent NO auth headers at all (bare fetch) — now uses the shared `buildHeaders`. Tests: 401-without-JWT, 401-invalid-JWT, reads-stay-open, gateway-guard-in-real-app. (design D5)
- [x] Review DECIDED (D6) — PIN is a re-auth factor, never a session-minting factor: `/v1/auth/pin` now requires a valid session JWT alongside the PIN (all targets). A PIN alone can no longer arm Live from anything that reaches 127.0.0.1, and an expired-overnight session cannot sidestep the daily password+TOTP login — the JWT's next-08:00-IST expiry is exactly the "recent-login freshness" bound. Frontend PIN callers attach the token; expired-session 401s route to the full login.
- [x] G10 (HTTP guard + accuracy) — the SEBI per-second broker-submission cap was already enforced at `BrokerRouter._throttle` (below the gate, every gated order). Added the missing HTTP-layer DoS/fat-finger 429 guard: `@rate_limit` on the 23 core `/orders/*` write routes + smart-route start, `RateLimiter.reset()` + autouse test fixture, a positive enforcement test (429 fires after the 10-token burst), and corrected the false app.py coverage comment. (`.local/specs/auth-phase1/DESIGN_LOG.md`)
- [x] G10 (remainder) — `AlgoTagGuard` WIRED into `BrokerRouter` dispatch (place/modify/cancel/execute_gated, after `_verify_safety`, before `_throttle`): relays the operator's broker-registered algo_id onto the dispatch session + enforces the per-(broker, exchange) per-second algo ceiling for `algo_tag_required` adapters (Dhan/IndMoney). Configured via workspace `brokers.algo_tags[broker].{algo_id,max_orders_per_sec}`; unconfigured brokers keep the adapter/mapping retail defaults. Malformed config fails closed (router None → orders 503); a ceiling breach maps to HTTP 429. 7 router tests + wiring tests + a 429 route test.

**Broker auth (the core build)**
- [x] G3 — **Credential-replay login step SHIPPED** (`flinttrade_gateway/native_login.py`): `establish_native_session` (login → `registry.put_session`, fail-closed) + `establish_native_sessions` (boot loop, per-selector isolation). Wired at boot via `_reestablish_native_sessions` and on-demand via the capture route. 4 unit tests. **Verified LIVE against a real Dhan account** — see G4.
- [x] G4 — **Native capture + activation backend SHIPPED** (`native_account_routes.py`, `/api/v1/native/*`): connect (store creds → register selector + ACL operator in workspace.json → rebuild router → login → session), relogin (daily re-auth), list (+ session status), remove, and a funds/positions/holdings read that exercises the live broker. `configure_broker_router` extracted from `create_flask_app` for runtime rebuild. 5 unit tests. **LIVE-VERIFIED with Dhan**: connect → session established → `funds` returned real account data (live balance + client ID confirmed); positions [] (unfunded). The four-broker native activation the audit found unbuilt now works live for Dhan. Since shipped: Upstox + Kotak Neo SDK activation (brokers.lock pins, operator-cleared licence), the native OAuth connect flow, the in-app connect UI (Settings → Brokers, catalogue-driven), and proper native display names (`kotakneo` alias wart). Remaining: live connect verification for IndMoney/Upstox/Kotak Neo with the maintainer's real accounts (operator action via Settings → Brokers). Postback: broker order-update postback URLs are intentionally unused (localhost can't receive inbound) — WS order feeds are used instead; only the Upstox OAuth redirect_uri (a loopback callback) needs populating.
- [x] G5 — Daily session refresh SHIPPED: `flinttrade_core.native_rotation.NativeSessionRefresher` is the real `refresh_token(broker)` hook for `CredentialsRotator` (renew-in-place via Dhan `renew_token` when a live session exists, vault-credential replay otherwise; failures raise → honest failed RotationResult + `needs_relogin` in the UI). `rotation_routes` now MOUNTED (guarded per G9); 08:05 IST daily jobs scheduled per registered native on an unstarted scheduler that `_run_flask_server` arms (factory stays side-effect-light). BrokersSection: expiry countdown (existing) + one-click Re-authenticate (replay) that falls back to a prefilled connect form when material is stale (`ftApi.native.reloginNativeAccount`).
- [x] G7 — Reconnect realism SHIPPED: adapters declare `replay_credentials()` (Dhan swaps TOTP→minted 24h token; Upstox swaps single-use OAuth code→exchanged token; Kotak Neo drops the stale TOTP; IndMoney static) and `establish_native_session` writes the replayable payload back via `CredentialStore.update_credentials_for` (payload-only, metadata untouched, best-effort). Per-selector login outcomes land in `NATIVE_SESSION_STATUS`; the accounts list + BrokersSection surface `needs_relogin` + the actionable `login_error` (amber) instead of silent boot failures.
- [ ] Dhan native activation end-to-end (the one attestable broker): install pinned SDK, vault creds, live login, session established, reads verified. (Live order testing stays maintainer-armed.)
- [x] Audit wave (2026-07-03): a 30-agent adversarial audit of the G5/G7/G9/G10 + PIN commit found 24 confirmed issues (1 refuted) — ALL fixed (auth reset-token type confusion, AlgoTagLimitError→429 on both gated dispatch paths, stale/`""`-bucket algo-id handling, lenient algo_tags parsing, the ftApi.native double-unwrap that had left the whole connect UI dead in-browser, the idle-lock-vs-session-bound-PIN dead-end, setup-wizard session establishment, and 7 credential-lifecycle bugs). A **re-audit** of that fix commit (5-lens workflow) then found 10 residuals (1 refuted) — ALL fixed too: auth_mode_switch token-type (third mint route), the dead-token probe moved into the shared verify path so interactive Re-authenticate/connect probe too (not just the daily job), transient-tolerant probe, failed-reconnect credential restore + selector-orphan cleanup, and 2 low docstring/dead-field items. Two audit→fix→re-audit rounds; details in `.local/specs/auth-phase1/DESIGN_LOG.md`.
- [ ] **Exit (remaining):** live-verify IndMoney/Upstox/Kotak Neo connect with the maintainer's real accounts → next-day restart proof → clean re-audit of the fixes. Dhan native path + Practice mode are proven; the four-broker connect UI, OAuth, G9/D6 auth, and G5/G7 session lifecycle are built + fully unit/integration-tested.

## Phase 2 — Stabilise what exists

Work the feature matrix (`feature-matrix.md`): fix every *broken*, finish or honestly-degrade every *partial*. Highlights (full inventory in `gap-map.md` Tier 3/4):

- [ ] G17 — Historical: call `DataPipeline.initialise()` on the wired download path; delete or async-fix the dead sync generation (downloader/expiry_manager/free_data kwarg — all demonstrably broken).
- [ ] G18 — Screener live paths: fix `registry.get_option_chain` (missing) + `get_history` signature misuse so OI-signals/RRG/regime/correlation stop silently sample-falling-back when connected.
- [ ] G19/G20 — EarningsCalendar contract (`entries` vs `events`, ignored params); SectorMap Portfolio-RRG route (build `/v1/rrg/portfolio` or remove the tab).
- [ ] G21 — `/ditto/accounts`: never fabricate sample accounts in production.
- [ ] G22 — `ObsidianVault(vault_path)` construction bug (swallowed TypeError; the defect is in core `agent_routes.py:98`, not the ai package).
- [ ] G38 — OpenClaw bridge contract: `openclaw_bridge.py` calls `/api/agents/*` routes that don't exist upstream — fix the client against the real OpenClaw API (or degrade the widget honestly).
- [ ] G39 — ExpiryTracker `capture_snapshot` calls nonexistent `client.optionchain`; HistoricalChain's DB can never populate — fix the client call and add a populate path.
- [ ] G23/G24 — Webhooks: either wire the gated ChartInk dispatch (`init_webhook_routes` + secret provisioning + public-prefix/auth story) or 501 the receiver honestly; fix `/api/v1/webhooks` ops CRUD (`_webhook_server` never set).
- [ ] G25 — Honesty pass: tax sample-as-success (+ TaxTab banner logic), FundingRate/GlobalIndices fake "live", SpreadView fake execute, Chart explore-OHLCV affordance, core broker widgets' demo affordance.
- [ ] G26 — Audit log: implement the hash chain (or stop claiming it everywhere); fix fsync comment.
- [ ] G27/G28 — Feed PnLTracker (or remove routes + widget polling); orderflow `interval` param; `export_trades_csv` end_date.
- [ ] G30 — Telegram: start the polling loop (kill switch reachable) or mark inbound commands unavailable; fix `/positions` alias; parse `/kill` responses (G15).
- [ ] G31 — Finish journal DuckDB → SQLite+FTS5 migration (script currently archives without copying rows).
- [ ] G29 — ticks: re-export the full surface or trim the crate to what's consumed; decide wire-vs-defer (it has zero consumers).
- [ ] G32/G33 — CI test-visibility: generate vitest shards from the tree (no hand-maintained lists); add contract tests for the mock-shape drift class (async-client shape, registry signatures, route existence for widget-called URLs).
- [ ] G34/G35 — secrets-check → real gitleaks (or fix docs + drop the pre-commit claim); `make update` hashed path; full-check OOM conflict; Makefile Windows ticks-tests; cargo-test CI lane.
- [ ] G36 — Docs corrections beyond the big three: docs/CI.md, DEVELOPER_GUIDE (14 claims), ARCHITECTURE edges, COMPATIBILITY endpoint, changelog beta.1 section, package READMEs, flint.toml desktop, site 17→18 + desktop README.
- [ ] Reference-map hygiene items HG2–HG6: stale brokers.lock:10 note (HG2), `.local/specs/native-app-audit` open checkboxes resolved or closed (HG3), ConnectionStep Fast-Refresh export wart (HG4), docs/superpowers stale restructure-completion doc (HG5), lost `.local` evidence-trail pointers regenerated or dropped (HG6). Plus annex P22 (signed release tags) + P23 (check_doc_sync).
- [ ] G37 — Unwired-mass disposition: every built+tested+unreachable module gets wire / delete / defer-with-reason recorded here (candidates list in `state-of-repo.md`).
- [ ] **Exit:** nothing user-visible crashes or silently fakes; feature matrix has no *broken* rows and every *partial* **and *stub*** row is either finished, visibly degraded, or explicitly deferred here; full local verification green; multi-agent audit + re-audit clean.

## Phase 3 — Build the unmapped

Backlog source: `.local/specs/audit/reference-map.md` §3 — the consolidated queue of **26 items**: 7 widgets + 3 broker features + 3 data pipelines build here (Phase 3); the 3 AI-layer patterns (AI1–AI3) belong to **Phase 4** (cited there in the learning-tier bullet); the 6 hygiene/doc items (HG1–HG6) fold into **Phase 2** (HG1 stale-OpenAlgo-wrapper deletion is part of G37; HG2–HG6 are listed as explicit Phase 2 tasks below); 4 items are recorded as **deferred** here (that satisfies the exit criterion for them). The 23-row partial-gap annex items carry their own phase tags per reference-map §3.7 (P20 visual-regression → Phase 5; P22 signed tags and P23 check_doc_sync → Phase 2; P6 must also correct the Depth widget's catalogue copy promising 50 levels that don't exist). Sources mapped: `.local/reference-research/2026-07-02` (OIPulse 53 routes, 1Cliq trade windows, Dhan DEXT3 37 widgets), `2026-07-03` (INDstocks API + Flash + TV, Groww Trade API + 915 terminal + Explore, INDmoney dashboard), `.local` misc/design baselines, and the `~/Documents/GitHub` repos (openalgo, openclaw, hermes-agent, flintsuite, autoresearch, upstox-*, DhanHQ-py, Kotak-neo-api-v2, lightweight-charts, mcp-server-upstox-api).

Known-committed items ahead of the map:
- [ ] **Groww native adapter** (founder broker; official `growwapi` SDK + captured Trade API docs): full doc-grounded surface per the adapter contract, brokers.lock pin, catalogue/native-factory/recommendations/test_base parametrisation, credential capture + replay integration.
- [ ] Zerodha community wave (kiteconnect 5.2.0, official MIT SDK) — ships on contribution; keep deferred.
- [ ] Spec-first rule: every mapped feature gets `.local/specs/<area>/` + `DESIGN_LOG.md` before build; port patterns, never blind-copy.
- [ ] **Exit:** every reference-map row with status `unmapped` or `deferred-candidate` is either implemented or carries an explicit `deferred` entry here with a reason. (`partial` rows are Phase 2 feature-matrix territory, not this exit.)

## Phase 4 — Autonomous loop proven (Practice)

The chain to prove: signal → SafetySystem L1–L5 → `gate_order` → `BrokerRouter` → SandboxEngine fill → journal → learning update, all day, Live blocked.

- [ ] G10 verification under load — the rate limiting built in Phase 1 is exercised by the full-day loop (order bursts throttled on every path, no bypass).
- [ ] G11 — Feed L4 from local tradebook-computed daily P&L (broker PNL unreliable); feed L3 from native option-chain greeks when available.
- [ ] G12 — Close the grep-guard blind spots (`.route_order(`, raw `OpenAlgoClient.modify/cancel_order`, loose `\w*router` regex; add ditto + MCP coverage).
- [ ] G13 — Refactor basket/split/bracket executors through the gate (they'd go live SafetySystem-only if wired today); fix ditto mirror hardcoded `mode='live'`; retire the mirror's ungated httpx fallback.
- [ ] G14 — Sandbox fill realism: feed LTP at dispatch; reject 0.0-price MARKET fills outside tests.
- [ ] Wire the learning tier honestly (reference-map backlog items AI1–AI3): the "self-learning" story (auto_retrain, trade_reflection, memory managers, TradedMemory, SkillRegistry — all library-only today) gets a minimal wired loop: journal → reflection → strategy/parameter update, spec'd first in `.local/specs/`.
- [ ] Full-day simulated run: autonomous agent in Practice for a full trading session (pre-open → close, IST) — orders rate-limited, fills journalled, learning update runs, Live provably blocked (mode guard + no live session), kill switch drill mid-run.
- [ ] G16 — Document/enforce the single-process constraint for in-memory job/runner state (or move to shared store).
- [ ] **Exit:** the loop survives a simulated full trading day with zero safety violations and a complete journal/learning trail; multi-agent audit + re-audit clean.

## Phase 5 — Distribution + surfaces

- [ ] Desktop updater story (currently none): in-app update check against GitHub releases at minimum; install/uninstall verified on macOS (hands-on) + Linux/Windows (CI artefacts + checklist).
- [ ] In-app bug reporting (error log export → GitHub issue template; no telemetry beyond opt-in).
- [ ] Site/docs truth pass to "built, done, or actively building" (G36 remainder): desktop README (fixes the site's 17-vs-18 cascade), sidebar meta, CI.md, USER_GUIDE against the stabilised matrix.
- [ ] make desktop-build verified locally end-to-end on this machine.
- [ ] **Exit:** a new user can install, update, report a bug; public surfaces state only what is true; audit + re-audit clean.

## Phase 6 — Release, then keep looping

- [ ] Full local verification suite green (tests, lint, typecheck, terminal build, desktop build when touched, secrets scan) → semver bump → changelog (shipped only) → tag → push to main with release structure. Never `--no-verify`; stage explicitly.
- [ ] Then the standing loop (`.local/AGENT.md`): find → fix → optimise → verify → document → commit, highest-leverage item first, forever.

---

## Standing constraints

- **no-overscope:** personal-use open-source (operator == user == data principal). No DPDPA / §65B / CERT-In / RBI / grievance / vendor ceremony. SEBI-derived functional requirements only: per-second order rate limiting, 2FA/OAuth broker login, daily session re-auth (+ AGPL compliance). Static-IP registration is an operator action.
- **OpenAlgo quirks:** sandbox can send real orders (verify isolation); `closeposition` ignores strategy; WS heartbeat lives in the terminal's `websocket.ts` — preserve it; PNL wrong for some brokers (compute locally); MCX symbols normalise via `symbol_utils`; never touch OpenAlgo's SQLite.
- **Ports:** terminal 5173 (Vite), FlintTrade backend 5100, OpenAlgo 5000 (external), OpenAlgo WS 8765. Never consolidate 5100 into 5000–5009.
- **Review pipeline:** claude (ultracode multi-agent panels) → maintainer. A phase/wave is done only after audit → fix → clean re-audit.
- **Trading safety:** all development/testing in Explore/Practice; Live is armed only by the maintainer, explicitly, per session. Every new order path mints a `SafetyContext` via `gate_order`/`gate_broker_write` → `BrokerRouter`.

*Living roadmap — tick items as they ship; move shipped features into `changelog.md`; keep gap IDs stable.*
