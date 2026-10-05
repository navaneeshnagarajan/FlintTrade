# FlintTrade — Development Roadmap

Broker connections use five native adapters: Dhan, Upstox, Kotak Neo,
INDmoney and Groww. Availability remains evidence-gated. Native broker HTTP
mutations and reads remain frozen until Task 9D and Task 7C.2; a broker session
cannot currently be established through the terminal. Practice uses the local
sandbox. Funded Live placement remains unproven and fail-closed.


> This is the public roadmap. Detailed working notes, specs and evidence live in the maintainer's private workspace; phase outcomes are summarised here when they land. Shipped detail moves to `changelog.md`.

FlintTrade is open-source, self-hosted trading software for manual, automated, algorithmic and AI-assisted workflows on Indian markets (NSE/BSE equity and F&O). It runs its own native backend first and uses native broker adapters. The headline feature is **gated execution**: every reachable live order traverses the five-layer `SafetySystem`, a one-shot HMAC `SafetyContext` and the `BrokerRouter` before any broker adapter is invoked — no order path may bypass this chain.

Current version: **v0.0.1** — a clean-slate pre-1.0 baseline after the 2026-07-23 release reset. Not production-ready.

## Architecture north star

- **The core backend is the only place broker differences are absorbed.** No feature talks to a broker directly; everything flows through the unified core functions (catalogue, router, gate, reads facade, storage). A feature with its own broker path is a consolidation bug.

One unbranching pipeline — every feature builds on the same layers, never around them:

native adapter → BrokerRouter/read port → core backend → terminal

## Current state

- **Brokers:** native broker HTTP UX is frozen on `main` until Task 9D and Task 7C.2. This remains an accepted product decision.

- **Safety:** no reachable ungated live order path — verified via repeated adversarial audit passes and pinned by guard tests. Intentionally-raw paths are Layer-5 emergencies on shrinking allowlists.

- **Modes:** Explore / Practice / Live are enforced server-side via JWT claims; PIN live-unlock and downgrade paths are wired through the app-auth flow, and Practice order placement is proven through the native sandbox engine.

- **Desktop:** the Electron source-bootstrap shell is complete and locally verified (macOS packaged ad hoc). No complete installer release is published yet — macOS awaits Apple distribution signing and notarisation secrets; Windows/Linux installers build only in CI.

## Phase tracker

| Phase | Scope | Status |
|---|---|---|
| 0 | Ground-truth audit; documentation corrected; roadmap rewritten | **Closed 2026-07-03** |
| 1 | Auth end-to-end (app + broker), SEBI-correct | In progress — core shipped; live broker-verification evidence remains |
| 2 | Stabilise everything that exists | In progress — major rows landed; evidence-backed duplicate and native-CI validation remains |
| 3 | Build the unmapped reference backlog | Exit criterion met 2026-07-06; closes after the standing audit |
| 4 | Autonomous loop proven in Practice | In progress — safety layers and learning loop shipped; full-day run pending |
| 5 | Distribution + public surfaces | In progress — Electron migration complete; release publication pending |
| 6 | Release + continuous improvement loop | Not started |

A phase closes only after a full multi-agent audit → fix everything → clean re-audit.

## Phase 0 — Ground-truth audit *(closed)*

**Goal:** establish the true state of the repository before building anything else — verify every documentation claim against code, cross-trace the order and auth paths, assemble a full feature matrix, and rewrite the roadmap from evidence.

Delivered: a per-package audit sweep, doc-claim verification and corrections across every top-level document, a full feature matrix, and a consolidated gap map that drives Phases 1–4. **Exit met:** two adversarial verification passes; the second returned zero refuted and zero high-severity findings. Closed 2026-07-03.

## Phase 1 — Auth end-to-end, SEBI-correct *(in progress)*

**Goal:** the complete authentication story — app auth (password + TOTP login, mode-scoped JWTs with daily expiry and revocation, PIN as a re-auth factor over a live session only) and broker auth (encrypted credential vault, credential-replay login, OAuth connect, daily session refresh) — correct against SEBI-derived functional requirements: per-second order rate limiting, 2FA/OAuth broker login, daily session re-auth.

Done: server-side mode upgrades and downgrades; mode-preserving PIN unlock; a working auth brute-force limiter; route-prefix regression guards; operator-session-JWT enforcement on all broker-management writes; per-second broker submission caps plus HTTP-layer rate limits and per-broker algo-tag ceilings; the native credential-replay login step; in-app credential capture and the OAuth connect flow (HTTP mutations now answer `503` until Task 9D); daily session refresh with honest `needs_relogin` surfacing instead of false connected states; live login/read verification for Dhan, Upstox and INDmoney. Two full audit → fix → re-audit rounds have passed over this work.

**Exit (remaining):** restore a working native HTTP path (Task 9D mutations + Task 7C.2 read-port cutover) before treating native Brokers UX as live again — native UX stays down on `main` until then, by product decision; live-verify the remaining native brokers' order-safety behaviour (INDmoney's restart-time discrimination and reduce-only close, Kotak Neo's funded Live unlock / order-safety proof); refresh post-restart connected evidence for the active natives; then a clean re-audit.

## Phase 2 — Stabilise what exists *(in progress)*

**Goal:** fix every broken feature and finish or honestly degrade every partial one, so nothing user-visible crashes or silently fakes data.

Done highlights:

- Gated basket/split/options-strategy orders; sandbox fill realism; native GTT (forever-order) correctness across Dhan and Upstox with fail-closed cross-broker fields; explicit unknown-outcome recovery for response-lost writes; a hash-chained, verifiable audit log; a native two-way Telegram bot carrying the kill switch; a real searchable trade journal (SQLite + FTS5); honest provenance labels on every widget that can fall back to sample data; clean uninstall plus backend persistence for data that previously lived only in browser storage; CI test-visibility fixes so every terminal test file runs in a shard, with drift guards.
- A terminal-wide widget consolidation (102 widgets → 69 via PR #71; current catalogue pin 71 after follow-on merges) that merged duplicate surfaces onto shared kernels (options maths, position sizing, order guards, strategy templates) and closed real order-path defects the duplicated surfaces had hidden; verified by adversarial review passes that were themselves re-checked by a fresh-context reviewer.
- Webhooks were narrowed by maintainer ruling (2026-07-26) to the generic HMAC-signed custom rail; the TradingView/ChartInk/GoCharting parsers and the n8n/WhatsApp bridges were removed.
- The native broker account foundation now has strict mutation contracts, encrypted durable claims, witnessed workspace recovery, retained runtime custody and a synthetic transaction coordinator. Read enrolment follows validated vault authority, and terminal receipts retain redacted audit events for verified retryable delivery. This foundation precedes the production HTTP cutovers below; it does not enable native broker UX or a provider driver.

Remaining: continue evidence-backed duplicate consolidation, and close only the still-open rows after a fresh code-ground-truth audit. Cross-platform nightly-CI repairs landed in #140. The older broker-connect, GTT UI, `post_market_analysis`, dead-admin-route, installer-duplication and “final two widget” rows are shipped or superseded. **Task 9D** must migrate broker-account HTTP handlers and remove `guard_broker_account_http` atomically (today every production mutation answers `503`). **Task 7C.2 / 8B** must cut native HTTP reads over to the authenticated in-process `BrokerReadPort` (today those reads answer `409` and make zero provider calls). Until both land, native broker UX on `main` stays down — that is the accepted product decision for the service-connections / identity merge, not a regression to restore in place.

**Exit:** nothing user-visible crashes or silently fakes; the feature matrix has no broken rows and every partial or stub row is finished, visibly degraded, or explicitly deferred; full local verification green; multi-agent audit + re-audit clean.

## Phase 3 — Build the unmapped *(exit met)*

**Goal:** work through the consolidated backlog of features mapped from reference platforms and prior research — build what belongs in FlintTrade, and defer the rest explicitly with reasons.

Two build waves shipped 16 items across analytics (FII long/short ratios, gamma density, an arbitrage scanner, candlestick pattern detection, index contribution), watchlist power features (formula builder, hover quick trade), tick-capture surfacing, and a local-data downloader (NSE bhavcopy plus a browseable local store). The remaining rows carry explicit deferrals: floating/pop-out panels, an order-capable trading MCP server (a deliberate safety decision reserved for the maintainer), life-OS breadth beyond trading, and alternative search/AI stacks. **Exit met 2026-07-06:** every backlog row is either implemented or explicitly deferred. Groww live promotion and a community-contributed Zerodha adapter remain tracked under their own evidence gates.

## Phase 4 — Autonomous loop proven in Practice *(in progress)*

**Goal:** prove the full autonomous chain — signal → SafetySystem L1–L5 → gated order → sandbox fill → journal → learning update — across a full trading day in Practice mode, with Live provably blocked throughout.

Done: Layer 3 admission from native option Greeks with fail-closed instrument reconciliation; Layer 4 fed from locally computed daily P&L (never trusting broker aggregates); grep-guard hardening so no new ungated order dispatcher can land; the agent learning loop (post-session reflection persisting per-symbol lessons that inform later decisions but can never mutate safety limits or order parameters); operator-approved skill drafts; searchable AI session history; single-backend-per-workspace enforcement. A compressed synthetic-clock full-session integration test pins the agent chain end-to-end. A real-`SandboxEngine` HTTP burst pins Practice rate limiting (10 accepted / 11 refused under a frozen clock) and contradictory Live-header rejection before sandbox or router dispatch.

AI3 (read-only Python-RPC tool scripting) is deferred to a maintainer sandbox-design call before any code or spec implementation.

**FT-MONDAY-003** (`#254`) ships AI Chat live-read context: when an LLM is configured, Chat may use Practice fills and native live-read feeds for analysis. Suggest stays labelled illustrative. Chat never shows green Connected without a real LLM. Measure later: profitable alphas are not a release criterion. Live place stays fail-closed. This does not lift the native broker HTTP freeze.

**Exit:** the loop survives a real full trading day in Practice with zero safety violations — rate limiting proven under load, a mid-run kill-switch drill, Live blocked server-side — and a complete journal/learning trail; audit + re-audit clean.

## Phase 5 — Distribution + public surfaces *(in progress)*

**Goal:** a new user can install the app, keep it updated, and report a bug; every public surface states only what is true.

Done: the Electron source-bootstrap desktop migration — a sandboxed shell, checksum-bound source and tool bootstrap, health-proofed promotion with rollback, guardian supervision, an honest source-versus-shell update UI, four CI-built installers plus a checksum manifest, and retirement of the previous Tauri/frozen-payload path — closed out with a full local verification gate and a five-lens adversarial review whose actionable findings were fixed and re-reviewed clean. Privacy-preserving in-app bug reporting shipped (diagnostics excluded by default, no background telemetry), and a site/docs truth pass aligned the public surfaces with the Electron model.

**Exit (remaining):** publish the release (maintainer-owned — macOS needs Apple distribution signing and notarisation secrets; Windows/Linux installers build in CI) and land the documented low-priority review follow-ups; then audit + re-audit clean.

## Phase 6 — Release, then keep looping *(not started)*

Full local verification green → semver bump → changelog (shipped only) → tag → release. Then the continuous loop: find → fix → optimise → verify → document → ship, highest-leverage item first.

## Standing constraints

- **no-overscope:** personal-use open-source (operator == user == data principal). No DPDPA / §65B / CERT-In / RBI / vendor-compliance ceremony. SEBI-derived functional requirements only (per-second order rate limiting, 2FA/OAuth broker login, daily session re-auth) plus AGPL licence compliance.

- **Trading safety:** all development and testing happens in Explore/Practice; Live is armed only by the maintainer, explicitly, per session. Every new order path mints a `SafetyContext` via `gate_order`/`gate_broker_write` → `BrokerRouter`.

- **Review discipline:** a phase or wave is done only after a full adversarial audit, fixes, and a clean re-audit.

*Curated public roadmap — tick items as they ship; shipped detail lives in `changelog.md`.*
