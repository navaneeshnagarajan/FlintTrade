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
applications (React terminal, Electron desktop shell, Next.js site), 1 shared
TypeScript design-system package, and 1 Rust package with Python bindings.

| Package | Language | Purpose | Tests |
|---|---|---|---|
| `site` | TypeScript / Next.js | Public website, generated documentation, contribution pages, and read-only docs MCP | `packages/apps/site/src/**/*.test.ts` |
| `terminal` | TypeScript / React | User-facing single-page application; FlexLayout workspace, home widgets, routes, and tools | `packages/apps/terminal/**/*.test.ts(x)` |
| `desktop` | TypeScript / Electron 44 | Sandboxed native shell; verifies tools, builds managed local source, supervises its guardian, and loads only the selected loopback origin | `packages/apps/desktop/electron/*.test.ts` |
| `design-system` | TypeScript / React | Shared brand tokens, layers, motion, primitives, and FlintTrade UI contracts | type-checked by app builds |
| `core` | Python | Flask app entry point, OpenAlgo client (45+ endpoints), config, workspace, models, exceptions, service-provider catalogue, inert service connections, and the `BrokerReadPort` contract | `packages/core/core/tests/` |
| `data` | Python | Tick recorder, audit logger, trade logger, SQLite sandbox state, DuckDB analytics storage | `packages/core/data/tests/` |
| `historical` | Python | OHLCV downloader (OpenChart, yfinance), DuckDB pipeline, expiry manager, instrument metadata | `packages/core/historical/tests/` |
| `indicators` | Python | Pure-NumPy batch indicators (110 exports; no TA-Lib) + streaming classes (optional Numba on 3 kernels) + PineTS (Pine Script conversion) | `packages/core/indicators/tests/` |
| `ticks` | Rust + PyO3 | High-performance tick processing engine, Python-callable via wheel | `packages/core/ticks/tests/` (cargo) |
| `gateway` | Python | OpenAlgo-compatible bridge support, native broker adapter contract/routing, founder-broker adapter code (Dhan, Upstox, and Kotak Neo connectable (Kotak Neo Connected (read) / API smoke only on FT-MONDAY-002 — Live place fail-closed; Neo has no sandbox); INDmoney and Groww built but coming soon), credential store, and WebSocket bridge | `packages/integrations/gateway/tests/` |
| `webhooks` | Python | Generic HMAC-signed custom webhooks, flow builder, alerter, Excel bridge | `packages/integrations/webhooks/tests/` |
| `ai` | Python | LLM client (multi-provider), optional RAG/vector store, signals, sentiment, MCP bridge, advisor | `packages/services/ai/tests/` |
| `automation` | Python | Cron manager, Telegram bot with kill-switch, post-market analysis, voice-order intent extraction | `packages/services/automation/tests/` |
| `backtest` | Python | Simulator, metrics (Sharpe, Sortino, drawdown), walk-forward, Monte Carlo, 94 strategy template modules | `packages/services/backtest/tests/` |
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

A complete dev environment includes Python 3.12, Node 22.22.2+ (24 recommended),
and Rust stable if you build `ticks`. OpenAlgo is optional: install it
separately, or clone a local-dev copy into `.local/external/openalgo/` with
`scripts/setup-test-deps.sh` (a bash script — on Windows run it in WSL2 or Git
Bash), only when you want the OpenAlgo-compatible integration path.

For the FULL Python stack — every workspace member plus the ML/AI extras
(vectorbt+numba backtesting, lightgbm/optuna ensemble tuning, local sqlite RAG,
reportlab PDF export, openpyxl Excel bridge) — sync all packages and extras
(the never-consumed `talib` extra was removed; the indicators are pure NumPy):

```bash
uv sync --all-packages --all-extras
```

On macOS, `lightgbm` additionally needs OpenMP: `brew install libomp`. A plain
`uv sync` installs a lean base environment; the corresponding ML/export tests
skip with a reason instead of failing.

---

## 3. Running tests

### Python (pytest)

From the repository root. `python scripts/ft.py <target>` is the cross-platform
runner — no make and no bash needed, identical behaviour on Windows, macOS and
Linux. `make <target>` is the POSIX alias for the same targets.

```bash
python scripts/ft.py test        # full pytest suite
python scripts/ft.py test-fast   # stop on first failure
python scripts/ft.py lint        # ruff over packages/ + tests/, then the terminal hooks lint

# Single file
python -m pytest packages/core/core/tests/test_app.py -v

# Single test
python -m pytest packages/core/core/tests/test_app.py::TestInputValidation::test_missing_bars_returns_400 -v

# Single package
python -m pytest packages/services/screener/tests/
```

> `--import-mode=importlib` is required for the flat-package layout.
> `scripts/ft.py` and the Makefile set it for you; if you call `pytest`
> directly, add it.

### Terminal (Vitest)

From the repository root, using the locked pnpm workspace:

```bash
pnpm install --frozen-lockfile
pnpm --filter @flinttrade/terminal typecheck   # tsc --noEmit only
pnpm --filter @flinttrade/terminal build       # full type-check + Vite build
pnpm --filter @flinttrade/terminal test        # full Vitest suite
```

For a single file, a single test name, or watch mode, work inside the package
(`cd` on its own line — do not chain with `&&`):

```bash
cd packages/apps/terminal
npx vitest run src/widgets/path/foo.test.tsx
npx vitest run -t "renders the order pad"  # single test by name
npx vitest                                 # watch mode (great for TDD)
```

### Desktop (Electron)

From the repository root, using the locked pnpm workspace:

```bash
pnpm --filter @flinttrade/desktop typecheck
pnpm --filter @flinttrade/desktop test:electron
pnpm --filter @flinttrade/desktop bundle
```

The Electron tests cover the renderer security waist, first-run bootstrap,
source promotion/rollback, guardian protocol and recovery, tray/hotkey/native
notifications, source updates and shell-installer handoff. They do not move
trading or broker authority out of Python.

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
pnpm --filter @flinttrade/terminal build
```

Output lands in `packages/apps/terminal/dist/`. The build runs `tsc --noEmit`
first, then `vite build` — both must pass clean. The backend serves the UI only
when `packages/apps/terminal/dist/index.html` exists, so run this once before
`python scripts/ft.py start` on a fresh checkout.

### ticks

```bash
cd packages/core/ticks
cargo build --release
```

The resulting `.pyd` / `.so` is imported by the Python `tick_engine` module
exposed through PyO3 bindings.

### Site

```bash
pnpm --filter @flinttrade/site typecheck
pnpm --filter @flinttrade/site test
pnpm --filter @flinttrade/site build
```

The site build regenerates the docs index, package index, version metadata,
llms files, and the read-only docs MCP content from repository source files.

### Desktop

```bash
python scripts/ft.py desktop-test     # Electron TypeScript + Vitest
python scripts/ft.py desktop-build    # verify bootstrap resources and bundle main/preload
python scripts/ft.py desktop-package  # build and verify this host's installer
```

On POSIX, `make desktop-test`, `make desktop-build` and `make desktop-package`
are aliases for the same three targets.

Output lands in `packages/apps/desktop/release/electron/`. The release workflow
produces a universal macOS DMG, Windows x64 NSIS installer, and x64/ARM64 Linux
AppImages. The source-built web app remains distinct from those Electron-shell
installers. A release is accepted only as all four canonical installers plus
`SHA256SUMS.txt`; retired Tauri and PyInstaller assets never satisfy that gate.
The local macOS packaging target always uses an ad-hoc seal, which verifies
bundle integrity but does not provide Developer ID trust or notarisation. Only
release CI can use complete Apple distribution-signing and notarisation secret
sets.

First launch uses system Git or the official HTTPS archive fallback, verifies
pinned tool distributions, provisions Python 3.12 with `uv`, installs from the
frozen Python and pnpm locks, builds the terminal, and starts the source guardian
only after candidate promotion succeeds. Rust is not a desktop build
prerequisite; it remains optional for `core/ticks`.

---

## 5. Architecture deep-dive

Component diagrams, the mode-system state machine, the WSGI prefix-strip
explanation, and the package dependency graph live in
[ARCHITECTURE.md](ARCHITECTURE.md). Read that document before making any
non-trivial change.

---

## 6. Adding a widget

Every widget is a self-contained TSX component that is registered as a
FlexLayout panel.

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
   belongs in one of the 17 listed presets (`beginner-core` is an extra
   unlisted layout resolved by id).
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
infrastructure shims, not broker adapters. Exact **reads** use
the contract defined by `BrokerReadPort`; `flinttrade_gateway.broker_read_service`
defines its owner factory, while application composition constructs and retains
the resulting dependency record. Native HTTP read routes currently return
`409` with zero provider calls until Task 7C.2 cuts them over to that port.
Reads do not traverse `gate_order` / `BrokerRouter`. Writes still must.

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
Only flip `connectable=True` after every declared `native_connect_blocker` has
been cleared and its evidence captured. A real account-path trial may satisfy a
declared evidence blocker, but it does not override an unresolved broker-safety,
SDK-attestation, or emergency-reduction blocker. Activation-blocked adapters stay
visible as "coming soon" so their code, mappings, and mock coverage are kept
without presenting them as ready to connect.

---

## 9. Code style and lint

### Python

- **PEP 8** with `ruff` as the enforcement tool. Run
  `python scripts/ft.py lint` (POSIX alias: `make lint`) before committing —
  that target lints the terminal as well, see [TypeScript](#typescript) below.
- **Type hints** on every public function. We write to the `python_requires`
  floor in `flint.toml` — currently 3.12 — so `list[int]` not `List[int]`,
  `X | None` not `Optional[X]`. CI runs `python_target` (3.14).
- **Google-style docstrings** for every public function and class.
- **Absolute imports** for anything cross-package or top-level
  (`flinttrade_<pkg>....`). Intra-package relative imports
  (`from .sibling import x`) are widespread and safe under
  `--import-mode=importlib`.
- **British English** in docstrings, comments, and user-visible strings.
  Code identifiers stay in their natural form (`color`, `behavior` are
  fine inside a CSS shim; user-visible labels read `colour`, `behaviour`).

### TypeScript

- **Strict mode**. No `any`, no `@ts-ignore`, no `@ts-nocheck`.
- **Lint at zero warnings**. `pnpm --filter @flinttrade/terminal lint`
  runs `eslint src --max-warnings=0`, making four rules errors rather than
  suggestions: `react-hooks/rules-of-hooks` and `react-hooks/exhaustive-deps`
  for the runtime faults `tsc` cannot see, plus `local/no-explicit-any` and
  `local/no-ts-suppression` for the two bans above — `strict` permits an
  explicit `any` by design, and a pragma is only a comment, so the compiler
  enforces neither. Both local rules are AST rules
  (`packages/apps/terminal/eslint-local-rules.mjs`); the regular-expression
  script they replaced missed `type Payload = any`. CI runs the gate in
  `node-core-tests`; `python scripts/ft.py lint` runs it alongside ruff.
- **Path alias** `@` → `packages/apps/terminal/src/`. Configured in
  `tsconfig.json` and `vite.config.ts` (the Vitest config lives inside
  `vite.config.ts`, so it inherits the alias).
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
  - `chore: bump flexlayout-react to 0.10.1`

---

## 10. Pull-request flow

1. **Branch off `main`.** During pre-1.0, all commits land directly on
   `main`; for non-trivial work, open a PR to give CI a chance to run.
2. **Run the local checklist** before pushing (one command per line — Windows
   PowerShell 5.1 has no `&&`):
   - `pnpm --filter @flinttrade/terminal typecheck`
   - `pnpm --filter @flinttrade/terminal test` (full suite), or `npx vitest run`
     from `packages/apps/terminal` for affected files
   - `python -m pytest --tb=short --import-mode=importlib`
   - `python scripts/ft.py lint` — the shell-independent way to run
     `ruff check packages/ tests/` *and* the terminal's `eslint src
     --max-warnings=0` lint gate (identical on Windows, macOS and Linux;
     the same scope `make lint` runs on POSIX)
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

### Broker authentication

The OpenAlgo bridge handles its own broker authentication (TOTP, OAuth,
OTP, biometric flows) — FlintTrade only holds the OpenAlgo API key for that
path. The native broker gateway, by contrast, stores broker credentials in
the encrypted vault (`gateway/credentials.py`, Fernet + PBKDF2) and performs
credential-replay / OAuth / TOTP login itself via
`flinttrade_gateway/native_login.py`. New native adapters follow that vault +
gated-session model; never add plaintext credential storage.

### Safety layers

The 5-layer safety system lives in `packages/services/engine/`. Every
order FlintTrade submits goes through admission when it's placed. Every
**Live** order placed through FlintTrade is then checked by those layers.
The submit routes are `POST /api/v1/orders/place`,
`POST /api/v1/orders/<broker>/place`,
`POST /api/v1/positions/exit-all`, and `POST /api/v1/orders/bracket`
when the body has exactly one stop-loss or one target. Each bracket leg
is admitted, then placed through SafetySystem. Practice on that route is
HTTP 403 `practice_unsupported`. GTT, a broker-held variety, a stop-loss
and a target together, and a trailing stop are refused before that
admission. Practice orders skip L1–L5 and go to the Practice fill path.
Practice **place** runs `Laya.admit` before that path; a refusal or a
quantity clamp stops before a simulated fill. A Practice close and a
Practice square-off are opposite orders on place. The Practice fill path
cancels and modifies only. Settings → Practice does not place. Live
operator and automate **place** is checked when it's placed: Mode guard
→ `Laya.admit` → SafetySystem L1–L5 → `gate_order` → `BrokerRouter`.
`"variety": "gtt"` is HTTP 422 `gtt_unsupported`
(`Not placed. GTT orders aren't supported right now.`) before that
path, on place, routed place, exit-all, and a bracket. No submit route reaches a
broker forever or super-order endpoint. The Kotak Neo adapter refuses a
`gtt` place. `POST /api/v1/orders/forever` returns HTTP 501 and does not
place.
Exit-all records a server reduce-only proof before `exit_all_positions`.
`cancel-all` only cancels. Example-data
placement is refused by the backend (HTTP 403 `mode_blocked`,
`Orders are not available for Example. Switch to Practice or Live to trade.`);
Order Pad Example Buy is a local example fill (`Example order placed`, id starting `SAMPLE-`; no HTTP order route, no Laya admit, no
SafetySystem). Other Live write verbs still reach SafetySystem without
this place admission. The global auth check covers both a session JWT
and `FLINTTRADE_API_KEY`. The session JWT is read from
`Authorization: Bearer` or from `X-FlintTrade-Token`. An API key on
`X-FlintTrade-Token` does not pass. An API key is not a session, and
place still needs a JWT mode claim. `GET /healthz` and `GET /readyz` are the public
status-only probes. Runtime fail-fast order in
`_check_order_locked` is **L5 → L4 → L1 → L2 → L3** (not L1–L5 numerical
order):

1. **L5 Kill switch** — explicit operator activation through Telegram, the UI,
   or the API cancels open orders and requests position flattening. Automatic
   account-scoped flattening belongs to the separate rupee MTM circuit breaker.
2. **L4 Daily P&L** — pause subsequent new orders at 3 % daily drawdown and
   latch a new-order hard stop at 15 %. Layer 4 does not cancel or flatten.
3. **L1 Order validation** — price within ±5 % of LTP, quantity within
   lot-multiple bounds.
4. **L2 Position limits** — maximum five simultaneous positions, no
   single position exceeding 60 % of available margin.
5. **L3 Portfolio risk** — net delta and net vega caps.

Do not bypass Laya or SafetySystem on those place paths. If you need a
fast-path for high-frequency orders, add the path inside the layers, not
around them.

### Laya decision sidecar

Operator steps, the chip, and the reason codes are in
[Start Laya](USER_GUIDE.md#start-laya). Desk place surfaces go through
this admission. Place admission asks the Laya model only after Down and
the hard rules.
The host is opt-in. Install and supervise it with the FlintTrade
environment (the project `.venv` after `uv sync`, or `uv run python`),
so `flinttrade_core` and `flinttrade_engine` import. Do not run these
commands with the sidecar interpreter.

```text
python -m flinttrade_core.laya_runtime install
python -m flinttrade_core.laya_runtime start
python -m flinttrade_core.laya_runtime status
python -m flinttrade_core.laya_runtime stop
```

`install` creates `<workspace>/runtime/laya/venv`. On Linux the default
workspace is `~/.flinttrade`. `FLINTTRADE_WORKSPACE_DIR` overrides it.
The sidecar environment can share the base interpreter with FlintTrade:
its `python` is often a symlink to the same executable, and the prefix
compared at install time is the environment directory, not that symlink.
The install refuses a command whose prefix is the FlintTrade environment.
The default install puts CPU torch in the sidecar environment from
`https://download.pytorch.org/whl/cpu`, then `laya[serve]==0.3.21`, so
the CUDA wheels stay out. The constraints file pins `torch==2.14.0+cpu`,
`laya==0.3.21`, `huggingface_hub==1.33.0`, and `tqdm==4.70.1` with no extras
(`packages/core/core/src/flinttrade_core/laya_sidecar_constraints.txt`).
The `serve` extra stays on the install requirement. The CPU install applies
that file to both pip commands, and installs torch first. The install size
is roughly 1.2 GB. CUDA and ROCm
installs do not use the CPU pin. `install --accelerator cuda` opts into the
PyPI torch build. `install --accelerator rocm` needs `LAYA_TORCH_INDEX`
set to an https PyTorch ROCm wheel index. `start` still uses CPU
(`LAYA_DEVICE=cpu`). The host stays `127.0.0.1`. `LAYA_PORT` chooses the
port and defaults to 8000. A clash on that port is Down with
`port_in_use`. A fresh API key is
written to `<workspace>/runtime/laya/api.key` and removed on `stop`, and
on a start that fails after the key was written. When `LAYA_API_KEY_FILE`
points at that same path, `start` replaces the file and does not treat
it as missing. A different path that is not there still refuses with
"The Laya API key file is missing."

`start` downloads the pinned commit (`[checkpoint] revision`, never the
default branch) into `<workspace>/runtime/laya/staging` when the weights
file or any manifest file is not already installed, and when the runtime
checkpoint is on disk but its hashes are not the pin. That directory is
not the launch path and not the shared Hugging Face cache. The download
sets `HF_HOME` to `<workspace>/runtime/laya/hf-home` and
`HF_HUB_DISABLE_XET=1` (read by `huggingface_hub` 1.33.0), so transfer
logs stay in that folder. The step does
not start the sidecar. While it runs, including a pin change, the reason
is `downloading` and the popover is `Downloading the model · X of Y GB` (for example `Downloading the model · 1.2 of 3.4 GB`)
(live, one decimal, decimal GB), with no Next line and no Updating label.
Orders stay on the Down refusal. It then hashes `model.safetensors` and
every manifest file in that staging directory. When no checkpoint is
already there, a full match renames staging onto
`<workspace>/runtime/laya/checkpoint` and launches the offline verified
boot, with hub access off. When a checkpoint is already there, a full
match renames it aside to `checkpoint.old-<random>` in the same runtime
directory, renames staging onto `checkpoint`, then deletes the old copy.
The current copy stays in place until that match. If the second rename
fails, the old checkpoint is renamed back and the reason is
`download_failed`, not `wrong_revision`. A complete download whose files
do not match the pin is `wrong_revision`; staging is deleted and a
checkpoint already on disk is left in place. An extra loadable file in a
complete download is `unverified`. A dropped connection, a partial or
missing file, or a read error is `download_failed` ("Can't download the
model"; tooltip "Check your connection, then Start Laya again."). The
status word for `downloading` and `download_failed` is Down, not Still
loading, and orders use "Laya is Down. New orders are paused until it's Ready. You can still close positions." A non-exit order is HTTP 403. Those failures delete the staging directory and leave the shared
model cache alone. The sidecar does not start on files that do not match
the pin. If the download does not finish, the reason is `download_failed`, not
`wrong_revision` and not `unverified`, whatever older snapshot is on
disk. An empty cache is `download_failed`. `unverified` stays when this
start did not download. A snapshot already on disk is `wrong_revision`
only when this start did not download. Leftover staging
directories and `checkpoint.old-*` copies are removed at the start of
`start` once a checkpoint is in place, with no chip change and no
message. If `checkpoint` is missing and one or more `checkpoint.old-*`
copies remain, the last `checkpoint.old-*` name is restored onto
`checkpoint` and any other aside copies are removed. If that restore fails, the aside copy stays
where it is and that cleanup is skipped. A copy that was restored is then
checked against the pin. If it does not match, the sidecar does not start
on it; the pinned download runs instead, and a failed download leaves
`download_failed` with that copy still on disk. The download log line is
`laya download repo=<repo> revision=<revision>`.
The pins live in `laya_policy.toml`:
`[checkpoint]` names `revision` beside `sha256`, the weights file `model.safetensors`, and
`[checkpoint.manifest]` pins `rl_agent_config.json`,
`encoder/config.json`, `tokenizer/tokenizer_config.json`, and
`tokenizer/tokenizer.json` by sha256.

A backend that was started with `LAYA_HOST=127.0.0.1`, `LAYA_PORT` (or
the default 8000), and `LAYA_API_KEY_FILE` pointing at that `api.key`
attaches on its health probe. The host must stay loopback. The attached
client uses the same revision and digest checks. On each sidecar start
FlintTrade hashes `model.safetensors` and each file in
`[checkpoint.manifest]` before launch. The runtime record holds the
sha256, pid, and start token, and each file's inode, size, and
modification time in nanoseconds
(`<workspace>/runtime/laya/verification.json`, with the token and pid
also in `run.json`). When the files are already on disk and this start is not replacing them,
a missing pinned file, a shard index, or any extra weights file or other
file the launcher could read is `unverified` ("Can't verify the model")
and the sidecar does not start. A changed byte in a snapshot that this
start is not replacing is `wrong_revision` ("Wrong model version") and the
sidecar does not start. A changed byte in the runtime checkpoint is the
download above; the sidecar does not start on that tree. Laya does not
reach Ready in these cases. A verified boot sets
`LAYA_WEIGHTS_PATH` to that hashed weights file. A model already in the
standard Hugging Face cache is accepted. When that file is the cache
symlink (`snapshots/<revision>/model.safetensors` into `blobs/`), it is
passed as the snapshot file, not the blob. A blob path is still refused.
The boot runs offline
(`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`). It does not pass a repo
id or a revision. When that sidecar's health document leaves the revision
null, FlintTrade fills the pinned revision from the verified manifest, so
the chip leaves Still loading and can reach Ready without a download in
this process. The launch log line is
`laya weights path=<path> sha256=<digest>`. Those identity values are
rechecked, without hashing again, when Laya reports Ready and on each
watch tick, about every 1.5 seconds. A mismatch is `unverified`
("Can't verify the model"). The log line is
`laya weights path=<path> changed=<field>` where `<field>` is `inode`,
`size`, `mtime`, or a comma-separated list of those, and `<path>` is the
file that changed. The same watch reads the pid file
(`runtime/laya/sidecar.pid`), the key file (`runtime/laya/api.key`), and
the runtime record, so a command-line stop or start, or a key rotation,
is reconciled by that watch. The desk polls `GET /api/v1/ping` every
1.5 seconds. That ping reconciles the pid, the key, and the runtime
record the same way an order does, so the chip and the order gate read
the same state. A stop or a start shows on the chip by the next 1.5-second check.
After Start Laya, until the ping confirms the new state, the chip says
Checking in the neutral colour and the popover says Checking Laya…. It
does not show a stale Ready during that wait. An admitted place while
the chip is not Ready or Degraded also shows Checking until the next
ping. A confirmed first load
still says Still loading. A place refused with exactly "Laya is Down. New orders are paused until it's Ready. You can still close positions." sets the chip to Down on that
response. The refusal line is unchanged. Every `stop` deletes the runtime
record, as does a start that fails after it was written. A record from
an earlier run is rejected. A health document without the weight digest
is Ready when that record matches the pin. If the record cannot be
checked, the reason is `unverified` ("Can't verify the model"). The
tooltip is "The installed model couldn't be checked against the pinned
version. Restart Laya. If it keeps happening, reinstall it."

`status` carries a reason code: `not_started`, `stopped`, `port_in_use`,
`still_loading`, `downloading`, `download_failed`, `unreachable`,
`wrong_revision`, `unverified`, `key_rejected`, or `key_missing`. `identity_absent` is
not a status code. The desk shows Not started, Stopped,
`Port <n> in use`, Still loading, `Downloading the model · X of Y GB`,
Can't download the model, Unreachable, Wrong model version, Can't verify
the model, Can't reach Laya, and The Laya API key file is missing.
`key_missing` stays until a later start finds the file, or an explicit
stop. When `LAYA_API_KEY_FILE` names `<workspace>/runtime/laya/api.key`,
that next `start` replaces the file and does not treat it as missing. A
different path that is not there still refuses with "The Laya API key
file is missing." A health
check does not replace it with Not started. The download progress class
subclasses the pinned `tqdm==4.70.1` (`tqdm.auto.tqdm`). The model is
about 2.37 GB, and the progress line reports that size once. `unverified` applies when this start did
not download. A failed download, including one over an older unverified
snapshot, is `download_failed` ("Can't download the model"). `<n>` is the
sidecar port. Tooltips for
`not_started`, `stopped`, `port_in_use`, `still_loading`, and
`unreachable` are the label followed by
`. Next: python -m flinttrade_core.laya_runtime start`. `downloading`
has no tooltip. The `download_failed` tooltip is "Check your connection,
then Start Laya again." The `wrong_revision` tooltip is "Laya is running a different model than
FlintTrade expects." That code is only a real mismatch: a complete
download whose files do not match the pin, a snapshot already on disk
that this start is not replacing, or a running sidecar that reports
another revision or digest. A dropped connection, a partial download, or
a failed download or swap, including one that puts the previous
checkpoint back, is `download_failed`, not this code. The `key_rejected`
tooltip is "Laya restarted with a new key. Reconnecting…" The chip stays
Down and orders are refused. When a place is refused because Laya cannot
be reached, or because it rejects the key, the chip updates on that same
order: Unreachable, or Can't reach Laya. Every chip-Down refusal reads
"Laya is Down. New orders are paused until it's Ready. You can still close positions." A
dead child is reaped on the health probe and on interpreter exit, and
the probe records Down with Stopped. `POST /api/v1/laya/start` starts or
restarts the managed sidecar for a signed-in operator session. A
port that another process holds, including one that is not Laya, is Down
with `Port <n> in use`. The first load, before health is usable, is Still
loading. Orders stay refused with the Down sentence while that load
runs. After a successful load, a later miss is Unreachable.

`GET /health` then records Practice Ready or Degraded from the sidecar.
Live stays Down until a `LayaQualification` record uses
`EvidenceUseScope.LIVE_DECISION` for that exact revision, digest, and
policy version. A base checkpoint is not that record. An unreachable
host, a timeout, a malformed response, or a revision or digest mismatch
is Down, and Practice refuses too. A decision without `revision` or
`sha256` is checked against this run's verified record for both admitted
and clamped orders. The decision log is
`<workspace>/runtime/laya/decisions.jsonl`. It stores `proof=decision`
or `proof=runtime`. An admitted Practice place with an empty note skips
the model and writes one line, `effect=clamp` with `failure=note_absent`
and no proof, including when the quantity already fits. When this run's
record stood in, each model allow keeps its own `effect=allow`
`proof=runtime` line. There is no dedupe. When the chip is Ready and a model decision
carries no proof, the refusal code is `laya_unverified` and the decision log records
`identity_absent` with no proof. The refusal reads "Not placed. Laya's
decision couldn't be verified. Try again." Stopping the sidecar records
Down before an in-flight probe can publish Ready. An empty note is
uncertain and is not a hard reject:
Practice clamps and Live denies. The Practice server reason is "Laya is
uncertain. Quantity stays inside the tighter limit." The Live server
reason is "Laya is uncertain. Live stays closed." On a denial, Order Pad
and Quick Trade show that server reason inside one alert (`role="alert"`),
the only live region. The reason line is named "Laya decision" and is not
its own status.
A clamp is only when the requested quantity is greater than the allowed one. The desk clamp
sentence is "Not placed. Laya allows up to N." Place N sends that
quantity. On Order Pad, "Review Practice order" then shows the placed
quantity. Place 1 on "Not placed. Laya allows up to 1." places. Nothing
is placed until Place N.
Order Pad sends that note as `rationale`, including when the field is
empty. The collapsed control is "Add a reason (optional)". Once open, the
field's accessible name is the same. Quick Trade, Positions square-off,
Order Ladder, Scalper, and Option Chain use that accessible name too.

The same client speaks `POST /v1/systemone`. An operator may point it at
another loopback host, including one on port 8888, without adding that
host's software as a dependency. Do not vendor Unsloth Studio. Chat
profiles stay separate from the `decision` service kind. Catalogue ids
under that kind are `decision:laya-managed` and
`decision:systemone-endpoint`; they are not chat profiles, their default
evidence scope is offline qualification until a Live qualification record
exists, and listing them does not start the host.

### Vite dev proxy paths

In `packages/apps/terminal/`, the dev server proxies:

| Route prefix | Target |
|---|---|
| `/api` | `http://127.0.0.1:5000` (OpenAlgo) |
| `/ft-api` | `http://127.0.0.1:5100` (FlintTrade backend) |
| `/ws` | `ws://127.0.0.1:8765` (OpenAlgo WebSocket) |

In dev mode, `packages/apps/terminal/src/services/api.ts` uses *relative*
paths (empty base URL). In production, it reads the full host from the
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

### Home and Invest net worth

Home and Invest share `accountNetWorth` in
`packages/apps/terminal/src/lib/accountNetWorth.ts`. The total is ledger
cash, including blocked margin, plus holdings at market value, plus each
open position. Opening an F&O position does not reduce
the total by its margin. A Practice round trip at an unchanged price
leaves the total at the starting cash, for example ₹10,00,000. The Invest
label is `Net Worth (Cash + Holdings + Positions)`. Options, and equity positions that are not
already holdings, add signed market value: last traded price × quantity
when that price is positive, otherwise the entry price × quantity.
Futures add unrealised P&L.

Dhan's funds set `futures_mtm_in_ledger`. The futures base is `buyAvg`
on a long and `sellAvg` on a short (`mark_source: "avg"`). When that
average is absent, the base is `costPrice` and `mark_source` is
`"fallback"`. Kotak Neo's funds also set `futures_mtm_in_ledger`. An
open future has no settlement price, so the base is the open-leg
average and `mark_source` is `"fallback"`. Practice sets
`futures_mtm_in_ledger` false and does not set a mark source, so a
future marks from the entry price.

`"fallback"` on an open future, while earlier mark-to-market is already
in the ledger, formats the amount with `≈` (`formatAccountNetWorth`).
Home puts `≈` and the tooltip on the Net Worth amount; the `Net Worth`
label has the tooltip only. Invest Dashboard puts the tooltip on the
label `Net Worth (Cash + Holdings + Positions)` and `≈` plus the tooltip
on the amount under it. The Net Worth view does the same for
`Known Total (Cash + Holdings + Positions)`, and puts both on the
`Open Positions` value. Available Funds on Dashboard shows `≈` with no
tooltip. The donut centre shows `≈` with no tooltip. The tooltip text is `approximateNetWorthTooltip`. A missing
Dhan average uses
`Approximate. Your broker didn't send an average price for NIFTY-JUN2026-FUT, so profit or loss from earlier days may be counted twice.`
A Kotak Neo open-leg estimate uses
`Approximate. The price for NIFTY25JUNFUT is estimated from the open position's average, so profit or loss from earlier days may be counted twice.`
One symbol is named, and several positions of that kind use
`N futures positions`. When both kinds are open, the tooltip is
`Approximate. Your broker didn't send an average price for NIFTY-JUN2026-FUT, and the price for NIFTY25JUNFUT is estimated from the open position's average, so profit or loss from earlier days may be counted twice.`
The accessible name is
`accountNetWorthAccessibleName` (`Net Worth, approximately …`). A flat
quantity, or `mark_source: "avg"`, clears it. Practice never shows `≈`.
Allocation percentages are not marked. Invest publishes the total only
after the position book has loaded (`positionBookReady` in
`InvestContext`). Home uses that same check in `PortfolioCard`: while
the book is pending or has failed, the amount is `—`, never a cash-only
figure. The sample book does not wait on that book. The amount appears
once positions have loaded, including when it is negative: `-₹50,000`,
or `≈ -₹50,000` when the mark is approximate. Home allocation stays on
the Example split until funds, holdings, and positions have all
succeeded (`PortfolioCard`). That split uses `ExampleLabel`, not
`ExampleChip`.

The Home greeting is `useOperatorGreetingName` in
`packages/apps/terminal/src/routes/home/operatorGreetingName.ts`. The
saved display name wins. The username is the fallback. `Trader` is the
unset placeholder and is never shown. Hour buckets are Asia/Kolkata in
`getIstGreeting`.

Real holdings on Benchmark use `HOLDINGS_RETURN_LEGEND`
(`Your holdings (unrealised)`), with `HOLDINGS_RETURN_TOOLTIP` and
table label `HOLDINGS_RETURN_LABEL` (`Unrealised return on holdings`).
That row has no Example mark. An empty book, and example holdings, use
`Your Portfolio`. Example holdings add `ExampleLabel` on the row.
`BenchmarkTab` renders `ExampleChip` with `always` on the hard-coded
index returns, so the chip stays in Practice and Live. Each index row
also renders `ExampleLabel`.

Home Open Positions percent is `formatPositionPnlPercent` in
`packages/apps/terminal/src/routes/home/PositionsCard.tsx`. Cost is the
absolute average price times quantity. The percent is P&L divided by cost when cost is above zero; otherwise
the cell is `—`.
Dhan and Neo rows do not carry `pnlPercent`.

Sample Invest figures use `ExampleChip`
(`packages/apps/terminal/src/components/ui/ExampleChip.tsx`), which
paints when the session is example data unless `always` is set.
Correlation, ETF Screener, ETFs, Risk-Return, Sector, Sector Rotation,
Shareholding, and Social render that chip, not `ExampleLabel`.
`SocialTab` renders exactly one, after loading has finished.
`EtfTab` in Example renders one, with
`Example prices. Connect a broker for live quotes.`
Practice and Live keep
`live quotes via OpenAlgo. Refreshes every 30s`
when quotes have loaded.
`SectorTab` in Example uses
`Example sector split. Connect a broker to see yours.`
and
`Example data. Not from your holdings.`,
with one chip.
`BasketTab` renders one in Example, including while quotes are loading
and after they have loaded.
`HoldingsTab` renders one. `DashboardTab` renders one on the inline
sample XIRR. It does not render one on sample Portfolio Allocation, and
that block omits the connected-book sentence. It does not render a
Portfolio XIRR card. Net Worth, Available Funds, Invested Value, and
Day P&L paint their final formatted value on the first frame, with no
count-up from zero, including `≈`, `-₹50,000`, and `—`. With no
holdings the inline XIRR is omitted.
`NetWorthTab` sample copy is
`Example equity and cash. Connect a broker to see yours.`,
with the chip on the sample `Allocation` label only. Equity Holdings
and Cash notes are blank on example data. A connected book keeps
`Allocation (live assets only)` and `Live from broker`.

### OpenAlgo bugs to work around

1. **Sandbox sends real orders for some brokers.** Verify isolation
   before testing.
2. **`closeposition` ignores strategy.** Track positions per-strategy
   yourself.
3. **WebSocket drops without heartbeat.** The terminal client in
   `packages/apps/terminal/src/services/websocket.ts` implements ping/pong.
   The Python `OpenAlgoClient` is REST-only apart from `ping`.
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
