# FlintTrade

**Open-source algorithmic and manual trading platform built on [OpenAlgo](https://openalgo.in).**

One clone. One command. Full trading infrastructure.

---

## What is FlintTrade?

FlintTrade bundles everything a trader needs into a single repo: trading terminal (equities, F&O, commodities, currency), strategy engine, backtesting, AI-powered analysis, data pipelines, multi-broker orchestration, and deployment infrastructure — all built on top of OpenAlgo's 30+ broker integrations.

**Key principles:**
- **Complete** — application + infrastructure + AI in one repo
- **Broker-agnostic** — works with any broker OpenAlgo supports
- **Multi-market** — equities, F&O, MCX commodities, currency derivatives, crypto derivatives (Delta Exchange)
- **Self-hosted** — your data, your server, your control
- **AI-native** — local LLM integration for autonomous trading
- **Open source** — AGPL-3.0, community-driven

## Quick Start

```bash
git clone --recursive https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
cp .env.example .env    # Add broker creds, LLM config
make setup              # Installs OpenAlgo + all deps + systemd services
make start              # Everything comes alive
# Open http://localhost:3000 → FlintTrade terminal
```

## Modules

| Module | What it does |
|---|---|
| **core** | Framework, CLI, OpenAlgo API client, configuration |
| **engine** | Strategy execution, order routing, 5-layer safety system |
| **terminal** | Scalper, option chain, 50-level DOM, OI analysis, charts |
| **dashboard** | Portfolio overview, P&L tracking, market overview |
| **ai** | LLM chat, RAG, ML signals, news sentiment, autonomous trading |
| **data** | Real-time tick capture, trade logs, SEBI audit trails |
| **historical** | Multi-source historical data, DuckDB/Parquet, free NSE data |
| **screener** | Market scanner, OI spurt, PCR, max pain, portfolio Greeks |
| **backtest** | Backtest UI with equity curves, performance metrics |
| **backtest-engine** | Event-driven simulation, vectorbt strategies, slippage modeling |
| **integration** | TradingView, ChartInk, webhooks, Chrome extension, Excel, Amibroker |
| **automation** | ML pipeline, cron, Telegram bot, OpenClaw agent, TOTP auto-login |
| **ditto** | Multi-broker, multi-account trade orchestration |

## Architecture

```
FlintTrade (this repo)
  ├── packages/13 modules (application layer)
  ├── infra/openalgo/ (managed service — 30+ brokers)
  ├── infra/openclaw/ (AI agent gateway)
  └── infra/ (nginx, systemd, WireGuard, fail2ban, cron)
          │
          ▼
    OpenAlgo REST API + WebSocket
          │
          ▼
    Any supported broker (Dhan, Zerodha, Angel, Upstox, Kotak, Fyers, 25+ more)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Always squash and merge.

```bash
git checkout dev && git pull
git checkout -b feature/{package}-{description}
# develop, test, commit, push
# PR to dev (requires 1 approval)
```

## License

[AGPL-3.0](LICENSE) — same as OpenAlgo.

## Acknowledgements

Built on [OpenAlgo](https://openalgo.in) and 25+ open-source projects by [Rajandran R](https://github.com/marketcalls) and the OpenAlgo community.
