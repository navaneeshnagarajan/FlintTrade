# FlintTrade Architecture

## Package Dependency Graph

```
┌─── FlintTrade (one repo) ─────────────────────────────────┐
│                                                            │
│  terminal (React + TypeScript, Dockview workspace)         │
│      │                                                     │
│      ├── screener ─── ai                                   │
│      │      │          │                                   │
│      ├── engine ◄──── backtest-engine                      │
│      │      │          │                                   │
│      ├── core ◄──── data ◄── historical                    │
│      │      │                                              │
│      └── automation ──── integration ── ditto               │
└────────────────────┼───────────────────────────────────────┘
                     │ REST API + WebSocket
              ┌──────┴───────┐
              │   OpenAlgo   │ external service (separately installed)
              │  33 brokers  │ — local-dev clone: .local/external/openalgo/
              └──────────────┘
```

## Frontend Architecture (terminal)

The terminal is a single React + TypeScript application using **Dockview** for a
widget-composable workspace. Users build their own layouts by dragging and
docking widgets (charts, order pad, positions, option chain, etc.).

### State Management

| Layer | Library | Purpose |
|-------|---------|---------|
| Global UI state | Zustand | Theme, layout, connection status, settings |
| Per-widget state | Jotai | Atomic state for individual widget instances |
| Server state | TanStack Query | API data fetching, caching, polling |

### Key Frontend Dependencies

| Library | Purpose |
|---------|---------|
| Dockview + dockview-react | Widget docking and layout management |
| shadcn/ui + Radix UI | Accessible, themeable UI components |
| TanStack React Table | High-performance data tables |
| Glide Data Grid | Virtualized grids for option chains and order books |
| react-hook-form + zod | Form validation |
| TradingView Lightweight Charts v5 | Financial charting |
| Tailwind CSS v4 | Utility-first styling |

## Safety Layers (engine)

1. Order validation (price ±5% LTP, qty limits)
2. Position limits (max 5 simultaneous, 60% margin)
3. Portfolio risk (net delta/vega limits)
4. Daily P&L limit (3% pause, 15% kill)
5. Kill switch (Telegram, UI, auto-trigger)

## Configuration Architecture

FlintTrade uses a two-tier configuration model:

### Tier 1: `.env` — Infrastructure only

The `.env` file (never committed) contains only OpenAlgo connection settings:

```
OPENALGO_HOST=http://127.0.0.1:5000
OPENALGO_PORT=5000
OPENALGO_API_KEY=<your key>
OPENALGO_WS_PORT=8765
```

Broker credentials are configured in OpenAlgo directly, not in FlintTrade.

### Tier 2: `~/.flinttrade/workspace.json` — User preferences

Everything else lives in a cross-platform workspace directory:

| Platform | Location |
|----------|----------|
| Linux | `~/.flinttrade/` |
| macOS | `~/Library/Application Support/flinttrade/` |
| Windows | `%APPDATA%/flinttrade/` |
| Override | `FLINTTRADE_HOME` env var |

The `workspace.json` file contains:
- **Storage paths** — `storage.fast` (SSD) and `storage.archive` (HDD)
- **Enabled modules** — which packages are active
- **UI preferences** — theme, default exchange, timezone
- **LLM config** — provider, host, model
- **Notification config** — Telegram bot settings
- **SEBI settings** — rate limits, audit retention, kill switch

API keys and tokens are stored as `_ref` fields (references). Actual secrets
should be stored in the OS keyring or as environment variables.

### How packages read config

```python
from packages.core.src.config import FlintTradeConfig

config = FlintTradeConfig.from_env()
config.settings.openalgo_host     # from .env
config.workspace.fast_data_dir    # from workspace.json
config.workspace.get("ui.theme")  # dot-notation access
```

Packages never read `os.environ` for data paths directly. They use the
`Workspace` class which resolves paths from workspace.json with fallbacks.

## Infrastructure & Deployment

### Makefile

The `Makefile` is the primary interface:

```bash
make setup      # First-time install (deps, workspace)
make start      # Start OpenAlgo service
make stop       # Stop OpenAlgo
make status     # Show service and port status
make test       # Run all tests
make lint       # Run ruff linter
make dev        # Start React dev servers + OpenAlgo
make health     # Run health check
make clean      # Remove build artifacts
make update     # Update Python + Node deps
```

OpenAlgo and OpenClaw are no longer git submodules; for local development clone them once via `bash scripts/setup-test-deps.sh` (see "External Test Dependencies" below).

### External Test Dependencies

OpenAlgo and OpenClaw are external services that FlintTrade communicates with over HTTP/WebSocket. They are NOT bundled with FlintTrade and are NOT git submodules. End users install them separately as prerequisites; contributors can run `scripts/setup-test-deps.sh` to clone local-dev copies into `.local/external/` (gitignored). AlgoMirror is intentionally absent — its mirroring patterns are absorbed in-process by `packages/ditto/` and the upstream repo is no longer tracked.

| Service | Local-dev clone path | Source | Role |
|---------|----------------------|--------|------|
| OpenAlgo | `.local/external/openalgo/` | [marketcalls/openalgo](https://github.com/marketcalls/openalgo) | broker gateway |
| OpenClaw | `.local/external/openclaw/` | [openinterface-ai/openclaw](https://github.com/openinterface-ai/openclaw) | AI agent gateway |

### Scripts

| Script | Purpose |
|--------|---------|
| `infra/scripts/setup.sh` | First-time installation |
| `infra/scripts/openalgo/start-openalgo.sh` | Start OpenAlgo as background process |
| `infra/scripts/openalgo/stop-openalgo.sh` | Stop OpenAlgo gracefully |
| `infra/scripts/status.sh` | Service status, ports, disk usage |
| `infra/scripts/health-check.sh` | Health check (exit 0/1) |
| `scripts/setup-test-deps.sh` | Clone OpenAlgo + OpenClaw external test-deps to `.local/external/` |
| `scripts/reset-flinttrade-state.sh` | Wipe `~/.flinttrade/` for a fresh-user test without touching OpenAlgo |

### Broker Authentication

Broker login is handled entirely by OpenAlgo (not by FlintTrade).
FlintTrade connects via API key only. If the OpenAlgo session expires,
the terminal notifies the user to re-authenticate at the OpenAlgo web interface.

### Docker

```bash
make docker-up     # Start all services
make docker-down   # Stop
make docker-build  # Rebuild images
```
