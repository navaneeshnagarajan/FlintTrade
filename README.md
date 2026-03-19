# FlintTrade

![Tests](https://img.shields.io/badge/tests-696%20passed-brightgreen)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Node](https://img.shields.io/badge/node-20%2B-blue)
![License](https://img.shields.io/badge/license-AGPL--3.0-orange)
![Status](https://img.shields.io/badge/status-pre--alpha-red)

> **Pre-alpha** — Under active development. Not ready for production trading.
> Use with sandbox/paper trading only.

Open-source modular trading platform for Indian markets, built on [OpenAlgo](https://openalgo.in). Supports 30+ brokers, equities, F&O, commodities, currency derivatives, and crypto.

## What is FlintTrade?

FlintTrade is a self-hosted trading platform that sits on top of OpenAlgo. OpenAlgo handles broker connections and order execution across 30+ Indian brokers. FlintTrade handles everything else: strategy execution, risk management, backtesting, real-time analysis, AI-powered signals, and multi-account orchestration.

The platform is organized into 11 independent packages (10 Python + 1 React). Use what you need — the option chain screener doesn't require the AI module, and the backtester doesn't require a live broker connection. Each package has its own source, tests, and documentation.

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
│  │engine    │ │  ticks   │ │ mirror   │              │
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
| **terminal** | React + TypeScript trading terminal — Dockview workspace, widget-composable, scalper, option chain, charts | ✅ Built |
| Infrastructure | Makefile, systemd, Docker, deploy scripts | 🔨 In Progress |

## Current State

**What works:**
- 11 packages with source code and **696 passing tests** (670 Python + 26 terminal)
- Async OpenAlgo v2 API client with 45+ endpoint wrappers
- 5-layer safety system (order validation → position limits → portfolio risk → P&L limits → kill switch)
- Per-exchange market hours (NSE/NFO 15:30, CDS 17:00, MCX 23:30, DELTA 24/7)
- 12 backtest strategy templates (EMA crossover, Supertrend, straddle sell, iron condor, etc.)
- React terminal with Dockview widget-composable workspace
- Docker Compose for cross-platform development

**What's in progress:**
- Infrastructure automation (`make setup`, `make start` end-to-end)
- Git submodules for OpenAlgo, OpenClaw, AlgoMirror
- Live WebSocket data feed in terminal UI

**What's planned:**
- End-to-end live trading verification against broker sandbox
- OpenClaw AI agent integration for autonomous trading
- Production monitoring and alerting

## Quick Start

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
pip install -r requirements.txt
python -m pytest packages/*/tests/ tests/ -v --import-mode=importlib  # 696 tests
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
| Foundation | Monorepo, 11 packages, 696 tests, CI | ✅ Complete |
| Infrastructure | Makefile, systemd, deploy scripts, git submodules | 🔨 In Progress |
| Live Connection | OpenAlgo sandbox trading, WebSocket data | 📋 Next |
| Terminal | Live option chain, scalper, real-time charts | 📋 Planned |
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
| Python | 3.11+ | Backend, strategy engine, AI |
| Node.js | 20+ | React terminal UI |
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

Key upstream projects:
[OpenAlgo](https://github.com/marketcalls/openalgo) ·
[AlgoMirror](https://github.com/marketcalls/algomirror) ·
[OpenClaw](https://github.com/openclaw/openclaw) ·
[Historify](https://github.com/marketcalls/historify) ·
[FastScalper](https://github.com/marketcalls/fastscalper-tauri) ·
[OpenTerminal](https://github.com/marketcalls/OpenTerminal) ·
[OpenEngine](https://github.com/marketcalls/openengine)
