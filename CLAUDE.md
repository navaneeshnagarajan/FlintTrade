# FlintTrade — Master Context

> Open-source algo and manual trading platform. One clone = the whole house.
> Repo: github.com/navaneeshnagarajan/FlintTrade | License: AGPL-3.0 | Version: 0.6.0-dev

## What is FlintTrade?

FlintTrade is a self-hosted, multi-market trading platform that bundles OpenAlgo + infrastructure + application into ONE repo. `git clone` → `make setup` → `make start` → live trading. No external subscriptions. Replaces Sensibull, Tradetron, TradingView paid.

**OpenAlgo runs as a managed subprocess** (git subtree in `infra/openalgo/`). FlintTrade manages its lifecycle — start, stop, update, health check. Users never touch OpenAlgo directly.

## Supported Markets (via OpenAlgo)

| Exchange | Code | What | Trading Hours (IST) |
|---|---|---|---|
| NSE | NSE | Equities | 9:15-3:30 |
| BSE | BSE | Equities | 9:15-3:30 |
| NFO | NFO | NSE F\&O (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, stock options) | 9:15-3:30 |
| BFO | BFO | BSE F\&O (SENSEX, BANKEX, SENSEX50) | 9:15-3:30 |
| CDS | CDS | NSE Currency Derivatives (USDINR, EURINR, GBPINR, JPYINR) | 9:00-5:00 PM |
| BCD | BCD | BSE Currency Derivatives | 9:00-5:00 PM |
| MCX | MCX | Commodities (GOLD, SILVER, CRUDEOIL, NATURALGAS, COPPER, ZINC) | 9:00-11:55 PM |
| NCDEX | NCDEX | Agri Commodities | 10:00-5:00 PM |
| DELTA | DELTA | Crypto Derivatives — BTC/ETH/XRP futures, perpetuals, options. INR settlement. FIU-India compliant. Native OpenAlgo broker. | 24/7 |
| NSE_INDEX | NSE_INDEX | Index values (NIFTY, BANKNIFTY, VIX, sector indices) | 9:15-3:30 |
| BSE_INDEX | BSE_INDEX | Index values (SENSEX, BANKEX, sector indices) | 9:15-3:30 |

**Deploy freeze depends on what you trade:**
- Equity/F\&O only: 9:15 AM - 3:30 PM
- Currency: 9:00 AM - 5:00 PM
- MCX Commodities: 9:00 AM - 11:55 PM (almost 24/7 on some days)
- Crypto (Delta Exchange): 24/7 — deploy requires position check before restart

## Monorepo Structure

```
FlintTrade/
├── packages/
│   ├── core/            → OpenAlgo API client, config, models, logger (absorbs openalgo-python-library SDK)
│   ├── engine/          → Strategy execution, safety layers, order routing (absorbs openengine patterns)
│   ├── terminal/        → Scalper, option chain, DOM, charts (absorbs fastscalper + OpenTerminal + pinets + fyers-websockets patterns)
│   ├── dashboard/       → P&L, portfolio, market overview (absorbs stock-market-dashboard + trading-dashboard + openalgo-mobile patterns)
│   ├── ai/              → LLM chat, RAG, ML signals, news sentiment (absorbs openalgo-mcp + openadvisor + finnews-ai patterns)
│   ├── data/            → Tick capture, audit logs (absorbs openquest QuestDB patterns)
│   ├── historical/      → Historical download, DuckDB/Parquet (absorbs historify + openchart)
│   ├── screener/        → OI spurt, PCR, max pain, portfolio Greeks (absorbs openalgo-portfoliogreeks)
│   ├── backtest/        → Backtest UI
│   ├── backtest-engine/ → Simulation engine (absorbs openengine + vectorbt-backtesting-skills)
│   ├── integration/     → TradingView, ChartInk, webhooks (absorbs openalgo-flow + chrome + excel + amibroker)
│   ├── automation/      → ML pipeline, cron, Telegram, OpenClaw, TOTP auto-login
│   └── ditto/           → Multi-broker, multi-account (absorbs algomirror)
├── infra/
│   ├── openalgo/        → git subtree (managed service, port 5000)
│   ├── openclaw/        → git subtree (AI agent, port 18789)
│   ├── nginx/           → blue-green reverse proxy
│   ├── systemd/         → service files
│   ├── scripts/         → deploy, rollback, backup, health, setup
│   ├── wireguard/       → VPN configs
│   ├── security/        → fail2ban, UFW
│   └── cron/            → TOTP login, health check, backup, DDNS
├── bugs/                → git-native bug tracking
├── docs/                → architecture, operations, SEBI, machine configs, references
├── tests/               → shared test infrastructure
└── .github/             → CI, PR templates, issue templates
```

## Absorbed Repos Map

"Absorb" = rewrite the logic into our architecture using the original as reference. NOT copy-paste.

| marketcalls repo | Absorbed into | What we take |
|---|---|---|
| openalgo | infra/openalgo/ (subtree) | Runs as managed service |
| openalgo-python-library | packages/core/ | SDK patterns, 80+ indicators |
| openengine | packages/backtest-engine/ | Event-driven backtest architecture |
| algomirror | packages/ditto/ | Multi-account routing, margin calc, trailing SL |
| historify | packages/historical/ | DuckDB pipeline, data management |
| openchart | packages/historical/ | Free NSE data (no broker API needed) |
| openquest | packages/data/ | QuestDB tick aggregation patterns |
| fastscalper-tauri | packages/terminal/ | Scalper UI patterns |
| OpenTerminal | packages/terminal/ | Trading terminal patterns |
| openalgo-pinets | packages/terminal/ | PineTS indicators, TradingView chart integration |
| fyers-websockets | packages/terminal/ | 50-level DOM, order flow analytics |
| tradingview-yahoo-finance | packages/terminal/ | TradingView chart integration patterns |
| openalgo-portfoliogreeks | packages/screener/ | Portfolio Greeks calculator |
| openalgo-mcp | packages/ai/ | MCP natural language trading patterns |
| openadvisor | packages/ai/ | CatBoost ML recommendations |
| finnews-ai | packages/ai/ | Financial news sentiment |
| openalgo-flow | packages/integration/ | Visual strategy builder |
| openalgo-chrome | packages/integration/ | Chrome extension trading |
| OpenAlgo-Excel | packages/integration/ | Excel add-in |
| OpenAlgoPlugin | packages/integration/ | Amibroker plugin |
| vectorbt-backtesting-skills | packages/backtest-engine/ | 12 strategy templates, agent skills |
| stock-market-dashboard | packages/dashboard/ | React dashboard patterns |
| trading-dashboard | packages/dashboard/ | React dashboard patterns |
| openalgo-mobile | packages/dashboard/ | Flutter UI → React responsive patterns |
| openalgo-desktop | future | Tauri 2.0 wrapper (after web is done) |
| openalgo-node | reference | Node.js SDK patterns |
| openalgo-java/rust/go/.NET | reference | SDK patterns in other languages |
| openalgo-webpage | reference | Marketing site |
| openalgo-docs | reference | Documentation (already in project knowledge) |
| openalgo-helm | infra/ (future) | Kubernetes deployment |
| openalgo-backtrader (p2c2e) | packages/backtest-engine/ | Backtrader integration |
| openalgo-chart (crypt0inf0) | packages/terminal/ | Chart component patterns |

## Git Branching

```
main ────────────────→ Production (PR from dev only, CI must pass, squash merge)
  └─ dev ────────────→ Integration (PR from feature/fix only, requires 1 approval)
       ├─ feature/*  → New features (anyone creates, PRs to dev, auto-deleted)
       ├─ fix/*      → Bug fixes (PRs to dev, auto-deleted)
       ├─ hotfix/*   → Emergency (PRs to main + backport to dev)
       └─ release/*  → Version prep (PRs to main)
```

Branch names MUST include package: `feature/terminal-scalper`, `fix/engine-routing`
Commits: `feat(terminal): add scalper panel` — conventional commits always
Always squash and merge. Every time.

## DEVLOG

Every change → append to DEVLOG.md:
```
## YYYY-MM-DD HH:MM IST | Machine | @username | IDE/Tool | AI Model/Agent | Branch | Summary
```

## Deploy Freeze

- NSE/BSE/NFO/BFO traders: 9:15 AM – 3:30 PM IST — NO deploys
- CDS/BCD traders: 9:00 AM – 5:00 PM IST — NO deploys
- MCX traders: 9:00 AM – 11:55 PM IST — NO deploys
- DELTA/crypto: check open positions before any restart (24/7 market)
- If a bug is found during market hours → use OpenAlgo Action Center
  to disable the strategy. Fix and deploy after your market closes.

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, Flask |
| Frontend | React 19, Vite, Tailwind CSS, TradingView Lightweight Charts v5 |
| Real-time | WebSocket, ZMQ |
| Database | DuckDB (analytics), SQLite (state), Parquet (archival) |
| AI/ML | LM Studio, ChromaDB, LightGBM, CatBoost |
| AI Agent | OpenClaw (gateway), Ollama (fallback) |
| Testing | pytest (Python), Vitest (React), ruff (linting) |
| CI/CD | GitHub Actions |
| Deploy | nginx, systemd, bash scripts |
| VPN | WireGuard |
| Security | fail2ban, UFW |

## OpenAlgo v2.0.0.1 Features (absorbed into FlintTrade packages)

- Option Chain + Greeks + GEX + IV Smile + OI Profile + Max Pain → screener
- 3D Volatility Surface + ATM Straddle Chart + OI Tracker → screener
- System Health Monitor API → dashboard
- 50-level WebSocket depth → terminal + data
- Historify scheduler + symbol validation → historical
- Flow Editor: Order Status node, SmartOrder negative positions → integration
- Basket order batched concurrent execution → engine
- Delta Exchange native broker integration → core (DELTA exchange)
- Nubra broker integration → core (broker list)
- WebSocket file descriptor leak fixes (all brokers) → data tick_recorder

**Supported brokers (24 via OpenAlgo v2.0.0.1):** Dhan, Zerodha, Angel One, Fyers, IIFL, 5paisa, Kotak Neo, Upstox, Aliceblue, Firstock, Flattrade, Finvasia/Shoonya, Mastertrust, ICICI Direct, Motilal Oswal, Paytm Money, Tradejini, Zebu, Rupeezy, Compositedge, Delta Exchange, Nubra, and more. FlintTrade code never references specific brokers — OpenAlgo abstracts them.

## What NOT to Do

- Commit .env, API keys, TOTP secrets, credentials
- Modify infra/openalgo/ source (use subtree pull for updates)
- Push directly to main or dev
- Reference specific brokers in package code
- Restart OpenAlgo during market hours with open positions
- Skip DEVLOG entries
