<p align="center">
  <img src="https://flinttrade.vercel.app/flinttrade/logo.svg?v=20260530" alt="FlintTrade logo" width="120" />
</p>

# FlintTrade

> Open-source modular trading platform for Indian F&O, commodities, and crypto.

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-orange.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.6.0--alpha-orange.svg)](VERSION)
[![CI](https://img.shields.io/badge/CI-local%20verified-brightgreen.svg)](https://github.com/navaneeshnagarajan/FlintTrade/actions/workflows/test.yml)
[![Tests](https://img.shields.io/badge/tests-terminal%202159%20%7C%20repo%2016-brightgreen.svg)](#)
[![Status](https://img.shields.io/badge/status-alpha%20not%20production%20ready-orange.svg)](disclaimer.md)
[![Website](https://img.shields.io/badge/website-live-blue.svg)](https://flinttrade.vercel.app)

A self-hosted trading workspace that turns a native broker gateway contract, optional OpenAlgo-compatible integrations, real-time tick streams, and a strategy engine into one keyboard-driven cockpit you actually own.

<p align="center">
  <a href="https://flinttrade.vercel.app/flinttrade/screenshots/01-welcome.png?v=20260530"><img src="https://flinttrade.vercel.app/flinttrade/screenshots/01-welcome.png?v=20260530" alt="Cinematic welcome screen on first launch" width="48%" /></a>
  <a href="https://flinttrade.vercel.app/flinttrade/screenshots/04-trade.png?v=20260530"><img src="https://flinttrade.vercel.app/flinttrade/screenshots/04-trade.png?v=20260530" alt="Trade canvas with Dockview widget-composable workspace" width="48%" /></a>
</p>
<p align="center">
  <a href="https://flinttrade.vercel.app/flinttrade/screenshots/08-ai.png?v=20260530"><img src="https://flinttrade.vercel.app/flinttrade/screenshots/08-ai.png?v=20260530" alt="AI Centre with chat, signals, sentiment, and RAG panels" width="48%" /></a>
  <a href="https://flinttrade.vercel.app/flinttrade/screenshots/06-lab.png?v=20260530"><img src="https://flinttrade.vercel.app/flinttrade/screenshots/06-lab.png?v=20260530" alt="Strategy Lab for backtest, forward test, and walk-forward optimisation" width="48%" /></a>
</p>

## Alpha disclaimer

FlintTrade `v0.6.0-alpha` is **not production ready**. It is educational,
self-hosted trading software for research, paper trading, and contributor
development first. Nothing in this repository is financial, investment, tax,
legal, or regulatory advice. Read [disclaimer.md](disclaimer.md) before
connecting a broker or enabling Live mode.

## What it does

- **Intraday F&O scalping** — sub-second order entry, bracket orders, hotkey-driven OrderPad, kill switch wired to Telegram and the UI.
- **Multi-broker support** — one workspace for FlintTrade's native gateway scaffolding plus optional OpenAlgo-compatible integrations; switch accounts without leaving the canvas.
- **Options analysis** — option chain with OI heatmaps, IV smile, max-pain, GEX, portfolio Greeks, payoff visualiser, and a futures quadrant.
- **Paper trading mode** — three-mode safety model (Explore / Practice / Live) with server-enforced isolation; learn without risking capital.
- **AI-assisted signals** — local LLM chat (LM Studio), ChromaDB RAG over your trades, LightGBM signal pipeline, news sentiment, and a multi-agent risk debate.
- **Custom strategies** — 94 backtest templates, Pine Script conversion, walk-forward optimisation, Monte Carlo, and tick-level simulation in Rust.
- **Automation flows** — visual flow builder, cron scheduler, TradingView and ChartInk webhooks, Telegram and WhatsApp alerts.
- **Multi-account orchestration** — Ditto module mirrors orders across child accounts with margin-aware sizing and trailing stop-loss.

## Supported brokers

FlintTrade's native broker gateway contract and routing are in alpha, with the Dhan direct adapter scaffolded and gated pending SDK attestation. Optional [OpenAlgo](https://github.com/marketcalls/openalgo)-compatible integrations remain available — see [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for the current matrix.

## Quickstart (5-minute Docker)

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
cp .env.example .env   # optional: set OPENALGO_API_KEY if using OpenAlgo
docker-compose up
```

Open <http://localhost:5173> and follow the welcome wizard.

> OpenAlgo is optional. Run it on port 5000 only if you want the OpenAlgo integration path; FlintTrade's own backend runs on port 5100.

---

## For developers

### Architecture

```mermaid
flowchart LR
    subgraph FT["FlintTrade"]
        UI["Terminal<br/>React 19 + TypeScript<br/>Dockview workspace"]
        BE["Python backend<br/>Strategy engine, AI,<br/>backtest, screener"]
        TE["tick-engine<br/>Rust + PyO3"]
        UI <-->|"/ft-api/v1/"| BE
        BE <--> TE
    end

    BG["Broker gateway<br/>native adapters"]
    OA["OpenAlgo-compatible<br/>optional integration<br/>port 5000"]
    BR["Broker API"]

    BE <-->|"native broker contract"| BG
    BE <-->|"REST + WebSocket"| OA
    BG <-->|"broker auth"| BR
    OA <-->|"broker auth"| BR
```

FlintTrade runs its own backend, native sandbox, and broker gateway contract. OpenAlgo remains an optional external integration for users who already rely on its broker gateway.

### Package map

17 package surfaces — 13 Python packages, 2 React applications, 1 shared
TypeScript design-system package, and 1 Rust/PyO3 tick engine.

| Package | Language | Purpose |
|---|---|---|
| `packages/apps/site` | Next.js + TS | Public website, generated documentation, and read-only docs MCP |
| `packages/apps/terminal` | React + TS | Single-page workspace, home widgets, routes, tools, and Dockview terminal |
| `packages/core/core` | Python | Flask backend, auth, workspace, OpenAlgo-compatible client, route registration |
| `packages/core/data` | Python | Tick capture, audit log, trade logging, SQLite sandbox state, DuckDB analytics storage |
| `packages/core/design-system` | TypeScript | Shared FlintTrade tokens, brand primitives, layers, and React components |
| `packages/core/historical` | Python | OHLCV downloader, free-data sources, DuckDB/Parquet pipeline, expiry manager |
| `packages/core/indicators` | Python + Numba | TA-Lib batch indicators, Numba streaming variants, Pine conversion |
| `packages/core/ticks` | Rust + PyO3 | High-performance tick processing for tick-level backtests |
| `packages/integrations/gateway` | Python | Native broker gateway, adapter pattern, credential vault, WebSocket bridge |
| `packages/integrations/webhooks` | Python | TradingView, ChartInk, custom webhooks, visual flow builder |
| `packages/services/ai` | Python | LLM client, RAG, ML signals, sentiment, MCP bridge, advisor workflows |
| `packages/services/automation` | Python | Cron jobs, Telegram bot, OpenClaw bridge, post-market analysis |
| `packages/services/backtest` | Python | Event-driven simulator, 94 strategy templates, walk-forward optimiser |
| `packages/services/ditto` | Python | Multi-account mirroring, margin calculator, trailing stop-loss |
| `packages/services/engine` | Python | 5-layer safety system, order router, scheduler, strategy registry |
| `packages/services/journal` | Python | Trade journal, execution-quality analytics, realised P&L tracking |
| `packages/services/screener` | Python | Option chain, OI analysis, PCR, max-pain, portfolio Greeks, IV smile |

### Tech stack

| Layer | Tools |
|---|---|
| Frontend | React 19, TypeScript 5 (strict), Tailwind CSS v4, Dockview v5, shadcn/ui, Lightweight Charts v5, Glide Data Grid, Zustand 5, Jotai, TanStack Query 5 |
| Backend | Python 3.12, Flask, httpx (async), pydantic, DuckDB, structlog |
| Data | TA-Lib (batch indicators), Numba (streaming), Rust/PyO3 (tick engine), QuestDB (future) |
| AI | LM Studio (local LLM), ChromaDB (vector store), LightGBM (signals), MCP bridge |

### Three ways in

- **Try it** — follow the [5-minute Docker quickstart](#quickstart-5-minute-docker) above and explore in paper mode.
- **Build with it** — read the [Developer Guide](docs/DEVELOPER_GUIDE.md) for repo layout, adding widgets, and adding broker adapters.
- **Contribute** — see [contributing.md](contributing.md) for branch strategy, commit conventions, and good-first-issues.

---

## Project documentation

| Guide | What's inside |
|---|---|
| [User Guide](docs/USER_GUIDE.md) | Install, first connection, paper trade, workspace tour |
| [Developer Guide](docs/DEVELOPER_GUIDE.md) | Repo layout, dev setup, adding widgets and strategies |
| [Architecture](docs/ARCHITECTURE.md) | Diagrams, data flow, mode system, auth, WSGI |
| [API Reference](docs/API.md) | FlintTrade `/ft-api/v1/` endpoints plus broker/OpenAlgo-compatible bridge routes |
| [Disclaimer](disclaimer.md) | Alpha-stage, no-advice, trading-risk, and user-responsibility notice |
| [Changelog](changelog.md) | Release notes by version |
| [Security](security.md) | Disclosure policy, supported versions, threat model |

## Community

- [GitHub Discussions](https://github.com/navaneeshnagarajan/FlintTrade/discussions) — questions, ideas, show-and-tell.
- [GitHub Issues](https://github.com/navaneeshnagarajan/FlintTrade/issues) — bug reports and feature requests.
- [contributing.md](contributing.md) — how to propose changes, run tests, and open a PR.

## Credits

FlintTrade is a native-first platform: its backend, native gateway contract,
safety/gating layer, and most application code are original work. It
interoperates with [OpenAlgo](https://github.com/marketcalls/openalgo) through an
optional bridge adapter rather than bundling its source. Some widgets and modules
were adapted from open-source projects (each marked in-source with an "Absorbed
from:" header); their licences and attribution are preserved in [notice](notice).
See [docs/REFERENCES.md](docs/REFERENCES.md) for the full influence notes.

## License

FlintTrade is released under [AGPL-3.0](LICENSE). If you modify and run
FlintTrade as a network service, you must publish your modified source.

## Code of Conduct

This project follows the Contributor Covenant. By participating you agree to abide by [code-of-conduct.md](code-of-conduct.md). Report unacceptable behaviour via GitHub.

## Contributing

Issues and pull requests are welcome. Please read [contributing.md](contributing.md) before opening a PR — it covers branch naming, commit conventions, testing, and the documentation expectations for every change.
