# FlintTrade Architecture

> Reflects `v0.0.1`. 18 package surfaces (13 Python + 3 apps: React
> terminal, Electron desktop shell, Next.js site + 1 shared TypeScript
> design-system package + 1 Rust/PyO3 tick engine).
> Run `make test` and terminal Vitest locally for the current test counts.

This document is the architectural reference for contributors. For a
user-facing overview, see [USER_GUIDE.md](USER_GUIDE.md). For HTTP /
WebSocket contracts, see [API.md](API.md). For repo conventions, see
[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).

---

## 1. High-level component diagram

```mermaid
flowchart LR
    subgraph Clients["Browser / Electron client"]
        T[Terminal React App]
        DESKTOP[Electron 40 shell]
        SITE[Public docs site]
        DS[Design system]
        DESKTOP --> T
    end

    subgraph ManagedDesktop["Managed desktop source · user home"]
        TOOLS[Checksum-verified tools]
        SOURCE[Active source checkout]
        GUARDIAN[Python source guardian]
        DESKTOP -- "bootstrap / update" --> TOOLS
        DESKTOP -- "build / promote" --> SOURCE
        DESKTOP -- "start / drain" --> GUARDIAN
        SOURCE --> GUARDIAN
    end

    subgraph Backend["FlintTrade backend (Python)"]
        F[Flask app · port 5100]
        E[engine]
        S[screener]
        AI[ai]
        D[data]
        H[historical]
        BT[backtest]
        AUT[automation]
        DIT[ditto]
        JNL[journal]
        IND[indicators]
        ING[webhooks]
        GW[gateway]
        TICK[ticks · Rust/PyO3]
    end

    subgraph NativeGateway["Native gateway · beta"]
        NGA[adapter contract + routing]
        DHAN[Dhan · Upstox · Kotak Neo · INDmoney · Groww<br/>adapters built to parity]
    end

    subgraph OpenAlgo["OpenAlgo · port 5000 / WS 8765 (optional external service)"]
        OA[broker adapters]
    end

    subgraph LocalAI["Managed local AI · loopback only (optional)"]
        OLL[Ollama server · private dynamic port]
        MODELS[Workspace model store]
        OLL --> MODELS
    end

    subgraph Brokers["Brokers (live)"]
        B1[Zerodha · Upstox · Fyers · Angel · ...]
    end

    T -- "/api/v1/* + /ft-api/v1/* (HTTP)" --> F
    GUARDIAN --> F
    T -- "WS /ws (port 8765 via proxy)" --> OA
    SITE -- "generated docs + read-only MCP" --> DS
    T --> DS
    F --> E
    F --> S
    F --> AI
    AI -- "OpenAI-compatible API" --> OLL
    F --> D
    F --> H
    F --> BT
    F --> AUT
    F --> DIT
    F --> JNL
    F --> ING
    F --> GW
    E --> TICK
    BT --> TICK
    IND --> TICK
    F --> NGA
    NGA --> DHAN
    F -- "REST" --> OA
    OA --> B1
```

Source/browser deployments default to the FlintTrade backend on port 5100 and
reach it through `/ft-api`. The Electron guardian instead starts its managed
backend with `--port 0`, consumes the announced dynamic loopback port, and
loads the terminal from that selected origin. OpenAlgo on 5000 and its
WebSocket on 8765 are optional external integration origins, proxied through
Vite only when that bridge is enabled. The native
gateway contract and routing are present, and the five founder-broker adapters
(Dhan, Upstox, Kotak Neo, INDmoney, Groww) remain dormant unless their activation
gates pass. The current connectable native set is Dhan and Upstox
after live login/read verification and emergency-planner coverage. INDmoney is
read-verified and its fail-closed planner is locally verified, but it remains
`connectable=false`: active regular `EQ-`/`DRV-` MARKET/LIMIT rows cannot yet be
distinguished authoritatively from smart parents after restart, and the broker
does not expose an atomic reduce-only close primitive. A funded/live-market
order-safety proof is still required. Kotak Neo and Groww are built and
catalogued but also kept `connectable=false` until their broker-specific blockers clear:
Kotak Neo's fail-closed planner is locally verified, but it still needs a successful
live adapter login/read probe and order-safety proof, while Groww
has approved-key login/account-read proof but still needs market-data/API
permission, static-IP resolution, and order-safety proof.
Portal/static-IP evidence is not enough by itself to promote them.

The Electron shell has machine authority but no trading authority. It owns
tool acquisition, the managed checkout, source promotion, the source guardian,
native windows and shell updates. The renderer receives named
`window.flintDesktop` methods only. The Python backend continues to own all
trading, authentication, configuration and durable user data.

Desktop source lives at `~/.flinttrade/src/FlintTrade` and verified tools at
`~/.flinttrade/tools`. User data remains in the platform workspace. First
launch builds a sibling candidate with the frozen repository locks, promotes it
only after the build completes, then requires both the guardian's exact ready
sentinel and a loopback `/api/v1/ping` response before the main window opens.
Updates use the same separation: the running checkout is immutable, candidate
health proof uses an isolated temporary workspace, and promotion retains one
last-known-good source for rollback.

The Electron installer is not the application runtime. A release contains the
shell and bootstrap resources only. Source/runtime updates and shell-installer
updates are separate flows. No Electron installer release is published yet; the
previous Tauri and PyInstaller release assets have been retired and do not
satisfy this architecture.

When the operator selects managed Ollama, the backend owns an on-demand sidecar
process. FlintTrade selects an unpredictable free high loopback port, starts
Ollama there, and accepts the endpoint only after proving process-tree listener
ownership. A competing bind makes startup fail closed. FlintTrade downloads the pinned runtime only after explicit
confirmation, verifies its SHA-256 digest before extraction, disables Ollama
cloud access, and stores models under the platform workspace. Accepted model
digests are stored separately from Ollama's model store. Explicit acceptance
creates a digest-derived locked alias, which each inference verifies before the
request and against the loaded digest afterwards before releasing output. Cloud
and custom OpenAI-compatible providers remain available;
intentionally self-hosted servers belong under the `custom` provider.
Runtime releases live in separate version directories. A stopped update stages
and verifies the preferred release before atomically selecting it, retaining one
fully rehashed rollback release. Uninstall transactionally quarantines only
fully verified releases recognised by the current build, recovers an interrupted
transaction at the next startup, and preserves models and trust metadata. Every
lifecycle mutation holds an owner-only cross-process workspace lease. Lifecycle,
receipt-journal and operation-owner lease paths reject links, reparse points,
non-regular files and foreign POSIX ownership before use. A backend restart never
signals an inherited PID; if Ollama survives its owner, lifecycle changes fail
closed until the operator terminates that process. Model reclamation is
API-driven: exact unselected names and unreferenced FlintTrade locked aliases can
be removed, but FlintTrade never traverses Ollama's blob store to delete files.
Browser mutations carry a durable client admission ID, making a lost or timed-out
HTTP response idempotently reconcilable through status. A bounded detailed
receipt journal compacts older terminal admission IDs into a fail-closed spent-ID
filter; corrupt journals and unknown outcomes never reopen admission. Shutdown consumes one
deadline across config-lock and runtime-state admission, operation cancellation,
inference drain and teardown. Destructive model operations hold the runtime-state
lock through live inventory and trust reconciliation, so shutdown either cancels
before the irreversible request or waits for its verified result. Windows production
children are contained in a private Job Object;
POSIX process-group identifiers are never signalled after the retained root has
been reaped.

---

## 2. Package dependency graph

```mermaid
flowchart TD
    desktop -. "boots managed source" .-> terminal
    desktop -. "starts source guardian" .-> core
    terminal --> core
    terminal --> ditto
    terminal --> screener
    terminal --> ai
    terminal --> automation
    terminal --> webhooks
    terminal --> engine
    terminal --> historical
    terminal --> designSystem[design-system]

    site --> designSystem
    site --> docs[docs/]

    engine --> core
    engine --> data
    engine --> gateway
    backtestEngine[backtest] --> engine
    backtestEngine --> tickEngine[ticks]
    backtestEngine --> historical
    backtestEngine --> indicators

    screener --> data
    screener --> historical
    screener --> indicators

    ai --> core
    ai --> data
    journal --> data
    journal --> core

    webhooks --> core
    webhooks --> engine

    automation --> core
    automation --> engine

    ditto --> engine
    ditto --> gateway

    historical --> data
    historical --> core

    data --> core
    indicators --> core
    gateway --> core
```

Solid arrows point from dependent to dependency. The dashed desktop edges are
runtime orchestration, not JavaScript or Python package imports. Runtime code lives under
`packages/{apps,core,integrations,services}`. The public site and terminal
both consume the shared design-system package; the site also consumes
repository docs and package READMEs to generate its pages, docs MCP, and
llms files.

---

## 3. Frontend architecture (terminal)

The terminal is a single React 19 + TypeScript application built with
Vite 6. Layout is managed by [Dockview v5.1](https://dockview.dev/),
which provides drag-and-drop panels, tabs, floating windows, and
serialisable layouts. Users compose their workspace from 97 widgets
(26 trading + 44 analysis + 27 utility) split across 12 routes.

### State architecture

```mermaid
flowchart LR
    WS[OpenAlgo WebSocket\nport 8765] --> J[Jotai atoms\nper-instrument LTP/Quote/Depth]
    REST[REST API\n/api/v1 + /ft-api/v1] --> TQ[TanStack Query cache\npositions, orders, holdings, funds, optionchain]
    J --> Z[Zustand stores\nconnection, layout, settings, aggregated P&L, mode]
    TQ --> Z
    Z --> UI[Widgets and routes]
    J --> UI
    TQ --> UI
```

**Boundary rules** — data enters through one path only and is never
duplicated:

- **Jotai atoms** — WebSocket real-time data only.
- **TanStack Query** — REST API responses only.
- **Zustand stores** — derived and UI state only (connection status,
  active layout, settings mirror, aggregated P&L, current mode).

### Frontend stack

| Category | Library | Why it's pinned |
|---|---|---|
| Language | TypeScript 5 (strict) | No `any`, no `@ts-ignore`. |
| Framework | React 19 | Server Actions, `use()`, the new compiler. |
| Build | Vite 6.4 | Fast HMR, ESM-first. |
| CSS | Tailwind CSS v4 | `@tailwindcss/vite` plugin, no `tailwind.config.js` for tokens. |
| Components | shadcn/ui | Copy-paste ownership, Radix accessibility primitives. |
| Layout | Dockview v5.1 | Floating, tabs, popout, JSON-serialisable. |
| Charts | Flint chart core over Lightweight Charts v5 | Runtime adapter, shared theme, drawing, indicator, and mini-chart contracts. |
| Streaming grid | Glide Data Grid | Canvas-rendered, 100K updates/sec. |
| Static grid | TanStack Table v8 | Headless, sortable, filterable. |
| State | Zustand v5 + Jotai + TanStack Query v5 | Separation of concerns by boundary. |
| Forms | react-hook-form + zod | Runtime validation, type inference. |
| Router | react-router-dom | Lazy-loaded route modules. |

### Chart ownership boundary

The terminal app does not create chart engines directly. Runtime value imports
from `lightweight-charts` are isolated to
`packages/apps/terminal/src/lib/lightweightChartRuntime.ts`, the runtime adapter
that bridges vendor APIs into Flint-owned chart contracts. The shared chart
surface lives in `packages/core/design-system/src/charts/`:

- `lightweight.ts` owns chart factories, theme application, canvas labelling,
  series registration contracts, and reusable layout constants such as
  `FLINT_TRANSPARENT_CHART_LAYOUT`.
- `theme.ts` owns the Flint market-chart palette derived from design-system
  tokens.
- `drawings.ts` owns drawing persistence, draft progression, hit-testing,
  movement, handles, render specs, and the drawing render-plan contract
  (`createFlintChartDrawingRenderPlan`) that maps drawings to line series,
  price lines, and markers. It also owns render-plan lifecycle diffing through
  `createFlintChartDrawingRenderPlanDiff`, so terminal hooks reconcile
  added, updated, unchanged, and removed drawing artefacts from core specs
  instead of rebuilding unchanged chart series.
- `indicators.ts` owns indicator defaults, periods, panes, colours,
  serialisation, static indicator line/histogram render specs, pane-aware
  series option contracts through `createFlintChartIndicatorSeriesRenderPlan`,
  series lifecycle diffing through
  `createFlintChartIndicatorSeriesRenderPlanDiff`, and OI overlay render
  semantics such as `createFlintChartOIProfileBarData`.
- `plotly.ts` owns `createFlintPlotlyTheme`, the shared default Plotly config,
  and layout merging for advanced charts that cannot use Lightweight Charts.
- `components.tsx` owns React-visible chart primitives such as legend rows,
  mini sparklines, donut breakdowns, and ranked bars.

Application widgets may pass data and user intent into these contracts, but
they should not call `createChart`, `chart.addSeries`, `createSeriesMarkers`,
or import Lightweight Charts runtime values directly. Terminal hooks may attach
or remove series through `lightweightChartRuntime.ts`, but render decisions must
come from the core contracts. The terminal regression test
`src/hooks/__tests__/flintChartCore.test.ts` enforces this boundary so new chart
work remains built on the core rather than around it.

Plotly is the explicit runtime exception for heavy 3D analysis surfaces that
Lightweight Charts cannot represent well, such as volatility surfaces. The
shared theme, modebar defaults, and axis/layout merge policy live in core via
`createFlintPlotlyTheme`, `FLINT_PLOTLY_DEFAULT_CONFIG`, and
`mergeFlintPlotlyLayout`. The terminal keeps only the heavy Plotly runtime
wrapper in `src/components/charts/PlotlyChart.tsx`, so Plotly stays lazy-loaded,
documented, and limited to analysis modules.

---

## 4. Backend architecture

FlintTrade's backend is a single Flask application registered as
`packages/core/core/src/flinttrade_core/app.py`. Source/browser mode defaults to
port 5100; the Electron source guardian explicitly selects a dynamic loopback
port instead. The application mounts every package's blueprints behind
`/v1/*`, and exposes them externally under `/ft-api/v1/*` thanks to the WSGI
prefix-strip middleware (see §6).

**One backend process per workspace.** In-memory job/runner state (scheduler
jobs, download queues, sandbox runtime, session registries) assumes a single
authoritative process. That constraint is enforced, not assumed:
`backend_instance.py` acquires a kernel-backed workspace lock before the
runtime starts (both the `run()` and WSGI entrypoints), and a second launch
against the same workspace fails fast with `BackendInstanceAlreadyRunning`.
The HTTP server (waitress) is single-process/threaded, so no multi-worker
deployment can split that state.

### Safety layers

Every order placed through FlintTrade passes five safety layers in order
inside `packages/services/engine/`:

1. **Order validation** — price within ±5 % of LTP, quantity multiple of
   lot size.
2. **Position limits** — max five simultaneous positions, no single
   position over 60 % of free margin.
3. **Portfolio risk** — net delta and net vega caps across the book.
4. **Daily P&L** — pause new orders at 3 % drawdown and latch a new-order
   hard stop at 15 % drawdown. Layer 4 does not cancel or flatten.
5. **Kill switch** — an explicit operator action (UI button, API, or Telegram)
   that cancels open orders and requests position flattening through the gated
   broker path. The account MTM circuit breaker is a separate automatic path.

### Mode-system state machine

```mermaid
stateDiagram-v2
    [*] --> Explore
    Explore --> Practice: /auth/mode {mode:practice}
    Practice --> Live: /auth/mode {mode:live} + password\nconfirm
    Live --> Practice: /auth/mode {mode:practice}
    Practice --> Explore: /auth/mode {mode:explore}
    Live --> Explore: /auth/mode {mode:explore}\n(forces kill-switch)

    state Explore {
        [*] --> noOrders
        noOrders: All order paths return\nsimulated success without\ntouching OpenAlgo
    }
    state Practice {
        [*] --> sandbox
        sandbox: Orders routed to FlintTrade's\nnative sandbox engine
    }
    state Live {
        [*] --> realOrders
        realOrders: Orders routed to a native broker\nadapter or OpenAlgo-compatible endpoint;\nsafety layers active
    }
```

Each transition issues a fresh JWT with the new `mode` claim and revokes
the old token's `jti`. The guard lives at
`packages/services/engine/src/flinttrade_engine/mode_guard.py`.

---

## 5. Data flow

```mermaid
flowchart TD
    Tick[OpenAlgo WS tick] --> Atom[Jotai atom\nltpAtomFamily(symbol)]
    Atom --> Derived[Derived atoms\nPCR · straddle · greeks]
    Derived --> UI1[Charts · Option Chain · Order Pad]

    REST[REST poll · TanStack Query] --> Cache[Query cache\npositions · orders · holdings]
    Cache --> UI2[Positions · Orderbook · Funds]

    UI1 --> Order[Order placement\nthrough engine]
    UI2 --> Order
    Order --> Safety[5-layer safety system]
    Safety --> ModeGuard[Mode guard]
    ModeGuard --> Router[Broker router]
    Router --> Sandbox[Native sandbox\npractice mode]
    Router --> Adapter[Native adapter or\nOpenAlgo-compatible API]
    Adapter --> Broker[Broker]
    Broker -. fill .-> Tick
```

Ticks fan in to per-instrument Jotai atoms which power every chart and
quote widget. REST data populates a separate query cache. Orders flow
out through the safety layers and the mode guard. Practice orders stay
inside FlintTrade's native sandbox; live orders route through a native
broker adapter or an OpenAlgo-compatible endpoint. Fills come back through
the tick stream and reconcile with the REST cache via
`packages/services/engine/src/flinttrade_engine/reconciliation.py`.

---

## 6. WSGI prefix strip

The terminal calls `/ft-api/v1/X`. The Vite dev proxy and the production
reverse proxy forward that to the FlintTrade backend on port 5100. The
WSGI middleware in `packages/core/core/src/flinttrade_core/app.py` strips the `/ft-api`
prefix before URL dispatch:

```
External:  GET /ft-api/v1/gex?symbol=NIFTY
            │
            ▼  (Vite proxy or reverse proxy)
Backend:   GET /v1/gex?symbol=NIFTY
            │
            ▼  (Flask URL map)
Handler:   screener.analysis_routes:gex_handler
```

This means a blueprint registered at `url_prefix="/v1"` (or
`url_prefix="/api/v1"`, depending on the route family) answers requests
at the external `/ft-api/v1/…` path automatically. **Never
double-prefix.** Routes documented in [API.md](API.md) as
`/ft-api/v1/X` are the external view; routes documented as `/v1/X` are
the internal view of the same endpoint.

---

## 7. Configuration architecture

Workspace-first with a dev/server fallback.

### Tier 1: `workspace.json` — UI-owned runtime configuration

Lives in a platform-specific workspace directory:

| Platform | Location |
|---|---|
| Linux | `~/.flinttrade/` |
| macOS | `~/Library/Application Support/flinttrade/` |
| Windows | `%APPDATA%/flinttrade/` |
| Override | `FLINTTRADE_HOME` env var |

`workspace.json` contains:

- **OpenAlgo bridge settings** — host, WebSocket port, and OpenAlgo API key
  written by Setup/Settings when that optional bridge is enabled.
- **Storage paths** — `storage.fast` (SSD) and `storage.archive` (HDD).
- **Enabled modules** — which packages are active.
- **UI preferences** — theme, default exchange, time zone, density.
- **LLM config** — provider and model; the managed Ollama endpoint is owned
  internally and is not persisted, while custom OpenAI-compatible providers
  retain an editable host.
- **Notification config** — Telegram bot settings.
- **Order-safety settings** — rate limits, audit retention, kill-switch.

Native broker credentials live in the encrypted gateway vault. OpenAlgo broker
credentials remain inside OpenAlgo; FlintTrade stores only the OpenAlgo API key.

### Tier 2: `.env` — advanced dev/server fallback

Lives in the repo root, never committed. Native desktop users do not need it.
Docker/systemd deployments and contributor experiments may use it for
`FLINTTRADE_API_KEY`, proxy/deployment flags, and fallback OpenAlgo settings
when the app UI is not available.

### How packages read config

```python
from flinttrade_core.config import FlintTradeConfig

config = FlintTradeConfig.from_env()
config.settings.openalgo_host     # from workspace.json, with .env fallback
config.workspace.fast_data_dir    # from workspace.json
config.workspace.get("ui.theme")  # dot-notation access
```

Packages never read `os.environ` for data paths directly. They use the
`Workspace` class, which resolves paths from `workspace.json` with
fallbacks.

---

## 8. Authentication

### FlintTrade JWT

- Issued on `/ft-api/v1/auth/login` after argon2id password
  verification.
- Optional second factor: TOTP enrolment with Fernet-encrypted seed.
- **Expires at 8 AM IST the next day.** No refresh tokens — sign in
  again.
- Carries `sub` (user), `exp` (expiry), `mode` (Explore / Practice /
  Live), `jti` (unique ID).
- Revocation blocklist keyed by `jti` in
  `packages/core/core/src/flinttrade_core/auth_state.py`.

### Server-side mode enforcement

Every order-path endpoint asks `mode_guard` whether the JWT permits a
live action. Trying to place a live order on a Practice JWT is rejected 403
immediately with code `practice_unsupported` (Explore mode yields
`mode_blocked`) — the request never reaches OpenAlgo.

### OpenAlgo X-API-Key

OpenAlgo's own endpoints use API-key auth, forwarded as the
`X-API-KEY` header by `packages/core/core/src/flinttrade_core/openalgo_client.py`. The key
comes from workspace config, with `.env` retained as an advanced fallback.

---

## 9. Infrastructure and deployment

### Makefile

`Makefile` is the primary interface:

```bash
make setup      # first-time install (deps, workspace)
make start      # start FlintTrade backend
make stop       # stop FlintTrade backend
make status     # show service and port status
make test       # run all Python tests
make test-fast  # stop on first failure
make lint       # run ruff
make dev        # start React dev server + FlintTrade backend
make health     # health check
make clean      # remove build artefacts
make update     # update Python + Node deps
```

OpenAlgo is an external service; it is NOT a git submodule and is NOT
bundled. For local development, run `scripts/setup-test-deps.sh` once per
machine to clone a local-dev copy into `.local/external/`.

### External test dependencies

| Service | Local-dev path | Source | Role |
|---|---|---|---|
| OpenAlgo | `.local/external/openalgo/` | [marketcalls/openalgo](https://github.com/marketcalls/openalgo) | Broker gateway. |

AlgoMirror is intentionally absent — its mirroring patterns are reimplemented
natively in `packages/services/ditto/` (our own code; the upstream repo is not
tracked, pulled, or called at runtime).

### Scripts

| Script | Purpose |
|---|---|
| `infra/scripts/setup.sh` | First-time installation. |
| `infra/scripts/openalgo/start-openalgo.sh` | Start OpenAlgo as a background process. |
| `infra/scripts/openalgo/stop-openalgo.sh` | Stop OpenAlgo gracefully. |
| `infra/scripts/status.sh` | Service status, ports, disk usage. |
| `infra/scripts/health-check.sh` | Health check (exit 0/1). |
| `scripts/setup-test-deps.sh` | Clone OpenAlgo to `.local/external/`. |
| `scripts/reset-flinttrade-state.sh` | Wipe the FlintTrade workspace for a fresh-user test. |

### Docker

```bash
make docker-up     # start all services
make docker-down   # stop
make docker-build  # rebuild images
```

### Production

Production deployments use `systemd` units under `infra/systemd/`. See
[setup/linux.md](setup/linux.md) for the canonical recipe.

---

## 10. Where to read more

- HTTP and WebSocket contract — [API.md](API.md)
- How to contribute — [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)
- Per-version change notes — [releases/](releases/)
- CI behaviour — [CI.md](CI.md)
- Supported brokers / exchanges / platforms — [COMPATIBILITY.md](COMPATIBILITY.md)
- Order safety notes — [ORDER_SAFETY.md](ORDER_SAFETY.md)
