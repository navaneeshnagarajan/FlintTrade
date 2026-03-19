# Tools, Dependencies & External Repos — Usage Guide

> Every tool, library, and external repo FlintTrade uses or plans to use.
> For each one: what it is, which FlintTrade package uses it, and HOW.

---

## Core Development Tools

### OpenAlgo (v2.0+)
- **What:** Open-source algo trading platform — broker connections, order execution, market data
- **Used by:** ALL packages (via packages/core OpenAlgo client)
- **How:** FlintTrade communicates ONLY through OpenAlgo's REST API and WebSocket. Never modify OpenAlgo.
- **Repo:** github.com/marketcalls/openalgo
- **Docs:** docs.openalgo.in
- **Install:** separate install — see docs.openalgo.in/installation-guidelines

### OpenAlgo Python SDK
- **What:** Official Python client for OpenAlgo API + 80+ technical indicators
- **Used by:** packages/core (API client patterns), packages/engine (indicator library)
- **How:** Reference for building our openalgo_client.py. Import indicators: `from openalgo import ta`
- **Repo:** github.com/marketcalls/openalgo-python-library
- **Install:** `pip install openalgo`

### Claude Code
- **What:** Anthropic's CLI coding agent — reads CLAUDE.md for context
- **Used by:** ALL packages (primary development tool on every machine)
- **How:** Each package has a CLAUDE.md that Claude Code reads. Sequential, focused work.
- **Install:** `npm install -g @anthropic-ai/claude-code`

### Antigravity
- **What:** Multi-agent IDE — reads AGENTS.md for context, runs 3-4 agents in parallel
- **Used by:** ALL packages (parallel development on Nitro and Mac)
- **How:** Each package has an AGENTS.md (identical to CLAUDE.md). Multiple agents work on different packages simultaneously.
- **Install:** Antigravity Manager View (GUI application)
- **Note:** Latest release reads AGENTS.md in addition to GEMINI.md

### VS Code
- **What:** Code editor — used with Claude Code extension
- **Used by:** ALL packages
- **How:** Primary editor. Claude Code runs inside VS Code terminal.

---

## AI & ML Tools

### LM Studio
- **What:** Local LLM inference server with GUI — runs GGUF/MLX models
- **Used by:** packages/ai (primary LLM provider), packages/automation (OpenClaw backend)
- **How:** Runs as server on port 1234. FlintTrade connects via OpenAI-compatible API.
- **Install:** lmstudio.ai (GUI installer for all platforms)
- **Config:** Load model → Start Server → API at http://localhost:1234/v1/chat/completions
- **Models:** Qwen 3.5 9B (Q4_K_M), Llama 3.1 8B, or any GGUF model
- **Note:** Use LM Link to share models across machines (E2E encrypted)

### OpenClaw
- **What:** AI agent gateway — Telegram, WhatsApp, Discord integration, heartbeats, cron, skills
- **Used by:** packages/automation (Telegram bot, AI agent bridge)
- **How:** Runs as systemd service. Connects to LM Studio for inference. Provides Telegram/WhatsApp interface to AI.
- **Repo:** openclaw docs
- **Install:** Node 22+ required. `npm install -g openclaw` or systemd service
- **Config:** ~/.openclaw/openclaw.json — set model, context length, auth token
- **Note:** Uses openai-completions API (NOT anthropic-messages) due to Qwen jinja template compatibility

### ChromaDB
- **What:** Vector database for RAG (Retrieval Augmented Generation)
- **Used by:** packages/ai (trade knowledge base, strategy performance memory)
- **How:** Store trade outcomes, strategy results, market regime data. Query during AI chat for context.
- **Install:** `pip install chromadb`
- **Planned:** Week 10-12 of roadmap

### LightGBM
- **What:** Gradient boosting framework — fast, efficient ML for tabular data
- **Used by:** packages/ai (signal generation), packages/backtest-engine (feature importance)
- **How:** Train on rolling 6-month windows of market data. Features: OI, volume, Greeks, technical indicators. Output: probability scores for trade signals.
- **Install:** `pip install lightgbm`
- **Planned:** Week 10-12 of roadmap

### Ollama
- **What:** Local LLM runner (alternative to LM Studio)
- **Used by:** packages/ai (optional fallback)
- **How:** Backup if LM Studio unavailable. Same OpenAI-compatible API.
- **Install:** ollama.ai
- **Note:** LM Studio is preferred (GUI, LM Link, better model management)

---

## Data & Storage Tools

### DuckDB
- **What:** In-process analytical database — SQL on Parquet/CSV files, columnar storage
- **Used by:** packages/historical (OHLCV storage), packages/data (tick analytics), packages/backtest-engine (data replay)
- **How:** Main analytical database. Store historical OHLCV, OI, Greeks. Query with SQL. Export to Parquet for archival.
- **Install:** `pip install duckdb`
- **Reference:** OpenAlgo's Historify uses DuckDB for the same purpose

### Parquet (Apache Arrow)
- **What:** Columnar file format — efficient storage for time-series data
- **Used by:** packages/historical (archival), packages/data (tick archival)
- **How:** DuckDB reads/writes Parquet natively. Store on /data partition (5TB HDD on production).
- **Install:** included with DuckDB, or `pip install pyarrow`

### SQLite
- **What:** File-based relational database — used for state/config (NOT analytics)
- **Used by:** packages/core (session state), packages/engine (strategy state)
- **How:** Small state tracking. OpenAlgo uses SQLite internally. Don't use for large datasets — use DuckDB instead.
- **Install:** built into Python stdlib

---

## Frontend Libraries

### Dockview + dockview-react
- **What:** Docking layout framework — drag, dock, split, float panels
- **Used by:** packages/terminal (widget-composable workspace)
- **How:** Users build their own layouts by dragging and docking widgets. Replaces fixed layout.
- **Install:** `npm install dockview dockview-react`

### shadcn/ui + Radix UI
- **What:** Accessible, themeable component library built on Radix primitives
- **Used by:** packages/terminal (all UI components)
- **How:** Copy components via CLI (`npx shadcn-ui@latest add button`). Customized with Tailwind.
- **Install:** `npm install class-variance-authority clsx tailwind-merge @radix-ui/react-slot @radix-ui/react-dialog @radix-ui/react-dropdown-menu @radix-ui/react-select @radix-ui/react-tabs @radix-ui/react-tooltip @radix-ui/react-popover @radix-ui/react-switch`

### Zustand
- **What:** Lightweight global state management
- **Used by:** packages/terminal (global UI state — theme, layout, connection, settings)
- **How:** Create stores with `create()`. No boilerplate, no providers.
- **Install:** `npm install zustand`

### Jotai
- **What:** Atomic state management for fine-grained reactivity
- **Used by:** packages/terminal (per-widget state, symbol atoms)
- **How:** Define atoms for each widget instance. Derived atoms for computed values.
- **Install:** `npm install jotai`

### TanStack React Query
- **What:** Server state management — data fetching, caching, background refresh
- **Used by:** packages/terminal (all API calls to OpenAlgo)
- **How:** `useQuery` for reads, `useMutation` for writes. Auto-refetch, stale-while-revalidate.
- **Install:** `npm install @tanstack/react-query`

### TanStack React Table
- **What:** Headless table library — sorting, filtering, pagination, virtualization
- **Used by:** packages/terminal (order book, trade book, positions table)
- **How:** Define column defs, use `useReactTable` hook. Renders via Tailwind.
- **Install:** `npm install @tanstack/react-table`

### Glide Data Grid
- **What:** High-performance virtualized grid for large datasets
- **Used by:** packages/terminal (option chain, order book with 50-level depth)
- **How:** Renders only visible cells. Handles 100k+ rows at 60fps.
- **Install:** `npm install @glideapps/glide-data-grid`

### react-hook-form + zod
- **What:** Form management with schema validation
- **Used by:** packages/terminal (order forms, settings, strategy config)
- **How:** `useForm` hook with zod resolver for type-safe validation.
- **Install:** `npm install react-hook-form zod @hookform/resolvers`

### react-router-dom
- **What:** Client-side routing for React SPAs
- **Used by:** packages/terminal (module navigation)
- **How:** Route-based code splitting for terminal modules.
- **Install:** `npm install react-router-dom`

### date-fns
- **What:** Lightweight date utility library
- **Used by:** packages/terminal (trade timestamps, market hours, expiry formatting)
- **How:** Pure functions, tree-shakeable. `format()`, `differenceInMinutes()`, etc.
- **Install:** `npm install date-fns`

### TradingView Lightweight Charts (v5)
- **What:** Professional financial charting library — candlesticks, volume, indicators
- **Used by:** packages/terminal (scalper charts, option charts)
- **How:** React integration. Multi-pane synchronized charts (CE/Spot/PE). Multi-timeframe.
- **Install:** `npm install lightweight-charts`
- **Reference:** OpenAlgo's PineTS uses this library

### Tailwind CSS (v4)
- **What:** Utility-first CSS framework with `@tailwindcss/vite` plugin
- **Used by:** packages/terminal
- **How:** Use utility classes directly in JSX. Dark mode via class strategy.
- **Install:** `npm install tailwindcss @tailwindcss/vite`

### Lucide React
- **What:** Icon library (fork of Feather Icons)
- **Used by:** packages/terminal
- **How:** `import { TrendingUp, Settings } from 'lucide-react'`
- **Install:** `npm install lucide-react`

---

## Infrastructure Tools

### nginx
- **What:** Reverse proxy and load balancer
- **Used by:** infra/ (blue-green deployment)
- **How:** Routes traffic between blue/green OpenAlgo instances. Sub-second swap via `nginx -s reload`.
- **Config:** infra/nginx/openalgo-blue-green.conf
- **Install:** `sudo apt install nginx`

### systemd
- **What:** Linux service manager
- **Used by:** infra/ (OpenAlgo services, cron)
- **How:** Blue/green OpenAlgo instances run as systemd services. Auto-start on boot.
- **Config:** infra/systemd/openalgo-blue.service, openalgo-green.service

### WireGuard
- **What:** VPN for secure remote access
- **Used by:** infra/ (optional — for accessing production server remotely)
- **How:** Mesh VPN connecting dev machines to production server.
- **Install:** built into Linux kernel, apps for Mac/Windows
- **Note:** Optional for FlintTrade. Required only if accessing OpenAlgo remotely.

### fail2ban
- **What:** Intrusion prevention — blocks repeated failed login attempts
- **Used by:** production server security
- **How:** Monitors SSH, nginx, OpenAlgo login attempts. Auto-bans IPs after repeated failures.
- **Install:** `sudo apt install fail2ban`

### UFW (Uncomplicated Firewall)
- **What:** Linux firewall
- **Used by:** production server security
- **How:** Allow only necessary ports (5000, 8765, 22, 51820). Block everything else.
- **Install:** `sudo apt install ufw`

### Cockpit
- **What:** Web-based server management dashboard
- **Used by:** production server monitoring (port 9090)
- **How:** Monitor CPU, RAM, disk, services via browser. Optional.
- **Install:** `sudo apt install cockpit`

### Docker
- **What:** Container runtime
- **Used by:** Optional — for containerized deployment of FlintTrade
- **How:** Future: Dockerfile for each package, docker-compose for full stack.
- **Install:** docs.docker.com/engine/install

---

## External Repos — AI/ML Research

| Repo | What | FlintTrade Package | When |
|---|---|---|---|
| **FinRL** (AI4Finance) | RL-based trading agents, gymnasium environments | ai | Week 10-12 |
| **FinMem** (pipiku915) | LLM with layered memory for trading decisions | ai | Week 12 |
| **TradingAgents** (TauricResearch) | Multi-agent trading with specialized roles | ai | Week 7 |
| **agency-agents** | Agent orchestration patterns | automation | Week 3 |
| **autoresearch** | Automated research pipeline | ai | Week 19 |
| **autoresearch-mlx** | MLX-optimized version (for Mac M-series) | ai | Week 19 (Mac) |
| **unsloth** | QLoRA fine-tuning (4x faster, 60% less VRAM) | ai | Week 19 |
| **optionlab** | Options strategy analysis + visualization | backtest-engine | Week 2 |
| **awesome-systematic-trading** | Curated list of quant trading resources | reference | — |
| **awesome-quant** | Curated list of quant tools and libraries | reference | — |
| **LLM-TradeBot** (EthanAlgoX) | Multi-agent LLM trading with dashboard | ai | Week 12 |
| **PrimoGPT** (ivebotunac) | LLM + RL + Unsloth QLoRA trading | ai | Week 12 |
| **FinRL_Contest_2025** (Open-Finance-Lab) | FinRL competition reference | ai | reference |

## External Repos — AI Trading Research (study, adapt patterns)

| Repo | What | FlintTrade Package |
|---|---|---|
| **Stockagent** (MingyuJ666) | LLM multi-agent stock trading simulation | ai (reference) |
| **llm-rl-finance-trader** (franjgs) | LLM sentiment + RL portfolio optimization | ai (reference) |
| **Trading-Agent** (MiChaelinzo) | Deep Q-Learning trading agent | ai (reference) |
| **FinRL-Trading** (AI4Finance) | FinRL trading module | ai (reference) |
| **Autonomous-Agents** (tmgthb) | Curated list of autonomous agent architectures | ai (reference) |

## External Repos — Indian F&O Strategy References (study, don't clone)

| Repo | What | FlintTrade Package |
|---|---|---|
| **algo_trading_strategies_india** (buzzsubash) | NSE option selling strategies | engine (reference) |
| **Banknifty-Straddle** (umeshpalai) | Straddle backtest reference | backtest-engine (reference) |
| **NSE-Option-Chain-Analyzer** (VarunS2002) | OI analysis tool | screener (reference) |
| **openalgo-backtrader** (p2c2e) | Backtrader integration | backtest-engine (reference) |
| **fully-automated-nifty-options-trading** (srikar-kodakandla) | Selenium-based auto-trading | engine (reference) |

## Pip Install Libraries

| Package | Repo | Used By | Status |
|---|---|---|---|
| openalgo | marketcalls/openalgo-python-library | core, engine | `pip install openalgo` |
| vectorbt | polakowo/vectorbt | backtest-engine | `pip install vectorbt` |
| jugaad-data | jugaad-py/jugaad-data | data, historical | `pip install jugaad-data` |
| lightweight-charts | tradingview/lightweight-charts | terminal | `npm install lightweight-charts` |
| lightgbm | microsoft/LightGBM | ai | `pip install lightgbm` |
| chromadb | chroma-core/chroma | ai | `pip install chromadb` |
| duckdb | duckdb/duckdb | historical, data | `pip install duckdb` |
| pyotp | pyauth/pyotp | automation (optional) | `pip install pyotp` |

## External Repos — OpenAlgo Ecosystem

| Repo | What | FlintTrade Package |
|---|---|---|
| **marketcalls/openalgo** | Core trading API (30+ brokers) | core |
| **marketcalls/openalgo-python-library** | Python SDK (80+ indicators) | core, engine |
| **marketcalls/historify** | DuckDB historical data management | historical |
| **marketcalls/algomirror** | Multi-account orchestration | ditto |
| **marketcalls/openalgo-mcp** | MCP/AI agent pattern | ai |
| **marketcalls/fastscalper-tauri** | Scalper UI (Rust+Tauri) | terminal (reference) |
| **marketcalls/openalgo-flow** | Visual workflow (N8N-style) | integration (reference) |
| **marketcalls/openalgo-pinets** | TradingView charts + PineTS indicators | terminal (reference) |
| **marketcalls/openalgo-node** | Node.js SDK | core (reference) |
| **marketcalls/openalgo-chart** | Chart integration | terminal (reference) |
| **marketcalls/openalgo-mobile** | Mobile UI (Flutter) | terminal (reference) |
| **marketcalls/openalgo-chrome** | Chrome extension | integration (future) |
| **marketcalls/OpenAlgo-Excel** | Excel add-in | integration (future) |
| **marketcalls/OpenAlgoPlugin** | Amibroker plugin | integration (future) |
| **marketcalls/openalgo-desktop** | Desktop app (Tauri 2.0) | future |
| **marketcalls/openchart** | Charting library | terminal (reference) |
| **marketcalls/openquest** | QuestDB tick aggregation | data (reference) |
| **marketcalls/openalgo-rust** | Rust SDK | core (reference) |
| **marketcalls/openalgo-portfoliogreeks** | Portfolio Greeks calculator | screener (reference) |
| **marketcalls/openengine** | Event-driven backtest engine | backtest-engine (reference) |
| **marketcalls/openalgo-docs** | GitBook documentation | docs (reference) |
| **marketcalls/openalgo-webpage** | Next.js website | — (reference) |

## External Repos — Dev Tools

| Tool | What | How FlintTrade Uses It |
|---|---|---|
| **CLI-Anything** | CLI framework for rapid tool building | Build the `flint` CLI tool in packages/core |
| **GitNexus** | Codebase intelligence — understand large repos | Dev tool on Ubuntu for navigating OpenAlgo source |
| **Cowork** (Anthropic) | Claude Desktop agent for non-code tasks | File management, documentation tasks on Mac |

## Broker SDKs (accessed through OpenAlgo, NOT directly)

| Broker | SDK/API | Notes |
|---|---|---|
| Dhan | DhanHQ API v2 | Primary sandbox + live. 5yr expired options data. |
| Kotak Neo | Kotak Neo SDK | Zero-brokerage execution (planned). |
| Upstox | Upstox API v3 | Backup. Contract-level expired options. |
| Zerodha | Kite Connect | Most popular. ₹500/month subscription. |
| Angel One | SmartAPI | Free APIs. Good WebSocket. |
| Fyers | Fyers API v3 | 50-level depth. 25yr daily data. |
| All others | Via OpenAlgo | 30+ brokers supported — see docs.openalgo.in |

**Critical:** FlintTrade NEVER calls broker APIs directly. All broker communication goes through OpenAlgo's unified API. Broker SDKs are listed here for reference only.

## Newly Discovered marketcalls Repos (not in Mini FOSS Universe)

| Repo | What | FlintTrade Package |
|---|---|---|
| **openengine** | Event-driven backtesting engine for Indian markets + live trading via OpenAlgo API | backtest-engine |
| **openadvisor** | ML stock recommendations using CatBoost, Flask, portfolio management (FossHack 2024) | ai |
| **OpenTerminal** | Open-source trading terminal for Indian traders (HTML/JS) | terminal (reference) |
| **finnews-ai** | Financial news AI (HTML) | ai |
| **fyers-websockets** | 50-level DOM analyzer with Fyers TBT tick-by-tick data, order flow analytics | terminal, data |
| **vectorbt-backtesting-skills** | 12 strategy templates, agentic coding skills for 40+ AI agents, TA-Lib, QuantStats | backtest-engine |
| **openchart** | Free NSE/NFO historical data library (pip install openchart, no broker API needed) | historical |
| **stock-market-dashboard** | React + Flask market dashboard with Yahoo Finance data | terminal (reference) |
| **trading-dashboard** | Simple React trading dashboard | terminal (reference) |
| **tradingview-yahoo-finance** | TradingView Lightweight Charts with Yahoo Finance data | terminal (reference) |
| **openalgo-portfoliogreeks** | Portfolio-level Black-Scholes Greeks calculator | screener |
| **openquest** | Real-time tick aggregation into QuestDB with TradingView streaming charts | data |

## Community Projects (not by marketcalls)

| Repo | Author | What | FlintTrade Package |
|---|---|---|---|
| **openalgo-backtrader** | p2c2e | Backtrader integration for OpenAlgo | backtest-engine |
| **openalgo-helm** | p2c2e | Kubernetes Helm chart for OpenAlgo | infra (future) |
| **openalgo-chart** | crypt0inf0 | Chart component for OpenAlgo | terminal (reference) |

## Additional Pip Libraries (discovered in GitHub audit)

| Library | Install | What | FlintTrade Package |
|---|---|---|---|
| **py_vollib_vectorized** | `pip install py_vollib_vectorized` | Fastest vectorized options pricing + Greeks (Black-Scholes, Black-76) with numba | screener, backtest-engine |
| **quantstats** | `pip install quantstats` | Portfolio analytics, tearsheets, monthly returns heatmaps, Sharpe/Sortino | backtest-engine, dashboard |
| **ta-lib** | `pip install TA-Lib` (needs C library: `brew install ta-lib` / `sudo apt install libta-lib-dev`) | 150+ technical indicators, candlestick patterns | engine, backtest-engine |
| **mibian** | `pip install mibian` | Simple Black-Scholes and Black-76 options pricing | screener |

## Additional Reference Repos (patterns to absorb)

| Repo | Stars | What | FlintTrade Package |
|---|---|---|---|
| **NSE-Option-Chain-Analyzer** (VarunS2002) | 500+ | Best OI trend analysis — PCR, writer detection, support/resistance from OI | screener |
| **Steadfast 1-click trading** | — | Multi-broker quick options trading (BankNifty, Nifty, Finnifty, Sensex) | terminal (reference) |
| **Open-Interest-NSE-Live-Analysis** | — | Live OI analysis toolkit with multi-strike visualization | screener |
| **py_vollib** (vollib) | 370+ | Core options pricing library (Black, BS, BSM) with analytical + numerical Greeks | screener, backtest-engine |
| **MiroFish** (666ghj) | 10k+ | Swarm intelligence prediction engine — multi-agent simulation, GraphRAG knowledge graphs, agent memory (Zep), prediction reports. Use for market scenario simulation and crowd behavior modeling. | ai (reference) |

## Crypto / Commodity / Currency Reference Repos

| Repo | Stars | What | FlintTrade Package | How |
|---|---|---|---|---|
| **ccxt** | 34k+ | Unified API for 100+ crypto exchanges. Delta Exchange supported. | core (reference) | OpenAlgo handles Delta Exchange directly. CCXT is reference for API patterns only. |
| **freqtrade** | 39k+ | Open-source crypto trading bot with FreqAI ML module. | ai, backtest-engine (reference) | Strategy architecture patterns, FreqAI adaptive ML approach. |
| **passivbot** | 4k+ | Crypto market-making bot (Python + Rust). Grid/DCA strategies. | engine (reference) | Grid strategy patterns for crypto perpetuals. |
| **intelligent-trading-bot** | 1.4k+ | ML feature engineering + signal generation for crypto. | ai (reference) | Feature engineering pipeline, online/offline separation pattern. |
| **vectorbt-backtesting-skills** | — | Already absorbed. Supports crypto markets via CCXT + yfinance. | backtest-engine | Already in our absorbed repos. |

## Pip Libraries for Crypto/Commodity/Currency

| Library | Install | What | Package |
|---|---|---|---|
| **ccxt** | `pip install ccxt` | Unified crypto exchange API (use for Delta Exchange data if needed) | data, historical |
| **yfinance** | `pip install yfinance` | Free MCX commodity data (GOLD, SILVER, CRUDE via Yahoo Finance) | historical |
| **jugaad-data** | `pip install jugaad-data` | NSE/BSE holidays, free Indian market data | historical, automation |
| **nsepython** | `pip install nsepython` | NSE option chain, FII/DII data, PCR | screener |

## Additional pip libraries (from transcript review)

| Library | Install | What | Package |
|---|---|---|---|
| **pyotp** | `pip install pyotp` | TOTP code generation (optional, broker login handled by OpenAlgo) | automation |
| **jugaad-data** | `pip install jugaad-data` | NSE/BSE holidays, free Indian market data | automation, historical |
| **nsepython** | `pip install nsepython` | NSE option chain, FII/DII data, PCR, advance/decline (free, no broker API) | screener |
