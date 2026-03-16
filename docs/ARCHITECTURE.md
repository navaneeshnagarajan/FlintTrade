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

## Infrastructure & Deployment

### Makefile

The `Makefile` is the primary interface for development and operations:

```bash
make setup      # First-time install (deps, submodules, data dirs)
make start      # Start OpenAlgo service
make stop       # Stop OpenAlgo
make status     # Show service and port status
make test       # Run all 662 tests
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
| `infra/scripts/setup.sh` | First-time installation on fresh Ubuntu 24.04 |
| `infra/scripts/start-openalgo.sh` | Start OpenAlgo as background process |
| `infra/scripts/stop-openalgo.sh` | Stop OpenAlgo gracefully |
| `infra/scripts/status.sh` | Show service status, ports, disk usage |
| `infra/scripts/health-check.sh` | Health check (exit 0/1 for monitoring) |
| `infra/scripts/deploy-production.sh` | Production deploy with market hours guard |

### systemd

Service templates are in `infra/systemd/`. They require manual placeholder
replacement before installation. See `infra/systemd/README.md`.

### Configuration

All configuration comes from `.env` (never committed). `.env.example` serves
as the template. Key variables:

- `OPENALGO_HOST` / `OPENALGO_PORT` — OpenAlgo API connection
- `OPENALGO_API_KEY` — Authentication
- `DATA_DIR` / `AUDIT_LOG_DIR` — Storage paths
- `BROKER` — Which broker is configured in OpenAlgo
- `TELEGRAM_BOT_TOKEN` — For /kill switch and alerts

### Docker

`docker-compose.yml` provides cross-platform development:

```bash
make docker-up     # Start all services
make docker-down   # Stop
make docker-build  # Rebuild images
```
