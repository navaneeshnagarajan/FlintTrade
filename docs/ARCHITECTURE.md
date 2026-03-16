# FlintTrade Architecture

## Package Dependency Graph

```
┌─── FlintTrade (one repo) ────────────────────────────────┐
│                                                           │
│  terminal ─── dashboard ─── screener ─── ai              │
│      │             │            │          │              │
│               engine ◄──── backtest-engine                │
│                    │            │                         │
│               core ◄──── data ◄── historical             │
│                    │                                     │
│            automation ──── integration ── ditto           │
└────────────────────┼──────────────────────────────────────┘
                     │ REST API + WebSocket
              ┌──────┴───────┐
              │   OpenAlgo   │ infra/openalgo/ (git subtree)
              │  30+ brokers │
              └──────────────┘
```

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
make setup      # First-time install (deps, submodules, workspace)
make start      # Start OpenAlgo service
make stop       # Stop OpenAlgo
make status     # Show service and port status
make test       # Run all tests
make lint       # Run ruff linter
make dev        # Start React dev servers + OpenAlgo
make health     # Run health check
make clean      # Remove build artifacts
make update     # Update submodules + deps
```

### Upstream Dependencies

| Directory | Source | Type |
|-----------|--------|------|
| `infra/openalgo/` | [marketcalls/openalgo](https://github.com/marketcalls/openalgo) | git subtree |
| `infra/openclaw/` | [openinterface-ai/openclaw](https://github.com/openinterface-ai/openclaw) | git subtree |
| `infra/algomirror/` | [marketcalls/algomirror](https://github.com/marketcalls/algomirror) | git submodule |

### Scripts

| Script | Purpose |
|--------|---------|
| `infra/scripts/setup.sh` | First-time installation |
| `infra/scripts/start-openalgo.sh` | Start OpenAlgo as background process |
| `infra/scripts/stop-openalgo.sh` | Stop OpenAlgo gracefully |
| `infra/scripts/status.sh` | Service status, ports, disk usage |
| `infra/scripts/health-check.sh` | Health check (exit 0/1) |

### Broker Authentication

Broker login (TOTP, OAuth, PIN, SMS OTP) is handled entirely by OpenAlgo.
FlintTrade connects via API key only. If the OpenAlgo session expires,
the dashboard notifies the user to re-authenticate at the OpenAlgo web interface.

### Docker

```bash
make docker-up     # Start all services
make docker-down   # Stop
make docker-build  # Rebuild images
```
