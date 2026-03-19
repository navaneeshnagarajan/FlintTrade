<p align="center">
  <img src="docs/assets/logo.svg" alt="FlintTrade" width="120" />
</p>

# FlintTrade

![Tests](https://img.shields.io/badge/tests-738%20passed-brightgreen)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Node](https://img.shields.io/badge/node-22%2B-blue)
![License](https://img.shields.io/badge/license-AGPL--3.0-orange)
![Status](https://img.shields.io/badge/status-pre--alpha-red)

> **Pre-alpha** — Under active development. Not ready for production trading.
> Use with sandbox/paper trading only.

Open-source modular trading platform for Indian markets, built on [OpenAlgo](https://openalgo.in). Supports 30+ brokers, equities, F&O, commodities, currency derivatives, and crypto.

## What is FlintTrade?

FlintTrade is a self-hosted trading platform that sits on top of OpenAlgo. OpenAlgo handles broker connections and order execution across 30+ Indian brokers. FlintTrade handles everything else: strategy execution, risk management, backtesting, real-time analysis, AI-powered signals, and multi-account orchestration.

The platform is organized into 12 independent packages (11 Python + 1 React). Use what you need — the option chain screener doesn't require the AI module, and the backtester doesn't require a live broker connection. Each package has its own source, tests, and documentation.

FlintTrade is not a broker, not a data vendor, and not a hosted service. It's a platform you run on your own hardware, with your own broker accounts, under your own control. It's designed for SEBI-compliant algorithmic trading in India.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                     FlintTrade                        │
│                                                      │
│  ┌────────────────────────────────────────────┐      │
│  │  terminal (React + TypeScript)              │      │
│  │  Dockview workspace, widget-composable UI   │      │
│  │  shadcn/ui, Zustand + Jotai, TanStack Query │      │
│  └────────────────────┬───────────────────────┘      │
│                       │                              │
│  ┌──────────┐ ┌───────┴──┐ ┌──────────┐             │
│  │  engine  │ │   core   │ │    ai    │  Python      │
│  │  safety  │ │  client  │ │  signals │  backend     │
│  │  router  │ │  models  │ │  RAG     │              │
│  └────┬─────┘ └─────┬────┘ └──────────┘             │
│       │             │                                │
│  ┌────┴─────┐ ┌─────┴────┐ ┌──────────┐             │
│  │screener  │ │   data   │ │historical│  Analysis    │
│  │backtest- │ │  audit   │ │ ditto    │  & data      │
│  │engine    │ │  ticks   │ │indicators│              │
│  └──────────┘ └──────────┘ └──────────┘             │
│                     │                                │
│  ┌──────────┐ ┌─────┴────┐                          │
│  │automaton │ │integratn │  Automation               │
│  │  cron    │ │ webhooks │  & hooks                  │
│  │ telegram │ │ flow     │                           │
│  └──────────┘ └──────────┘                          │
└────────────────────┬─────────────────────────────────┘
                     │ REST API + WebSocket
              ┌──────┴──────┐
              │   OpenAlgo  │  Managed service (port 5000)
              │  30+ brokers│
              └──────┬──────┘
                     │
              ┌──────┴──────┐
              │  Your Broker │  Dhan, Zerodha, Angel, Fyers,
              │   Account    │  Kotak, Upstox, Delta, 25+ more
              └─────────────┘
```

## Modules

| Module | Description | Status |
|--------|-------------|--------|
| **core** | OpenAlgo API client (45+ endpoints), config, models | ✅ Built |
| **engine** | Strategy execution, order routing, 5-layer safety system | ✅ Built |
| **data** | Tick capture, trade logs, DuckDB storage, SEBI audit trail | ✅ Built |
| **historical** | Multi-source downloader, free NSE data, DuckDB/Parquet pipeline | ✅ Built |
| **screener** | Option chain, OI analysis, futures quadrant, Greeks, IV | ✅ Built |
| **backtest-engine** | Event-driven simulator, 12 strategies, walk-forward optimizer | ✅ Built |
| **ai** | LLM client, RAG, ML signals, sentiment, MCP bridge | ✅ Built |
| **integration** | TradingView webhooks, ChartInk, visual flow builder | ✅ Built |
| **automation** | Cron jobs, Telegram bot, OpenClaw bridge | ✅ Built |
| **ditto** | Multi-account mirroring, margin calculator, trailing SL | ✅ Built |
| **indicators** | TA-Lib (batch, 150+ indicators) + Numba (streaming) + PineTS (Pine Script conversion) | ✅ Built |
| **terminal** | React + TypeScript trading terminal — Dockview workspace, widget-composable, scalper, option chain, charts | ✅ Built |
| Infrastructure | Makefile, systemd, Docker, deploy scripts | 🔨 In Progress |

## Current State

**What works:**
- 12 packages with source code and **738 passing tests** (712 Python + 26 terminal)
- Async OpenAlgo v2 API client with 45+ endpoint wrappers
- 5-layer safety system (order validation → position limits → portfolio risk → P&L limits → kill switch)
- Per-exchange market hours (NSE/NFO 15:30, CDS 17:00, MCX 23:30, DELTA 24/7)
- 12 backtest strategy templates (EMA crossover, Supertrend, straddle sell, iron condor, etc.)
- React terminal with Dockview widget-composable workspace
- Docker Compose for cross-platform development

**What's complete (Phases 1-9):**
- TypeScript strict mode migration (zero JSX/JS files remain)
- Dockview v5.1 widget-composable workspace with 21 widgets (all TSX)
- 7 functional tools (Settings, P&L Dashboard, Strategy Builder, Trade Journal, Flow Builder, Market Intelligence, Backtest Lab)
- State architecture: Zustand 5 + Jotai + TanStack Query 5 (replaced DataBus)
- Setup wizard (/setup), Investor dashboard (/invest), Learn center (/learn)
- Git submodules for OpenAlgo, OpenClaw, AlgoMirror
- Live WebSocket data feed with ping/pong heartbeat
- Indicators package (13 indicators, 42 tests)
- CI: GitHub Actions (python-tests, node-tests, secrets-check)

**What's planned:**
- Live testing and performance optimization (Phase 10)
- OpenClaw AI agent integration for autonomous trading
- Production monitoring and alerting

## Quick Start

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
pip install -r requirements.txt
python -m pytest packages/*/tests/ tests/ -v --import-mode=importlib  # 738 tests
```

Full `make setup` deployment is under development. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

### Docker (development)

```bash
cp .env.example .env
# Edit .env — add OPENALGO_API_KEY
docker compose up
```

## Roadmap

| Phase | What | Status |
|-------|------|--------|
| Foundation | Monorepo, 12 packages, 738 tests, CI | ✅ Complete |
| Infrastructure | Makefile, systemd, deploy scripts, git submodules | ✅ Complete |
| Live Connection | OpenAlgo sandbox trading, WebSocket data | ✅ Complete |
| Terminal | 21 widgets, 7 tools, 4 routes, Dockview v5.1 | ✅ Complete |
| AI Integration | OpenClaw agent skills, autonomous signals | 📋 Planned |
| Production | SEBI compliance verification, multi-broker, monitoring | 📋 Future |

## SEBI Compliance

FlintTrade is designed for SEBI-compliant algorithmic trading:

- **Static IP** — Required for order APIs. Enforced at broker level.
- **Rate limiting** — 10 orders/second hard limit (engine layer).
- **Kill switch** — Cancel all orders + close all positions in one command. Accessible via Telegram `/kill`, API, or safety system auto-trigger.
- **Audit trail** — Every order, modification, and cancellation logged as append-only JSONL with gzip rotation. 5-year retention per SEBI requirement.
- **Algo registration** — Strategy IDs mapped to broker-registered algo IDs.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.12+ | Backend, strategy engine, AI |
| Node.js | 22+ | React terminal UI |
| OpenAlgo | v2.0+ | Broker connectivity (runs as managed service) |
| DuckDB | 1.0+ | Analytics database (installed via pip) |
| Docker | 24+ | Optional — for cross-platform deployment |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, branch strategy, and commit conventions.

During pre-release (v0.x), all work goes directly to `main`. Feature branches and pull requests activate at v1.0.0.

## License

[AGPL-3.0](LICENSE) — same license as OpenAlgo.

## Acknowledgements

Built on [OpenAlgo](https://openalgo.in) by [Rajandran R](https://github.com/marketcalls) and the OpenAlgo community.

### Upstream Projects
- [OpenAlgo](https://github.com/marketcalls/openalgo) — Broker gateway (AGPL-3.0)
- [AlgoMirror](https://github.com/marketcalls/algomirror) — Multi-account mirroring
- [OpenClaw](https://github.com/openclaw/openclaw) — AI agent framework
- [FastScalper](https://github.com/marketcalls/fastscalper-tauri) — Scalper UI patterns
- [OpenTerminal](https://github.com/marketcalls/OpenTerminal) — Terminal reference
- [OpenEngine](https://github.com/marketcalls/openengine) — Strategy engine

### Code Absorbed (with attribution)
FlintTrade absorbs and adapts code from these open-source projects:

| Project | Author | License | What We Used |
|---------|--------|---------|--------------|
| [openalgo-flow](https://github.com/marketcalls/openalgo-flow) | Marketcalls | AGPL-3.0 | Flow Builder tool (React Flow + node types) |
| [etftracker](https://github.com/marketcalls/etftracker) | Marketcalls | MIT | Investor dashboard patterns, sector rotation |
| [trading-journal](https://github.com/marketcalls/trading-journal) | Marketcalls | MIT | Trade Journal tool |
| [trading-strategies-openalgo](https://github.com/WINDY-WINDWARD/trading-strategies-openalgo) | WINDY-WINDWARD | MIT | Backtest strategies |
| [openalgo-portfoliogreeks](https://github.com/marketcalls/openalgo-portfoliogreeks) | Marketcalls | MIT | Greeks calculator patterns |
| [pyindicators](https://github.com/pyindicators/pyindicators) | PyIndicators | MIT | Indicator algorithm reference |
| [openalgo-chart](https://github.com/marketcalls/openalgo-chart) | Marketcalls | — | Sector heatmap, risk calculator patterns |
| [Historify](https://github.com/marketcalls/historify) | Marketcalls | — | Historical data patterns |

### Libraries
- [Dockview](https://github.com/mathuo/dockview) — Docking layout framework (MIT)
- [Lightweight Charts](https://github.com/nicfv/Lightweight-Charts) — Financial charting (Apache-2.0)
- [shadcn/ui](https://ui.shadcn.com/) — UI components (MIT)
- [Glide Data Grid](https://github.com/glideapps/glide-data-grid) — High-performance grid (MIT)
