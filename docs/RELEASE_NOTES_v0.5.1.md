# FlintTrade v0.5.1 — release notes

**Status:** release candidate (`flint.toml` version `0.5.1-rc`).
**Base:** v0.5.0 GA (`2741cad`, 2026-04-19).
**Diff:** 46 commits, ~8,800 inserts / ~3,500 deletes, no breaking API changes.

This is a **patch release** focused entirely on security hardening, route-contract correctness, and CI infrastructure. No new user-facing features. Safe upgrade from v0.5.0 — every public API on the backend kept its existing call shape; the sandbox executor's `SandboxExecutor.run` and `ftApi.helpers.{post,get,put,del}` are backwards-compatible.

## TL;DR

- Repository flipped to **public AGPL-3.0** (unlimited CI minutes; previously hit private-repo cap).
- Closed **4 Codex stop-gate findings**: advanced-order mode-safety, helper auth-header propagation, JWT-revocation lifecycle, rate-limit auto-discovery.
- Closed **1 Codex MEDIUM finding**: sandbox subprocess isolation (hostile code can no longer outlive its wall-clock timeout).
- Closed **6 silent-404 frontend↔backend route mismatches** (iv_smile, payoff/*, earnings/*, pnl/symbols, strategies/uploaded/*, postcss/cargo updates).
- **Vitest OOM in CI** root-caused and fixed via `pool=forks` + radix-ui umbrella unwound. Widget tests now pass cleanly in CI.
- **51/51 sandbox tests pass** (44 pre-existing + 7 new subprocess isolation tests).
- **8 sample-data stub routes** added so widgets render the "Demo" badge instead of 404-ing in production.

## Security highlights (closes Codex audit findings)

### Critical

1. **Advanced order routes now require live-mode JWT unlock**
   `basket`, `split`, `options-strategy`, `bracket` previously wore only `@require_non_explore`, which blocked explore mode but never checked the `live_mode_unlocked` claim. A logged-in user without PIN re-verification could place real-money advanced orders. New `require_live_unlocked` decorator enforces the full mode-safety stack (`explore→403 mode_blocked`, `practice→403 practice_unsupported`, `live without unlock→403 live_locked`, `live unlocked→pass`). [`packages/engine/src/mode_guard.py`]

2. **PIN-unlock now actually swaps in the live JWT + downgrade revokes it**
   `ModeIndicator.tsx`'s `handleConfirmLive` previously discarded the live-unlocked JWT returned by `/v1/auth/pin`, so the in-memory token stayed at the Practice JWT and every subsequent live order was 403'd by `require_live_unlocked`. Conversely, switching the UI back to Practice never invalidated the live token — a stale live JWT could place real orders even after the UI claimed Practice. New `POST /v1/auth/mode` revokes the prior JTI server-side and mints a fresh Practice JWT; `handleToggle` swaps it in. Fails closed on revocation failure (503, UI stays Live). [`packages/core/src/auth_routes.py`, `packages/terminal/src/chrome/ModeIndicator.tsx`]

3. **Sandbox subprocess isolation — hostile code cannot outlive its timeout**
   `SandboxExecutor.run` now spawns `packages.engine.src._sandbox_child` in a child Python interpreter and kills it with `SIGKILL`/`TerminateProcess` on timeout. The legacy in-thread path is retained as an opt-in (`use_subprocess=False`) for trusted callers only. POSIX rlimits (256 MB AS, CPU, NOFILE=64, FSIZE=0) applied inside the child. Parent ONLY `json.loads` from the child; never `pickle.loads`. [`packages/engine/src/sandbox_executor.py`, `packages/engine/src/_sandbox_child.py`]

### High

4. **`ftApi.helpers` now attaches auth headers on every request**
   Previously only `api.postOrder` attached `X-API-Key` + `Authorization: Bearer <jwt>`. Helper-based callers (e.g. `placeBracketOrder`) sent only `Content-Type` and would have been rejected by `require_live_unlocked` with `auth_required`. Fixed: `post/get/put/del` now read from `useConnectionStore` + `useAuthStore` and attach both headers when populated. [`packages/terminal/src/services/ftApi.helpers.ts`]

5. **Auth rate-limit registration is now auto-discovered**
   `_apply_rate_limits` had a hardcoded list of five legacy endpoints and silently skipped the `@_rate_limit` decorator on `auth_setup_reset`, `auth_setup_regenerate_2fa`, `auth_mode_switch`, `auth_forgot_password`, `auth_reset_password`. All Flask-Limiter rules are now derived from a module-globals scan, with a test that fails if a future contributor adds an auth route without `@_rate_limit`. [`packages/core/src/auth_routes.py`]

### Medium / route drift

6. **Six frontend↔backend URL mismatches fixed** (silent 404s in production):
   - `iv_smile` → backend `/ivsmile` (frontend renamed)
   - `payoff_bp` moved `/v1` → `/api/v1` (covers `payoff/*`, `regime/current`, `analytics/correlation`)
   - `earnings_bp` moved `/v1/earnings` → `/api/v1/earnings`
   - `pnl/symbols` accepts both `GET` and `POST` (matches OpenAlgo contract)
   - `strategies/uploaded/<id>/{start,stop,logs}` → `strategies/<id>/{start,stop,logs}` (removed spurious `/uploaded/` segment; engine `strategy_bp` owns it directly)
   - `global_indices` stub registered at `/market/global_indices` (matches frontend caller)

7. **Duplicate routes removed**:
   - `/api/v1/security/{stats,bans,ban,unban}` was registered in both `security_bp` (first-match-wins) and `operations_bp` (shadowed); operations duplicates removed.
   - `/api/v1/strategies` + `/strategies/<x>/{start,stop}` collided between engine `strategy_bp` and core `backtest_bp`; backtest's renamed to `/backtest/strategies*` so live vs builtin strategy surfaces don't fight Flask's dispatcher.

## CI / dependencies

- **Public AGPL repo** — unlimited Actions minutes; previously hit private-repo monthly cap.
- **`pool: threads` → `pool: forks`** in `vite.config.ts`. Each test file in its own child process; OS reclaims heap on file completion. Closes the `ERR_WORKER_OUT_OF_MEMORY` failures on `node-widget-tests-1` / `node-widget-tests-3`.
- **`radix-ui` umbrella unwound** in all 14 shadcn primitives. `import { X as XPrimitive } from "radix-ui"` → `import * as XPrimitive from "@radix-ui/react-x"`. Each primitive now pulls in ~60 modules instead of ~2,400. Roughly 70-80% reduction in widget-test module-graph memory.
- **rand 0.7.3 → 0.9.4** in `desktop/src-tauri/Cargo.lock` — closes Dependabot alert #4 (rand unsoundness with custom logger). Plus a sweep of compatible minor bumps (tauri 2.11.1 → 2.11.2, tokio 1.51.1 → 1.52.3, hyper-rustls 0.27.8 → 0.27.9, wasm-bindgen 0.2.118 → 0.2.121, …).
- **postcss 8.5.8 → 8.5.15** via PR #39 — closes Dependabot alert #7 (PostCSS XSS in CSS stringify output).
- **CI cost-control patch already in v0.5.0**: macOS + Windows runners moved to `nightly-cross-platform.yml` (Sunday cron); per-push test matrix is 7 Ubuntu jobs with `paths-ignore`, `concurrency: cancel-in-progress`, and a draft-PR guard. No effect post-public-flip but kept as defence in depth.

## Outstanding / known issues (carry into v0.5.2)

- **glib pinned at 0.18.5** (Dependabot alert #1, medium severity). Transitive dep through gtk 0.18 inside tauri 2.x. Closes when tauri/gtk bumps GTK to 0.20+.
- **Windows sandbox Job Object** not yet implemented. POSIX rlimits enforce inside the child on Linux/macOS; on Windows the only enforcement is `proc.kill()` on wall-clock timeout. Hostile strategies can't outlive the deadline but can briefly burn ~256 MB memory + a CPU within the window. Follow-up adds `pywin32` Job Object support.
- **Sandbox subprocess spawn overhead** (~80–200 ms per call on Windows). The BacktestLab walk-forward inner loop calls the sandbox per bar; that's a 10-100× slowdown. Acceptable for user-uploaded strategies (the threat model); for in-house template runs, pass `use_subprocess=False` (already documented). A "trusted mode" boolean on the BacktestLab path is a follow-up.
- **8 stub backend endpoints** still return `is_sample_data: true` placeholders (etf/screener, sectors/rotation, analytics/risk-return, crypto/funding_rates, market/global_indices, screener/shareholding, screener/sector-constituents, screener/lot-size). Frontend widgets honour the flag and render "Demo" badges. Real implementations land as separate features.

## Verified metrics

- **Total tests**: ~12,200 (9,150+ pytest, 3,050+ vitest)
- **Sandbox tests**: 51/51 pass (44 pre-existing + 7 new subprocess isolation)
- **Auth tests**: 15/15 in `test_auth_routes.py` (15 cases × multiple expectations)
- **Mode-guard tests**: 17/17 in `test_mode_guard.py`
- **Frontend hook tests**: 12/12 useOrders/usePositions/useMargin gate logic
- **Helper auth-header tests**: 14/14 in `ftApi.helpers.test.ts`
- **Stub route tests**: 13/13 in `test_sample_data_routes.py`
- **`tsc --noEmit`**: clean
- **Codex stop-gate**: ALLOW (latest run on `b6fb501`)

## Commit range

```text
2741cad (v0.5.0 GA, 2026-04-19) .. 270c2f8 (HEAD, 2026-05-20)
```

Notable commits:
- `8851607` fix(security): mode-safety stack for advanced order routes (Codex #4)
- `df0e236` test(mode-guard,helpers): tighten coverage from independent code review
- `3208b0b` feat(stubs,tests): close orphan-API 404s + hook coverage gaps
- `2fd6c40` fix(stubs): wire global-indices stub at the URL the frontend actually calls
- `1005de9` chore(deps,tests): consolidate auto-PR cleanups + dependabot Cargo.lock security bump
- `00c06e7` fix(everything): CRITICAL JWT lifecycle + HIGH route drift + duplicate routes
- `b6fb501` fix(auth): rate-limit auto-discovery + fail-closed mode downgrade
- `cbc237b` chore(deps): bump postcss
- `301f7c3` fix(ci,deps): vitest pool=forks unblocks widget-tests + cargo update closes rand vuln
- `270c2f8` fix(security,perf): sandbox subprocess isolation + radix-ui umbrella unwound

## Upgrade notes

No action required for existing deployments. The sandbox API
(`SandboxExecutor.run`) is backwards-compatible; trusted callers in
BacktestLab who want the legacy in-thread speed can opt out with
`SandboxExecutor(use_subprocess=False)` (see docstring for when this is
appropriate).

Frontend callers of `ftApi.helpers.post/get/put/del` now automatically
attach `X-API-Key` and `Authorization: Bearer <jwt>` when the connection
and auth stores are populated. No code change needed on caller side;
the auth contract is strictly additive.

The `/v1/auth/mode` endpoint is new; the frontend `ModeIndicator` will
use it automatically. Existing tokens remain valid until their 8 AM IST
expiry; only the new mode-toggle UX exercises the endpoint.
