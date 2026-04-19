# FlintTrade Known Issues

Derived from `Grep` scans across `packages/**/*.{ts,tsx,py}` at commit `93bbaa0`. UI-level placeholder HTML attributes and stubbed **test files** (`vi.stubGlobal`, test doubles) are excluded — they are not real product issues.

**Summary counts:**

- `FIXME` markers: **0**
- `HACK` markers: **0**
- `XXX` markers: **0** (a handful of matches in `pine_converter.py` were generic placeholder names like `ta.xxx(...)` — false positives, excluded)
- `TODO` markers (real): **5**
- "Not implemented" / "stub" / "for now uses sample data" patterns (real): **~15**
- Explicit "placeholder" markers in production code (real): **3** (many matches were HTML `placeholder=` attributes — excluded)

No severity ranking beyond the groups below. Fix or document each one before cutting a GA release.

---

## FIXME (0)

None found.

## HACK (0)

None found.

## XXX (0)

None found in a product sense. Matches in `packages/indicators/src/pine_converter.py` are regex examples (`ta.xxx(...)`, `input.xxx(...)`) — false positives.

## TODO (5 real)

| # | File:line | TODO |
|---|---|---|
| 1 | [packages/core/src/csp.py:40](../../packages/core/src/csp.py#L40) | `# TODO: remove 'unsafe-inline' once Vite build uses nonce-based CSP` — CSP still permits inline styles/scripts because Vite's dev/build pipeline does not emit nonces yet. Tracked in the file header as well (line 16). |
| 2 | [packages/ai/src/memory.py:527](../../packages/ai/src/memory.py#L527) | `# TODO: page through in batches when ChromaDB exposes stable offset/limit` — memory module currently fetches all entries in one call; could blow up on large collections. |
| 3 | [packages/ditto/src/mirror.py:48](../../packages/ditto/src/mirror.py#L48) | `# TODO: Fetch lot sizes dynamically from OpenAlgo /api/v1/instruments in future.` — lot sizes are hardcoded. Works while MCX/NSE contract list is stable, breaks when lots change. |
| 4 | [packages/engine/src/strategy_routes.py:293](../../packages/engine/src/strategy_routes.py#L293) | `TODO: Forward trade tracking is a future feature. The strategy runner can be retrieved here. For now returns an empty list so the frontend …` — forward-test trade log endpoint returns `[]`. |
| 5 | [packages/core/src/backtest_routes.py:403](../../packages/core/src/backtest_routes.py#L403) | `# Hardcoded fallback list matching the known 12 strategies` — backtest route has a hardcoded strategy list as a fallback when the registry scan fails. |

## "Not implemented" / stub endpoints (Python)

| File:line | Detail |
|---|---|
| [packages/core/src/operations_routes.py:933-937](../../packages/core/src/operations_routes.py#L933-L937) | `ditto kill-all` endpoint is `Currently a stub — returns 501 Not Implemented` — intentional, requires real account connections. |
| [packages/automation/src/totp_login.py:2](../../packages/automation/src/totp_login.py#L2) | `TOTP auto-login is intentionally NOT implemented in FlintTrade.` — matches the "Decisions Made" list in CLAUDE.md (OpenAlgo handles broker auth). |
| [packages/automation/src/totp_login.py:58](../../packages/automation/src/totp_login.py#L58) | `"""Stub — TOTP auto-login is not implemented.` — stub class for callers that import it. |
| [packages/core/src/auth_routes.py:510](../../packages/core/src/auth_routes.py#L510) | `# Placeholder for flask-mail Message (lazy import so tests can mock it)` — design note rather than a real stub, but flags that email sending depends on a late binding. |
| [packages/integration/src/webhook_receiver.py:486](../../packages/integration/src/webhook_receiver.py#L486) | `# Placeholder — full integration with engine order router is done` — partial wording; verify the comment matches the real state (looks like it was meant to say "is NOT done"). |
| [packages/screener/src/breadth_routes.py:233](../../packages/screener/src/breadth_routes.py#L233) | `row["date"] = None  # placeholder; terminal can use its own date axis` — market-breadth endpoint returns null dates intentionally; UI must supply the x-axis. |
| [packages/core/src/user_routes.py:58](../../packages/core/src/user_routes.py#L58) | `# For now, role is checked against the 'role' claim in the JWT.` — Single-claim RBAC; upgrade path implied. |
| [packages/core/tests/test_csrf.py:10](../../packages/core/tests/test_csrf.py#L10) | `suite validates the double-submit cookie flow end-to-end.  For now it …` — CSRF test is a stand-in until the full end-to-end setup is in place. |
| [packages/backtest-engine/src/rl_trainer.py:452](../../packages/backtest-engine/src/rl_trainer.py#L452) | `# worker (Celery, threading, etc.). For now, return immediately` — RL training runs inline; no queue/worker yet. |
| [packages/data/src/tax_routes.py:89](../../packages/data/src/tax_routes.py#L89) | `# For now, return all sample trades regardless of FY` — tax endpoint ignores the financial year filter. |

## "Not implemented" / stub UI widgets (Terminal)

| File:line | Detail |
|---|---|
| [packages/terminal/src/widgets/analysis/VolatilityCone/VolatilityConeWidget.tsx:231](../../packages/terminal/src/widgets/analysis/VolatilityCone/VolatilityConeWidget.tsx#L231) | `// For now we use sample data always (endpoint not yet implemented)` — Volatility Cone has no backing API yet. |
| [packages/terminal/src/widgets/analysis/IVSkew/IVSkewWidget.tsx:334](../../packages/terminal/src/widgets/analysis/IVSkew/IVSkewWidget.tsx#L334) | `// In live mode you would wire up a real query; for now use sample data always` — IV Skew uses sample data. |
| [packages/terminal/src/widgets/analysis/ImpliedMove/ImpliedMoveWidget.tsx:192](../../packages/terminal/src/widgets/analysis/ImpliedMove/ImpliedMoveWidget.tsx#L192) | `// In live mode we would call an API; use sample data for now` — Implied Move uses sample data. |
| [packages/terminal/src/widgets/utility/TickSpeed/TickSpeedWidget.tsx:190](../../packages/terminal/src/widgets/utility/TickSpeed/TickSpeedWidget.tsx#L190) | `// For now simulate realistic live numbers while connected` — Tick Speed gauge is simulated even when broker is connected. |
| [packages/terminal/src/hooks/useScannerData.ts:251](../../packages/terminal/src/hooks/useScannerData.ts#L251) | `// OI Change requires option chain data — keep sample for now` — Scanner OI-change column shows sample data. |
| [packages/terminal/src/routes/ai/AISuggestionsPanel.tsx:87](../../packages/terminal/src/routes/ai/AISuggestionsPanel.tsx#L87) | `advisor backend; for now we use curated entries from the 101 backtest` — AI Suggestions panel lists curated backtest entries, not model output. |
| [packages/terminal/src/routes/invest/tabs/DashboardTab.tsx:146-150](../../packages/terminal/src/routes/invest/tabs/DashboardTab.tsx#L146-L150) | `// XIRR calculation — uses demo cash flows for now; live would use trade history` — Invest dashboard XIRR uses demo cash flows. |
| [packages/terminal/src/routes/setup/ConnectionStep.tsx:385](../../packages/terminal/src/routes/setup/ConnectionStep.tsx#L385) | `Auth flow "{broker.auth_flow}" is not yet supported in the setup wizard.` — wizard visibly refuses some broker auth flows. |
| [packages/terminal/src/tools/BacktestLab/BacktestLabTool.tsx:860](../../packages/terminal/src/tools/BacktestLab/BacktestLabTool.tsx#L860) | UI switches between `"Mock data"` and `"Live results"` labels — Backtest Lab falls back to mock data on run errors (line 904 logs `"showing mock data instead."`). |
| [packages/terminal/src/hooks/useTremorTheme.ts:8](../../packages/terminal/src/hooks/useTremorTheme.ts#L8) | `(via the customColors workaround)` — Tremor theme hook has an explicit workaround for Tremor's theming. |

## Verification caveats specific to this machine

These are not code issues but test/runtime issues observed at report time that prevent a clean verdict:

1. **DuckDB file lock on `~/.flinttrade/security.db`** — another Python process (PID 26840) is holding the file open and blocking pytest from creating a `SecurityTracker`. Fix: `taskkill /F /PID 26840` (or find and stop whatever is holding the DB) before re-running `pytest`.
2. **Python 3.14.3 on a project targeting 3.12** — likely contributes to the 6 pytest collection errors in `packages/gateway/tests/`. Switch the active interpreter to 3.12 (the version declared in `pyproject.toml`) before trusting any pytest output.
3. **Vitest worker crash (`ERR_IPC_CHANNEL_CLOSED`)** — known Windows/tinypool flake on Node 24 under very large suites; retry with `--poolOptions.threads.singleThread=true` or on a cleaner Node session.

---

## Issues this report does **not** cover

- Runtime regressions (no browser QA or live broker smoke test was performed).
- Console errors / warnings from the terminal dev server (not started).
- Deprecation warnings from installed libraries (Flask's `__version__` warning was observed; there may be more).
- Security findings beyond the self-reported CSP TODO — a real secure review is a separate exercise.
