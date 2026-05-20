# FlintTrade Developer Guide

This guide is for contributors and integrators. It assumes you have read
[USER_GUIDE.md](USER_GUIDE.md) so you know what FlintTrade does at a user
level, and that you are comfortable with Python, TypeScript, and Git.

For higher-level design context (data flow, mode system, dependency graph),
see [ARCHITECTURE.md](ARCHITECTURE.md). For the public HTTP and WebSocket
contract, see [API.md](API.md). For CI behaviour, see [CI.md](CI.md).

---

## 1. Repository layout

FlintTrade is a monorepo with 16 packages. Twelve are Python, one is a
React application, one is Rust with Python bindings, and two are
auxiliary distribution wrappers.

| Package | Language | Purpose | Tests |
|---|---|---|---|
| `gateway` | Python | Direct broker connections (33 brokers via OpenAlgo shims), credential store, WebSocket bridge | `packages/gateway/tests/` |
| `core` | Python | Flask app entry point, OpenAlgo client (45+ endpoints), config, workspace, models, exceptions | `packages/core/tests/` |
| `engine` | Python | 5-layer safety system, order router, scheduler, base strategy, strategy registry, mode guard | `packages/engine/tests/` |
| `data` | Python | Tick recorder, audit logger (SEBI 5 year), trade logger, DuckDB storage | `packages/data/tests/` |
| `historical` | Python | OHLCV downloader (OpenChart, yfinance), DuckDB pipeline, expiry manager, instrument metadata | `packages/historical/tests/` |
| `screener` | Python | Option chain, OI analysis, PCR, max pain, futures quadrant, IV smile, payoff engine | `packages/screener/tests/` |
| `backtest-engine` | Python | Simulator, metrics (Sharpe, Sortino, drawdown), walk-forward, Monte Carlo, 94 strategy templates | `packages/backtest-engine/tests/` |
| `ai` | Python | LLM client (multi-provider), RAG over ChromaDB, signals, sentiment, MCP bridge, advisor | `packages/ai/tests/` |
| `integration` | Python | TradingView webhooks, ChartInk, custom webhooks, flow builder, alerter, Excel bridge | `packages/integration/tests/` |
| `automation` | Python | Cron manager, Telegram bot with kill-switch, OpenClaw bridge, post-market analysis | `packages/automation/tests/` |
| `ditto` | Python | Multi-account manager, position mirror, margin calculator, trailing SL, risk manager | `packages/ditto/tests/` |
| `indicators` | Python | TA-Lib (batch, 150+ indicators) + Numba (streaming) + PineTS (Pine Script conversion) | `packages/indicators/tests/` |
| `tick-engine` | Rust + PyO3 | High-performance tick processing engine, Python-callable via wheel | `packages/tick-engine/tests/` (cargo) |
| `terminal` | TypeScript / React | The user-facing single-page application; Dockview workspace, 82 widgets, 12 routes | `packages/terminal/**/*.test.ts(x)` |
| `chrome-extension` | TypeScript | Browser extension for quick trading from any page | `packages/chrome-extension/tests/` |
| `desktop` | Rust / Tauri | Native desktop wrapper that embeds the terminal | `packages/desktop/tests/` |

Test counts (measured 2026-05-19): roughly 9,089 Python (pytest, 313 files)
and 2,973 terminal (Vitest, 264 files), totalling about 12,062.

---

## 2. Development environment setup

Pick the guide for your platform and follow it end-to-end:

- [Windows setup](setup/windows.md)
- [macOS setup](setup/macos.md)
- [Linux setup](setup/linux.md)
- [Raspberry Pi setup](setup/raspberry-pi.md)
- [Quick start (cross-platform)](setup/QUICKSTART.md)

A complete dev environment includes Python 3.12, Node 20+ (24 recommended),
Rust stable (only if you build `tick-engine`), and an OpenAlgo install
either at `.local/external/openalgo/` (via `scripts/setup-test-deps.sh`)
or as a separate service.

---

## 3. Running tests

### Python (pytest)

From the repository root:

```bash
make test           # all ~9,089 tests
make test-fast      # stop on first failure
make lint           # ruff check across packages/*/src/

# Single file
python -m pytest packages/core/tests/test_app.py -v

# Single test
python -m pytest packages/core/tests/test_app.py::test_health_endpoint -v

# Single package
python -m pytest packages/screener/tests/
```

> `--import-mode=importlib` is required for the flat-package layout. The
> Makefile sets it for you; if you call `pytest` directly, add it.

### Terminal (Vitest)

From `packages/terminal/`:

```bash
npm install
npm run typecheck                          # tsc --noEmit only
npm run build                              # full type-check + Vite build
npx vitest run                             # all ~2,973 tests
npx vitest run src/widgets/path/foo.test.tsx
npx vitest run -t "renders the order pad"  # single test by name
npx vitest                                 # watch mode (great for TDD)
```

### Rust (tick-engine)

From `packages/tick-engine/`:

```bash
cargo test
cargo build --release   # produces an importable Python wheel
```

---

## 4. Building

### Terminal

```bash
cd packages/terminal
npm run build
```

Output lands in `packages/terminal/dist/`. The build runs `tsc --noEmit`
first, then `vite build` — both must pass clean.

### tick-engine

```bash
cd packages/tick-engine
cargo build --release
```

The resulting `.pyd` / `.so` is imported by the Python `tick_engine` module
exposed through PyO3 bindings.

### Desktop (Tauri)

```bash
cd packages/desktop
npm run tauri build
```

Produces a native installer for your current platform. Cross-compilation
is documented in the package README.

---

## 5. Architecture deep-dive

Component diagrams, the mode-system state machine, the WSGI prefix-strip
explanation, and the package dependency graph live in
[ARCHITECTURE.md](ARCHITECTURE.md). Read that document before making any
non-trivial change.

---

## 6. Adding a widget

Every widget is a self-contained TSX component that is registered as a
Dockview panel.

### Step-by-step

1. **Pick a category.** Place the new file under
   `packages/terminal/src/widgets/<trading|analysis|utility>/<Name>.tsx`.
2. **Write the component.** Use functional components and hooks. Pull
   market data from Jotai atoms (per-instrument LTP / quote / depth),
   REST data from TanStack Query hooks, and UI state from Zustand stores
   — never mix layers (see [ARCHITECTURE.md](ARCHITECTURE.md#state-architecture)).

   ```tsx
   import { useAtomValue } from 'jotai';
   import { ltpAtomFamily } from '@/atoms/marketData';

   export function MyWidget({ panelProps }: { panelProps: WidgetPanelProps }) {
     const ltp = useAtomValue(ltpAtomFamily(panelProps.symbol));
     return <div className="widget-shell">{ltp ?? '—'}</div>;
   }
   ```

3. **Register the widget.** In
   `packages/terminal/src/layout/widgetFactory.tsx`, add an entry mapping
   the widget identifier to your component.
4. **Write a test.** Co-locate as `<Name>.test.tsx`. At minimum, mount
   the component with mocked atoms and assert the rendered output.
5. **(Optional) add to a workspace preset.** Edit
   `packages/terminal/src/layout/workspacePresets.ts` if your widget
   belongs in one of the 13 default presets.
6. **Update [USER_GUIDE.md](USER_GUIDE.md)** if the widget changes the
   user-visible workspace tour.

### Style rules

- Use **shadcn/ui** primitives (Button, Dialog, Input, etc.) — never raw
  HTML.
- Use **Tailwind v4** utility classes; no arbitrary `style={...}`
  except for measured pixel values from observers.
- Honour `prefers-reduced-motion` for any animation.
- Use the **Glass Adaptive** design system tokens (CSS vars defined in
  `packages/terminal/src/styles/`). No hardcoded colours.

---

## 7. Adding a strategy

FlintTrade has two strategy surfaces — backtest-only templates and
live-runnable strategies.

### Backtest template

For research and parameter sweeps. Lives under
`packages/backtest-engine/src/strategies/`.

1. Create `my_strategy.py` and subclass
   `backtest_engine.base.BaseBacktestStrategy`.
2. Implement `signal(ctx)` returning a typed `Signal` object.
3. Register the template in
   `packages/backtest-engine/src/strategies/__init__.py`.
4. Write a unit test in `packages/backtest-engine/tests/` with
   deterministic input data.

### Live strategy

For the production engine. Lives under
`packages/engine/src/strategies/`.

1. Subclass `engine.strategy.BaseStrategy`.
2. Implement the lifecycle hooks (`on_tick`, `on_order_event`,
   `on_position_event`, `on_stop`).
3. Register in `packages/engine/src/strategies/__init__.py`.
4. Write a unit test against a mocked OpenAlgo client.
5. Update the strategy registry so the Strategy Lab UI lists it.

Two production strategies ship today: `ema_crossover` and `wheel_live`.
Use either as a reference implementation.

---

## 8. Adding a broker adapter

OpenAlgo handles the heavy lifting, but FlintTrade keeps a thin shim
layer for capability detection and broker-specific quirks.

1. Add a shim under `packages/gateway/src/shims/<broker>.py` implementing
   the `BrokerAdapter` protocol from `packages/gateway/src/adapter.py`.
2. Add an entry to the `BROKER_CATALOG` dict in `adapter.py` with the
   broker's display name, auth flow type, and capabilities.
3. Register in `packages/gateway/src/registry.py` so the session manager
   can instantiate sessions for that broker.
4. Add tests under `packages/gateway/tests/` — mock the OpenAlgo HTTP
   responses, assert auth, capability lookup, and error handling.
5. Update [COMPATIBILITY.md](COMPATIBILITY.md) with the new broker.

---

## 9. Code style and lint

### Python

- **PEP 8** with `ruff` as the enforcement tool. Run `make lint`
  before committing.
- **Type hints** on every public function. We target Python 3.12 syntax
  (`list[int]` not `List[int]`, `X | None` not `Optional[X]`).
- **Google-style docstrings** for every public function and class.
- **Absolute imports**. Never use `from .foo import bar` inside
  `packages/<pkg>/src/`.
- **British English** in docstrings, comments, and user-visible strings.
  Code identifiers stay in their natural form (`color`, `behavior` are
  fine inside a CSS shim; user-visible labels read `colour`, `behaviour`).

### TypeScript

- **Strict mode**. No `any`, no `@ts-ignore`, no `@ts-nocheck`.
- **Path alias** `@` → `packages/terminal/src/`. Configured in
  `tsconfig.json`, `vite.config.ts`, and `vitest.config.ts`.
- **Functional components** with hooks. No class components.
- **lucide-react** for icons. **date-fns** for dates. **zod** for any
  runtime validation.
- **British English** in user-visible strings.

### Universal

- **No personal information** in committed code or commits (no
  hostnames, IPs, hardware specs, broker account IDs, fund amounts,
  order IDs).
- **No mock or placeholder data** in shipped UI — every screen renders
  real data or an explicit empty-state component.
- **Conventional Commits**. Examples:
  - `feat(screener): add OI profile widget`
  - `fix(engine): respect strategy isolation in closeposition`
  - `docs: add troubleshooting section for port 5100`
  - `test(core): cover JWT revocation edge cases`
  - `chore: bump dockview to 5.1.4`

---

## 10. Pull-request flow

1. **Branch off `main`.** During pre-1.0, all commits land directly on
   `main`; for non-trivial work, open a PR to give CI a chance to run.
2. **Run the local checklist** before pushing:
   - `npx tsc --noEmit` in `packages/terminal`
   - `npx vitest run` (full suite or affected files)
   - `python -m pytest --tb=short --import-mode=importlib`
   - `ruff check packages/*/src/`
3. **Open the PR.** Use the template in
   `.github/PULL_REQUEST_TEMPLATE.md`. Tick every checklist item that
   applies.
4. **Never push with `--no-verify`.** Pre-commit hooks exist for a
   reason. If a hook is broken, fix the hook in the same PR.
5. **No `dangerouslySkipPermissions`.** Anywhere.
6. **Sign-off** is optional. Conventional commit format is mandatory.

---

## 11. Common gotchas

### WSGI prefix strip — `/ft-api/v1/X` becomes `/v1/X`

The Vite dev server proxies `/ft-api/*` to the FlintTrade backend on
port 5100. The backend's WSGI middleware strips the `/ft-api` prefix
*before* URL dispatch. That means a blueprint registered at
`url_prefix="/v1"` answers requests at `/ft-api/v1/…` from the outside
and `/v1/…` from the inside. Do not double-prefix.

### Port 5100 is the FlintTrade backend — not OpenAlgo

OpenAlgo runs on ports 5000-5009 (multi-instance range). FlintTrade
deliberately picks 5100 to avoid that range. Do not propose
consolidating onto a single port; it would clash with multi-instance
OpenAlgo setups.

### No TOTP auto-login

OpenAlgo handles broker authentication (TOTP, OAuth, OTP, biometric
flows). FlintTrade only knows about the OpenAlgo API key. Do not add
broker-credential storage or TOTP automation to FlintTrade.

### 5-layer safety system in `packages/engine/`

Every order placed through FlintTrade passes five safety layers in
order:

1. **Order validation** — price within ±5 % of LTP, quantity within
   lot-multiple bounds.
2. **Position limits** — maximum five simultaneous positions, no
   single position exceeding 60 % of available margin.
3. **Portfolio risk** — net delta and net vega caps.
4. **Daily P&L** — pause at 3 % daily drawdown, kill at 15 %.
5. **Kill switch** — manual (Telegram, UI button) or automatic
   (P&L breach, OpenAlgo session loss, exchange holiday detector).

Do not bypass any layer. If you need a fast-path for high-frequency
orders, add the path inside the layers, not around them.

### Vite dev proxy paths

In `packages/terminal/`, the dev server proxies:

| Route prefix | Target |
|---|---|
| `/api` | `http://127.0.0.1:5000` (OpenAlgo) |
| `/ft-api` | `http://127.0.0.1:5100` (FlintTrade backend) |
| `/ws` | `ws://127.0.0.1:8765` (OpenAlgo WebSocket) |

In dev mode, `packages/terminal/src/api.ts` uses *relative* paths (empty
base URL). In production, it reads the full host from the
`connectionStore`. Do not bypass the proxy in dev — your code will work
locally but break on every other contributor's machine.

### State boundary rules

| Layer | Source | Lives in |
|---|---|---|
| Jotai atoms | WebSocket | Per-instrument LTP, quote, depth, derived PCR / straddle / Greeks |
| TanStack Query | REST | Positions, orders, holdings, funds, option chain |
| Zustand stores | Derived | Connection status, layout, settings mirror, aggregated P&L, mode |

Each data shape enters through one path only. Duplicate data across
stores and you guarantee a bug.

### OpenAlgo bugs to work around

1. **Sandbox sends real orders for some brokers.** Verify isolation
   before testing.
2. **`closeposition` ignores strategy.** Track positions per-strategy
   yourself.
3. **WebSocket drops without heartbeat.** The client in
   `packages/core/src/openalgo_client.py` implements ping/pong.
4. **PNL calculation incorrect for some brokers.** Compute it locally
   from `tradebook`.
5. **MCX symbol format inconsistency.** Normalise in
   `packages/core/src/symbol_utils.py`.
6. **Never touch OpenAlgo's SQLite directly.** Concurrent access
   corrupts the DB. Always go through the REST API.

---

## 12. Where to ask for help

- **GitHub Discussions** — usage questions, design discussions, ideas.
- **GitHub Issues** — bug reports, feature requests.
- **GitHub Security Advisories (private)** — security disclosures.

Active design specs for in-flight work live under
[docs/superpowers/specs/](superpowers/specs/). If you are about to start
non-trivial work, check the specs folder first — there may already be
an approved design.
