# Unexamined Repos Scan

> **Generated:** 2026-03-31 by Claude Code (Opus 4.6)
> **Scope:** ~120 repos not referenced in `REPO_FEATURE_MAP.md` out of 222 total
> **Method:** README scan, directory structure analysis, source code sampling

---

## HIGH Priority (absorb now)

| Repo | Location | What | Target Package | Complexity |
|------|----------|------|----------------|------------|
| **raptorbt** | marketcalls-all | Rust/PyO3 backtesting engine. 5800x faster than vectorbt. Has `run_single_backtest`, `run_basket_backtest`, `run_options_backtest`, `run_pairs_backtest`, `run_spread_backtest`, Monte Carlo simulation, and 10 built-in indicators (SMA, EMA, RSI, MACD, Stochastic, ATR, Bollinger, ADX, VWAP, Supertrend). Same author as OpenAlgo. | `tick-engine` + `backtest-engine` | HIGH — Rust codebase, but architecture patterns are directly applicable to our tick-engine PyO3 package |
| **Agentic-Trader** | marketcalls-all | Single-agent autonomous trading system. OpenAI Agents SDK + LiteLLM. 7 TA-Lib indicators, parallel data fetching, strict risk management (stop-loss, position limits, no pyramiding), market hours protection. Uses OpenAlgo API. | `ai` + `engine` | MEDIUM — Single Python file (`agent.py`), clean architecture doc |
| **fluxscan** | marketcalls-all | Full scanner engine. Custom Python-based scanners with TA-Lib, watchlist management, scheduled scans, built-in templates (MACD, RSI, BB), WebSocket progress, export CSV/JSON. Uses OpenAlgo SDK. | `screener` + terminal Scanner widget | MEDIUM — Flask app with models for scanner, schedule, watchlist, scan_result |
| **AlgoTrade** | marketcalls-all | Strategy platform using OpenAlgo REST APIs. Strategy CRUD, instance deployment, signal generation (LE/LX/SE/SX), WebSocket helper, background tasks, symbol mapping. Full Flask+SQLAlchemy app. | `engine` (strategy registry) | MEDIUM — Complete strategy lifecycle management |
| **ExpiryTrack** | marketcalls-all | Expired F&O contract historical data collector. 3-month data before expiry, async task management, data export (CSV/JSON/ZIP), encrypted credential storage. Upstox-based but patterns are universal. | `historical` (expiry data pipeline) | MEDIUM — Clean src/ structure with collectors, exporters, database managers |
| **FinSights** | marketcalls-all | News summary platform for Indian market. FastAPI + Perplexity AI. Pre/post-market summaries, sector coverage, stock-specific search, scheduled fetching, cache-first architecture. | `ai` (news/sentiment) + terminal News widget | LOW — FastAPI (we use Flask), but the news fetching + AI summary pipeline is directly useful |
| **openalgo-execution-system** | community-openalgo | Execution system with FastAPI backend + Next.js frontend. Has executor (with retry logic), monitor, reconciliation engine. Trade state machine (ENTRY_PENDING -> ACTIVE -> EXIT_PENDING -> CLOSED). | `engine` (execution patterns) | LOW — Mostly scaffolding, but reconciliation pattern is useful |
| **opencase** | marketcalls-all | Stock basket platform. TypeScript + Hono. Multi-broker support (Zerodha, AngelOne). Routes for baskets, portfolio, investments, alerts, instruments. | terminal Invest route (basket investing) | MEDIUM — TypeScript, relevant basket/portfolio patterns |
| **pandas_signals_library** | marketcalls-all | Signal processing for trading: `exrem` (remove excessive signals), `flip` (state machine), `valuewhen` (conditional lookback). AmiBroker-style signal handling in pandas. | `indicators` | LOW — 3 functions, but very useful for strategy signal processing |

---

## MEDIUM Priority (absorb later)

| Repo | Location | What | Target Package | Notes |
|------|----------|------|----------------|-------|
| **TradingView-Screener** | marketcalls-all | Python library to create custom TradingView screeners using official API. Query builder, column definitions, models. No web scraping needed. | `screener` | Clean API wrapper. Could power a TradingView screener widget. |
| **OpenTerminal** | tier1-core | Flask trading dashboard with AngelOne. Watchlist management (5 watchlists), market data streaming, order management, portfolio overview, symbol search. | terminal (reference) | Flask+Jinja2 but has solid watchlist service patterns. |
| **Crypto-Realtime-QuestDB** | marketcalls-all | Real-time crypto analytics with QuestDB + FastAPI. WebSocket ingestion, dashboard, 8 trading pairs. | `data` (QuestDB patterns) | QuestDB integration patterns for our planned QuestDB tick storage. |
| **LLM-TradeBot** | external-all | Multi-agent adversarial trading bot. Market regime detection, price position awareness, dynamic score calibration, multi-layer physical auditing. Backtesting included. | `ai` (agent architecture) | Sophisticated adversarial decision framework. REFERENCE ONLY for AI package. |
| **algosattva** | community-openalgo | OpenAlgo fork with bracket order implementation. Full AGPL codebase with bracket order architecture docs. | `engine` (bracket orders) | 12 bracket order docs. If bracket orders land in upstream OpenAlgo, this is the reference. |
| **order-flow-chart** | tier2-ecosystem | Order flow visualization with D3.js + Flask. Real-time SSE, buy/sell volume at price levels, time bucketing, tick size aggregation. | terminal OrderFlow widget | Simple but functional. Angel One WebSocket specific. |
| **scanner** (EMA Crossover) | marketcalls-all | Streamlit EMA crossover dashboard. SQLite data store, candlestick charts with EMA, multi-timeframe scanning (1m/5m/10m/15m). | `screener` (crossover detection) | Small but focused. Useful crossover detection patterns. |
| **screener-scraper** | marketcalls-all | Screener.in scraper. Parses financial statements, shareholding data, BSE announcements. No credentials needed for public endpoints. | `screener` (fundamental data) | Useful for fundamental screening. BSE/Screener.in data access. |
| **highcharts-heatmap** | marketcalls-all | Nifty 50 treemap heatmap. Flask + Highcharts. Market cap sizing, % change coloring, yfinance data. | terminal SectorMap widget | Simple heatmap pattern. We already have sector-rotation-map reference. |
| **bseindiaapi** | marketcalls-all | Unofficial BSE India Python API. Clean library with tests and docs. | `core` (BSE data access) | Useful if we need BSE-specific data beyond OpenAlgo. |
| **YFinance-Alert-Manager** | marketcalls-all | Real-time stock monitoring + alert system. WebSocket updates, color-coded alerts (above/below/equal), multiple stocks, auto management. | terminal (alert patterns) | Alert system pattern for our planned alerts feature. |
| **stock-dashboard** | marketcalls-all | Flask stock dashboard with OpenAlgo API + LWC charts + EMA/RSI indicators + theme toggle + auto-update + watchlist. | terminal (reference) | Uses our exact stack (OpenAlgo + LWC). Simple reference. |
| **VectorBT-Tearsheets** | marketcalls-all | VectorBT + QuantStats tearsheet generation. EMA crossover strategy, NIFTY 50 benchmark comparison. | `backtest-engine` (tearsheets) | Tearsheet generation pattern for backtest results. |
| **tradingview-yahoo-finance** | tier2-ecosystem | TradingView LWC + yfinance. Multi-timeframe, EMA/RSI, watchlist management, light/dark theme. | terminal (reference) | Similar to stock-dashboard. Uses SQLAlchemy for watchlist persistence. |
| **websocket-stockmarket-clickhouse** | marketcalls-all | WebSocket to ClickHouse pipeline. Real-time stock data capture, async operations. | `data` (time-series storage) | ClickHouse alternative to QuestDB. Pattern reference only. |
| **freqtrade** | tier3-ai-research | Leading open-source crypto algotrading bot. Strategy framework, backtesting, hyperopt, edge positioning. | `engine` (reference) | Massive codebase. Reference for strategy lifecycle, hyperopt, edge positioning. |

---

## LOW Priority (reference only)

| Repo | Location | What | Notes |
|------|----------|------|-------|
| **flowsurface** | marketcalls-all | Rust desktop charting app (iced framework). Heatmap, footprint, DOM ladder, candlestick, comparison charts. Crypto focused (Binance, Bybit). | Rust charting algorithms. REFERENCE ONLY for tick-engine heatmap/footprint logic. |
| **VectorBT-Streamlit** | marketcalls-all | Streamlit VectorBT backtesting app with EMA strategy. | Simple demo. We have better backtest UI plans. |
| **FinRL** | tier3-ai-research | Deep reinforcement learning for financial trading. Environments, agents, data processing. | Academic research. Too complex for direct absorption. |
| **StockSharp** | tier3-ai-research | C#/.NET trading framework. Indicators, strategies, analytics. | Wrong language. Architecture reference only. |
| **backtrader** | external-all | Classic Python backtesting framework. Event-driven, broker simulation. | Well-known reference. We use VectorBT/raptorbt approach instead. |
| **ccxt** | external-all | 113+ crypto exchange connectors. Unified API. | Crypto focused. Not relevant for Indian market. |
| **openalgo-indicator-skills** | tier2-ecosystem | Claude Code skills for OpenAlgo indicators. 100+ Numba-optimized indicators, Plotly charts. | Skills format, not library. Reference for indicator implementations. |
| **Pairs-Trading-Algorithm** | marketcalls-all | Pairs trading with cointegration tests. Jupyter notebook. | Academic pattern. Reference for pairs strategy in backtest-engine. |
| **StatArb-Bayesian-Pairs** | marketcalls-all | Bayesian-optimized pairs trading. Backtrader-based. | Academic pattern. Reference for stat-arb strategy. |
| **quantitative_finance** | marketcalls-all | Academic QF portfolio. Black-Scholes, delta hedging, Hull-White, CAPM, exotic options. C++/Python/MATLAB. | Academic reference for options pricing math. |
| **Hull_Market_Prediction** | marketcalls-all | Transformer encoder for market prediction. Kaggle competition. | Research-only. Transformer allocation model. |
| **QuantFormer** | marketcalls-all | Transformer for quant trading. Chinese market data. Single Jupyter notebook. | Research paper implementation. Not directly useful. |
| **Stocks-Markets** | marketcalls-all | Collection of Jupyter notebooks. Anomaly detection, signal processing, option Greeks, ARIMA. 12+ notebooks. | Academic snippets. Individual notebooks may be useful for specific algorithms. |
| **trading-dashboard** | tier2-ecosystem | React trading dashboard with Tailwind + Recharts. Market summary, watchlist, line chart. | Simple demo. We have far more sophisticated dashboard. |
| **stock-market-dashboard** | tier2-ecosystem | React+Flask stock dashboard. S&P 500 candlestick, dark theme. | US market focused. Simple demo. |
| **opendash** | tier2-ecosystem | Minimal Flask stock dashboard. 3 files total. | Too minimal. |
| **openalgo-rust-mcp** | external-all | OpenAlgo MCP server in Rust. 38 tools, HTTP/SSE transport. | Reference for Rust MCP patterns. Not directly absorbable. |
| **awesome-quant** | external-all | Curated list of quant libraries. README-only repo. | Discovery resource, not code. |
| **awesome-systematic-trading** | external-all | Curated list of systematic trading resources. README-only. | Discovery resource, not code. |

---

## SKIP (not relevant)

| Repo | Location | Reason |
|------|----------|--------|
| **Autonomous-Agents** | external-all | Academic paper collection about autonomous agents. README only. |
| **Ecng** | external-all | C#/.NET StockSharp system framework. Wrong language. |
| **FinRL_Contest_2025** | external-all | Competition starter kit. Academic only. |
| **OpenAlgoNFT** | community-openalgo | NFT platform. Not trading related. |
| **OpenAlgoTrader** | community-openalgo | Rust algo trading platform (IB focused). Unrelated to OpenAlgo India. |
| **balajivinodap-openAlgo** | community-openalgo | C++/MatLab/TradeStation HFT code. Unrelated to our OpenAlgo. |
| **openalgo-frontend** | community-openalgo | Scala/Gradle frontend. Quandl data. Unrelated. |
| **openalgotrade** | community-openalgo | C++ IB API trading tools. Unrelated to our OpenAlgo. |
| **marketnext-openalgo** | community-openalgo | Fork of OpenAlgo. No unique additions over upstream. |
| **openalgo-cryptoinfo** | community-openalgo | Fork of OpenAlgo. No unique additions. |
| **openalgo-platform** | community-openalgo | Fork of OpenAlgo. No unique additions. |
| **myalgo_openalgo** | community-openalgo | Empty wrapper around OpenAlgo. No content. |
| **openalgo-trading-extention** | community-openalgo | Chrome extension for quick trading buttons. Not relevant to React app. |
| **p2c2e-openalgo-mcp** | community-openalgo | Repackaged MCP server. No new content. |
| **openalgo-mvp** | community-openalgo | Simplified OpenAlgo fork with Tailwind/DaisyUI. No unique features. |
| **OpenAlgo-Excel** | marketcalls-all | Excel plugin for OpenAlgo. |
| **OpenAlgo-Java** | marketcalls-all | Java client for OpenAlgo. Wrong language. |
| **OpenAlgo.NET** | marketcalls-all | .NET client for OpenAlgo. Wrong language. |
| **OpenAlgoPlugin** | marketcalls-all | AmiBroker data plugin in C++. Wrong language. |
| **CSharp-NT8-OrderFlowKit** | marketcalls-all | NinjaTrader C# order flow. Wrong language/platform. |
| **NinjaTraderNCDFiles** | marketcalls-all | NinjaTrader data files. |
| **Anthropic-Cybersecurity-Skills** | marketcalls-all | Cybersecurity skills for Claude. Not trading related. |
| **Train_Your_Language_Model_Course** | marketcalls-all | LLM training course. Educational, not trading. |
| **openalgo-go** | marketcalls-all | Go client for OpenAlgo. Wrong language. |
| **openalgo-rust** | marketcalls-all | Rust client for OpenAlgo. Wrong language. |
| **openalgo-node** | marketcalls-all | Node.js client for OpenAlgo. We use Python backend. |
| **openalgo-us** | marketcalls-all | US market version of OpenAlgo. Different market. |
| **openalgo-mobile** | marketcalls-all/tier4 | React Native mobile app. Different platform. |
| **openalgo-excel-addin** | marketcalls-all | Excel add-in. |
| **openalgo-docs** | marketcalls-all | Documentation site. |
| **openalgo-webpage** | marketcalls-all | Marketing website. |
| **opencase-webpage** | marketcalls-all | Marketing website for OpenCase. |
| **opendash-dashboard** | marketcalls-all | Minimal Flask dashboard. 3 files, Vercel deployment. |
| **option-dashboard** | marketcalls-all | PDF + PNG screenshots only. No code. |
| **Options** | marketcalls-all | Text files only (log.txt, review.txt). No code. |
| **Quantzilla** | marketcalls-all | Empty repo. LICENSE only. |
| **openalgo-indicator-skills** (marketcalls) | marketcalls-all | Empty directory. |
| **Amibroker-AFL-codes** | marketcalls-all | AmiBroker AFL code. Wrong platform. |
| **amibroker** | marketcalls-all | AmiBroker related. |
| **autoinstall** | marketcalls-all | Linux auto-install scripts. DevOps. |
| **amazon-s3-operations** | marketcalls-all | AWS S3 operations. Unrelated. |
| **Flask-Amazon-SES-Example** | marketcalls-all | Email sending with SES. Unrelated. |
| **alpaca-websockets** | marketcalls-all | Alpaca API websockets. US market. |
| **codex** | marketcalls-all | AI coding tool. Unrelated. |
| **daisyui** | marketcalls-all | CSS framework fork. We use shadcn/ui. |
| **excalidraw** | marketcalls-all | Drawing tool fork. Unrelated. |
| **LibreChat** | marketcalls-all | Chat UI fork. Unrelated. |
| **listmonk** | marketcalls-all | Newsletter manager. Unrelated. |
| **docker-fastapi-react** | marketcalls-all | Generic Docker template. |
| **flask-traefik** | marketcalls-all | Flask + Traefik reverse proxy. DevOps. |
| **flask-gmail-oauth** | marketcalls-all | Gmail OAuth example. |
| **flask-jupyter** | marketcalls-all | Flask + Jupyter integration. |
| **flask-login-app** | marketcalls-all | Basic Flask login. |
| **flask-socketio-demo** | marketcalls-all | Socket.IO demo. |
| **flask-test** | marketcalls-all | Flask testing example. |
| **flask-user-management** | marketcalls-all | Flask user management. |
| **react-login-app** | marketcalls-all | Basic React login. |
| **google-gemini-slackbot** | marketcalls-all | Slack bot. Unrelated. |
| **gpt-slack-bot** | marketcalls-all | Slack bot. Unrelated. |
| **gptclone** | marketcalls-all | GPT clone UI. Unrelated. |
| **groqbook** | marketcalls-all | Book generation with Groq. Unrelated. |
| **hello-chrome-plugin** | marketcalls-all | Chrome plugin template. |
| **lumentis** | marketcalls-all | Documentation tool. |
| **model-replicator** | marketcalls-all | ML model replication. |
| **fal_marketplace** | marketcalls-all | AI marketplace. Unrelated. |
| **electrobun-skill** | marketcalls-all | Electrobun skill. Unrelated. |
| **forklore** | marketcalls-all | Open-source maintainer stories website. Nuxt.js. Unrelated. |
| **dungbeetle** | marketcalls-all | SQL job server in Go. Not trading related. |
| **jimsimons** | marketcalls-all | Jim Simons biography website. FastAPI + Jinja2. Not code. |
| **marketcalls** | marketcalls-all | Blog/website content. |
| **notebook** | marketcalls-all | Jupyter notebook examples. |
| **data** | marketcalls-all | Data files. |
| **doc/docs** | marketcalls-all/external | Documentation files. |
| **server-monitor-dashboard** | marketcalls-all | Server monitoring. DevOps. |
| **sketchmaker** | marketcalls-all | Image generation tool. Unrelated. |
| **timer** | marketcalls-all | Timer app. Unrelated. |
| **template-prompt-to-video** | marketcalls-all | Video generation. Unrelated. |
| **sample-system-prompt** | marketcalls-all | AI prompt examples. |
| **uv** | external-all | Python package manager. Tool, not trading. |
| **zipline-reloaded** | external-all | Zipline backtesting. We use VectorBT/raptorbt. |
| **vectorbt** | external-all | VectorBT source. We already reference it. Being replaced by raptorbt. |
| **mcporter** | external-all | MCP TypeScript toolkit. Not trading. |
| **MiroFish** | tier3-ai-research | Already used for persona testing. Examined separately. |
| **PrimoGPT** (duplicate) | external-all + tier3 | Already in feature map. |
| **Stockagent** (duplicate) | external-all + tier3 | Already in feature map. |
| **proxy-server** | marketcalls-all | Generic proxy server. |
| **proxy-websockets** | marketcalls-all | WebSocket proxy. |
| **pytvlwcharts** | marketcalls-all | Python wrapper for LWC in notebooks. Not for React. |
| **sparkLib** | marketcalls-all | MaticAlgos Spark client library. Different platform. |
| **taskflow** | marketcalls-all | Task management tool. Unrelated. |
| **wabridge/wabridge-python** | marketcalls-all | WhatsApp bridge. Not trading. |
| **website** | marketcalls-all | Website content. |
| **yfinance** | marketcalls-all | yfinance fork or wrapper. We use openchart/OpenAlgo for data. |
| **yfinancecharts** | marketcalls-all | yfinance + charts. Simple demo. |
| **zipline** | marketcalls-all | Zipline fork. Using raptorbt instead. |
| **metatrader5-quant-server-python** | marketcalls-all | MT5 quant server. Different platform. |
| **crypto-alert-bot** | marketcalls-all | Crypto alert bot. Different market. |
| **companytracker** | marketcalls-all | BSE company tracker. Already referenced in feature map as REFERENCE ONLY. |
| **stockdata** | marketcalls-all | Simple yfinance downloader. 3 files. |
| **StockWatchlist-Flask-App** | marketcalls-all | Basic Flask watchlist. We have far better. |
| **pipeline** | marketcalls-all | Generic data pipeline. |
| **fastalgo** | marketcalls-all | FastAPI RBAC auth system. Not trading specific. Generic auth patterns. |
| **openalgo_mcp** | marketcalls-all | Repackaged MCP server. No new content over tier1 openalgo-mcp. |
| **openalgo-devlopment-environment** | marketcalls-all | Dev environment setup docs. |
| **openalgo-chrome** | tier2-ecosystem | Chrome extension. Already in feature map as REFERENCE ONLY. |
| **fastscalper-tauri** | tier1-core | Tauri desktop scalper app. Different platform (desktop native). |
| **fastscalper** (Flask) | marketcalls-all | Flask + CustomTkinter scalper GUI. Desktop app, not web. |
| **openchart-js** | marketcalls-all | Node.js library for NSE/NFO historical data download. npm package. |
| **openalgo-backtrader** | external-all/tier4 | Backtrader integration with OpenAlgo. Already in feature map. |
| **openalgo-tradingview-scalper** | external-all/tier4 | TradingView scalper. Already in feature map. |
| **openalgostratagies** | external-all/tier4 | Strategy collection. Already in feature map. |
| **trading-strategies-openalgo** | external-all/tier4 | Already in feature map as DIRECT COPY. |

---

## Summary

| Category | Count |
|----------|-------|
| **HIGH priority (absorb now)** | 9 repos |
| **MEDIUM priority (absorb later)** | 17 repos |
| **LOW priority (reference only)** | 12 repos |
| **SKIP (not relevant)** | ~82 repos |
| **Total unexamined** | ~120 repos |

### Top 5 Most Valuable Discoveries

1. **raptorbt** — Rust/PyO3 backtesting engine from the same author (marketcalls). 5800x faster than vectorbt. Has indicators, Monte Carlo, options/pairs/spread backtesting. DIRECTLY applicable to our `tick-engine` and `backtest-engine` packages. This is the single most important discovery.

2. **fluxscan** — Complete scanner engine using OpenAlgo SDK + TA-Lib. Custom Python scanners, scheduled execution, watchlist management, templates. Maps directly to our Scanner widget and screener package.

3. **Agentic-Trader** — Production autonomous trading agent using OpenAlgo API. Single-agent architecture (not multi-agent bloat), parallel data fetching, risk management. Clean reference for our AI package's autonomous trading feature.

4. **AlgoTrade** — Full strategy platform with OpenAlgo. Strategy CRUD, instance deployment, signal generation, WebSocket integration. The strategy lifecycle management patterns map to our engine package.

5. **ExpiryTrack** — F&O expired contract data collector with clean architecture. Task management, data export, encryption. Patterns applicable to our historical package's expiry data handling.

### Updated REPO_FEATURE_MAP Additions Needed

The original feature map should be updated to include:
- raptorbt -> tick-engine + backtest-engine (DIRECT COPY for Rust patterns)
- fluxscan -> screener + terminal Scanner widget (ADAPT)
- Agentic-Trader -> ai + engine (ADAPT)
- AlgoTrade -> engine strategy registry (ADAPT)
- ExpiryTrack -> historical expiry pipeline (ADAPT)
- FinSights -> ai news/sentiment (ADAPT)
- opencase -> terminal Invest route (REFERENCE)
- pandas_signals_library -> indicators (DIRECT COPY for signal functions)
- TradingView-Screener -> screener (ADAPT)

---

*Scan complete. 120 repos examined. 9 HIGH + 17 MEDIUM discoveries. raptorbt is the standout find.*
