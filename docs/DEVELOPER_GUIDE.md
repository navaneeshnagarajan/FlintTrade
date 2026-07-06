# FlintTrade Developer Guide

This guide is for contributors and integrators. It assumes you have read
[USER_GUIDE.md](USER_GUIDE.md) so you know what FlintTrade does at a user
level, and that you are comfortable with Python, TypeScript, and Git.

For higher-level design context (data flow, mode system, dependency graph),
see [ARCHITECTURE.md](ARCHITECTURE.md). For the public HTTP and WebSocket
contract, see [API.md](API.md). For CI behaviour, see [CI.md](CI.md).

---

## 1. Repository layout

FlintTrade is a monorepo with 18 package surfaces: 13 Python packages, 3
applications (React terminal, Tauri desktop shell, Next.js site), 1 shared
TypeScript design-system package, and 1 Rust package with Python bindings.

| Package | Language | Purpose | Tests |
|---|---|---|---|
| `site` | TypeScript / Next.js | Public website, generated documentation, contribution pages, and read-only docs MCP | `packages/apps/site/src/**/*.test.ts` |
| `terminal` | TypeScript / React | User-facing single-page application; Dockview workspace, home widgets, routes, and tools | `packages/apps/terminal/**/*.test.ts(x)` |
| `desktop` | TypeScript / Rust (Tauri 2) | Native desktop shell; bundles the PyInstaller-frozen backend sidecar + built terminal into one cross-OS installer (Linux/Windows/macOS), served from a single loopback origin | `packages/apps/desktop/src-tauri/src/**` (cargo tests) |
| `design-system` | TypeScript / React | Shared brand tokens, layers, motion, primitives, and FlintTrade UI contracts | type-checked by app builds |
| `core` | Python | Flask app entry point, OpenAlgo client (45+ endpoints), config, workspace, models, exceptions | `packages/core/core/tests/` |
| `data` | Python | Tick recorder, audit logger, trade logger, SQLite sandbox state, DuckDB analytics storage | `packages/core/data/tests/` |
| `historical` | Python | OHLCV downloader (OpenChart, yfinance), DuckDB pipeline, expiry manager, instrument metadata | `packages/core/historical/tests/` |
| `indicators` | Python | TA-Lib (batch, 150+ indicators) + Numba (streaming) + PineTS (Pine Script conversion) | `packages/core/indicators/tests/` |
| `ticks` | Rust + PyO3 | High-performance tick processing engine, Python-callable via wheel | `packages/core/ticks/tests/` (cargo) |
| `gateway` | Python | OpenAlgo-compatible bridge support, native broker adapter contract/routing, founder-broker adapter code (Dhan, Upstox, and INDmoney connectable; Kotak Neo and Groww built but coming soon), credential store, and WebSocket bridge | `packages/integrations/gateway/tests/` |
| `webhooks` | Python | TradingView webhooks, ChartInk, custom webhooks, flow builder, alerter, Excel bridge | `packages/integrations/webhooks/tests/` |
| `ai` | Python | LLM client (multi-provider), optional RAG/vector store, signals, sentiment, MCP bridge, advisor | `packages/services/ai/tests/` |
| `automation` | Python | Cron manager, Telegram bot with kill-switch, OpenClaw bridge, post-market analysis | `packages/services/automation/tests/` |
| `backtest` | Python | Simulator, metrics (Sharpe, Sortino, drawdown), walk-forward, Monte Carlo, 94 strategy templates | `packages/services/backtest/tests/` |
| `ditto` | Python | Multi-account manager, position mirror, margin calculator, trailing SL, risk manager | `packages/services/ditto/tests/` |
| `engine` | Python | 5-layer safety system, order router, scheduler, base strategy, strategy registry, mode guard | `packages/services/engine/tests/` |
| `journal` | Python | Journal entries, trade logging, execution-quality analytics, and realised P&L tracking | `packages/services/journal/tests/` |
| `screener` | Python | Option chain, OI analysis, PCR, max pain, futures quadrant, IV smile, payoff engine | `packages/services/screener/tests/` |

The repository carries a large Python and terminal test suite. Prefer the
commands below for current counts instead of relying on stale hard-coded
numbers.

---

## 2. Development environment setup

Pick the guide for your platform and follow it end-to-end:

- [Windows setup](setup/windows.md)
- [macOS setup](setup/macos.md)
- [Linux setup](setup/linux.md)
- [Raspberry Pi setup](setup/raspberry-pi.md)
- [Quick start (cross-platform)](setup/QUICKSTART.md)

A complete dev environment includes Python 3.12, Node 22+ (24 recommended),
and Rust stable if you build `ticks`. OpenAlgo is optional: install it
separately, or clone a local-dev copy into `.local/external/openalgo/` with
`scripts/setup-test-deps.sh`, only when you want the OpenAlgo-compatible
integration path.

For the FULL Python stack — every workspace member plus the ML/AI extras
(vectorbt+numba backtesting, lightgbm/optuna ensemble tuning, ChromaDB RAG,
reportlab PDF export, openpyxl Excel bridge) — sync all packages and extras;
only `talib` stays opt-in because it needs the TA-Lib C library:

```bash
uv sync --all-packages --all-extras --no-extra talib
```

On macOS, `lightgbm` additionally needs OpenMP: `brew install libomp`. A plain
`uv sync` installs a lean base environment; the corresponding ML/export tests
skip with a reason instead of failing.

---

## 3. Running tests

### Python (pytest)

From the repository root:

```bash
make test           # full pytest suite
make test-fast      # stop on first failure
make lint           # ruff check across packages/*/src/

# Single file
python -m pytest packages/core/core/tests/test_app.py -v

# Single test
python -m pytest packages/core/core/tests/test_app.py::test_health_endpoint -v

# Single package
python -m pytest packages/services/screener/tests/
```

> `--import-mode=importlib` is required for the flat-package layout. The
> Makefile sets it for you; if you call `pytest` directly, add it.

### Terminal (Vitest)

From `packages/apps/terminal/`:

```bash
npm install
npm run typecheck                          # tsc --noEmit only
npm run build                              # full type-check + Vite build
npx vitest run                             # full Vitest suite
npx vitest run src/widgets/path/foo.test.tsx
npx vitest run -t "renders the order pad"  # single test by name
npx vitest                                 # watch mode (great for TDD)
```

### Rust (ticks)

From `packages/core/ticks/`:

```bash
cargo test
cargo build --release   # produces an importable Python wheel
```

---

## 4. Building

### Terminal

```bash
cd packages/apps/terminal
npm run build
```

Output lands in `packages/apps/terminal/dist/`. The build runs `tsc --noEmit`
first, then `vite build` — both must pass clean.

### ticks

```bash
cd packages/core/ticks
cargo build --release
```

The resulting `.pyd` / `.so` is imported by the Python `tick_engine` module
exposed through PyO3 bindings.

### Site

```bash
cd packages/apps/site
npm run typecheck
npm run test
npm run build
```

The site build regenerates the docs index, package index, version metadata,
llms files, and the read-only docs MCP content from repository source files.

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
   `packages/apps/terminal/src/widgets/<trading|analysis|utility>/<Name>.tsx`.
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
   `packages/apps/terminal/src/layout/widgetFactory.tsx`, add an entry mapping
   the widget identifier to your component.
4. **Write a test.** Co-locate as `<Name>.test.tsx`. At minimum, mount
   the component with mocked atoms and assert the rendered output.
5. **(Optional) add to a workspace preset.** Edit
   `packages/apps/terminal/src/layout/workspacePresets.ts` if your widget
   belongs in one of the 13 default presets.
6. **Update [USER_GUIDE.md](USER_GUIDE.md)** if the widget changes the
   user-visible workspace tour.

### Style rules

- Use **shadcn/ui** primitives (Button, Dialog, Input, etc.) — never raw
  HTML.
- Use **Tailwind v4** utility classes; no arbitrary `style={...}`
  except for measured pixel values from observers.
- For chart widgets, use the Flint chart core in
  `packages/core/design-system/src/charts/` and the terminal runtime adapter at
  `packages/apps/terminal/src/lib/lightweightChartRuntime.ts`. Do not import
  Lightweight Charts runtime values or call `createChart`, `chart.addSeries`,
  or `createSeriesMarkers` directly from widget code. Drawing creation should
  go through `advanceFlintChartDrawingDraft`, drawing render decisions should
  go through `createFlintChartDrawingRenderPlan`, drawing runtime lifecycle
  diffing should go through `createFlintChartDrawingRenderPlanDiff`, indicator
  line/histogram render specs and pane-aware series options should go through
  `createFlintChartIndicatorSeriesRenderPlan`, indicator runtime lifecycle
  diffing should go through `createFlintChartIndicatorSeriesRenderPlanDiff`,
  and OI overlay bar semantics should stay in core helpers such as
  `createFlintChartOIProfileBarData`.
- For Plotly-only analysis surfaces, keep the heavy runtime behind
  `packages/apps/terminal/src/components/charts/PlotlyChart.tsx`, but use the
  core `createFlintPlotlyTheme`, `FLINT_PLOTLY_DEFAULT_CONFIG`, and
  `mergeFlintPlotlyLayout` contracts for theme, modebar, and layout behaviour.
- Honour `prefers-reduced-motion` for any animation.
- Use the **Glass Adaptive** design system tokens (CSS vars defined in
  `packages/apps/terminal/src/styles/`). No hardcoded colours.

---

## 7. Adding a strategy

FlintTrade has two strategy surfaces — backtest-only templates and
live-runnable strategies.

### Backtest template

For research and parameter sweeps. Lives under
`packages/services/backtest/src/flinttrade_backtest/strategies/`.

1. Create `my_strategy.py` and subclass
   `flinttrade_backtest.base_strategy.BaseBacktestStrategy`.
2. Implement `signal(ctx)` returning a typed `Signal` object.
3. Register the template in
   `packages/services/backtest/src/flinttrade_backtest/strategies/__init__.py`.
4. Write a unit test in `packages/services/backtest/tests/` with
   deterministic input data.

### Live strategy

For the production engine. Lives under
`packages/services/engine/src/flinttrade_engine/strategies/`.

1. Subclass `flinttrade_engine.strategy.BaseStrategy`.
2. Implement the lifecycle hooks (`on_tick`, `on_order_event`,
   `on_position_event`, `on_stop`).
3. Register in `packages/services/engine/src/flinttrade_engine/strategies/__init__.py`.
4. Write a unit test against a mocked OpenAlgo client.
5. Update the strategy registry so the Strategy Lab UI lists it.

Two production strategies ship today: `ema_crossover` and `wheel_live`.
Use either as a reference implementation.

---

## 8. Adding a broker adapter

FlintTrade has two first-class broker paths: the recommended
OpenAlgo-compatible bridge and the native gateway. A native broker is a direct
SDK/HTTP adapter that implements the `BrokerAdapter` Protocol and is routed
through the `BrokerRouter`; OpenAlgo is represented by its own bridge adapter
(`brokers/openalgo.py`) alongside the native ones. Do not model a new native
broker as an OpenAlgo shim. The `shims/` directory holds only OpenAlgo
infrastructure shims, not broker adapters.

1. Add a native adapter under
   `packages/integrations/gateway/src/flinttrade_gateway/brokers/<broker>.py`
   implementing the `BrokerAdapter` Protocol from
   `packages/integrations/gateway/src/flinttrade_gateway/adapter.py`. Map the
   broker's native exceptions onto `flinttrade_core.exceptions` and advertise
   capabilities truthfully (the router relies on them for failover).
2. Add an entry to the `BROKER_CATALOG` dict in `adapter.py` with the
   broker's display name, auth flow type, and capabilities.
3. Register the adapter in
   `packages/integrations/gateway/src/flinttrade_gateway/registry.py` so the
   `BrokerRouter` in `router.py` can resolve and dispatch orders to it.
4. Add tests under `packages/integrations/gateway/tests/` — mock the broker's
   SDK/HTTP responses, assert auth, capability lookup, and error handling.
5. Update [COMPATIBILITY.md](COMPATIBILITY.md) with the new broker.

Native connectability is a separate release gate from adapter existence.
Only flip `connectable=True` after the broker has been tried against a real
account path and the evidence is captured. Built-but-unverified adapters stay
visible as "coming soon" so their code, mappings, and mock coverage are kept
without presenting them as live-ready.

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
- **Path alias** `@` → `packages/apps/terminal/src/`. Configured in
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
   - `npx tsc --noEmit` in `packages/apps/terminal`
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

### 5-layer safety system in `packages/services/engine/`

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

In `packages/apps/terminal/`, the dev server proxies:

| Route prefix | Target |
|---|---|
| `/api` | `http://127.0.0.1:5000` (OpenAlgo) |
| `/ft-api` | `http://127.0.0.1:5100` (FlintTrade backend) |
| `/ws` | `ws://127.0.0.1:8765` (OpenAlgo WebSocket) |

In dev mode, `packages/apps/terminal/src/api.ts` uses *relative* paths (empty
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
   `packages/core/core/src/flinttrade_core/openalgo_client.py` implements ping/pong.
4. **PNL calculation incorrect for some brokers.** Compute it locally
   from `tradebook`.
5. **MCX symbol format inconsistency.** Normalise in
   `packages/core/core/src/flinttrade_core/symbol_utils.py`.
6. **Never touch OpenAlgo's SQLite directly.** Concurrent access
   corrupts the DB. Always go through the REST API.

---

## 12. Where to ask for help

- **Question issue template** — focused usage questions, design questions, and ideas.
- **GitHub Issues** — bug reports, feature requests.
- **GitHub Security Advisories (private)** — security disclosures.

Active design specs for in-flight work live under
[docs/superpowers/specs/](superpowers/specs/). If you are about to start
non-trivial work, check the specs folder first — there may already be
an approved design.
