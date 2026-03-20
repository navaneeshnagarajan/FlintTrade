> **Status: Absorbed into v2 spec (2026-03-20)**
> All patterns from this document have been integrated into `docs/superpowers/specs/2026-03-19-flinttrade-v2-foundation-design.md`.
> This file is kept for historical reference only.

---

# Autonomous Indian F&O Platform: Enhancement Blueprint

The existing blueprint gains nine critical capabilities through these additions: a professional manual scalping terminal built atop OpenAlgo, multi-broker routing via AlgoMirror with ₹0 brokerage on Kotak Neo, and a fully automated daily broker login system using pyotp — eliminating the feared 3 AM problem entirely. **None of the enhancements below replace existing blueprint components; all are additive layers** that integrate with the existing autonomous trading architecture.

The research uncovered a far richer OpenAlgo ecosystem than previously mapped: **25+ repositories** spanning 6 SDK languages, desktop and mobile apps, a portfolio Greeks calculator, real-time tick aggregation via QuestDB, and an enterprise-grade multi-account management platform. Combined with verified zero-brokerage API trading on Kotak Neo and a robust data layer from jugaad-data, this blueprint enhancement transforms the platform from a single-strategy autonomous system into a complete trading operation supporting manual scalping, autonomous strategies, multi-account family mirroring, and comprehensive options analytics.

---

## 1. Manual trading terminal: the missing interface

The original blueprint focused exclusively on autonomous execution but overlooked a critical need — **manual and semi-automatic trading**. The OpenAlgo ecosystem already provides building blocks for this, and a professional React-based terminal can sit on top of OpenAlgo without modifying it.

### What already exists in OpenAlgo

**FastScalper-Tauri** (`github.com/marketcalls/fastscalper-tauri`) is a lightweight **380×300px** Rust/Tauri desktop app providing four quick-action buttons: LE (Long Entry), LX (Long Exit), SE (Short Entry), SX (Short Exit). It connects to OpenAlgo's `/api/v1/placesmartorder` endpoint via API key, supports CNC/MIS/NRML product types, and includes voice alerts via the Web Speech API. Cross-platform builds are available for Windows (.msi), macOS (.dmg), and Linux (AppImage). While useful for basic scalping, it lacks charts, option chain integration, and keyboard shortcuts — it's a starting point, not a terminal.

**OpenAlgo v2 built-in analytics** already includes TradingView Lightweight Charts in the Historify module, plus a comprehensive options analytics suite: **IV Chart** (implied volatility time series), **IV Smile** (volatility skew across strikes), **ATM Straddle Chart**, **GEX Dashboard** (gamma exposure), **OI Profile/Tracker**, **3D Volatility Surface**, **Max Pain analysis**, and a full **Option Chain with Greeks**. The P&L Tracker provides real-time MTM curves with drawdown analysis using TradingView Lightweight Charts.

**OpenAlgo-PineTS** (`github.com/marketcalls/openalgo-pinets`) demonstrates the integration pattern: a Python Flask backend fetches OHLCV data from OpenAlgo's history API, serves it to a frontend using TradingView Lightweight Charts v5.0.8 with PineTS (TypeScript port of PineScript) indicators. Currently showcases Williams VIX Fix but is architecturally extensible for any indicator.

**OpenAlgo Desktop** (`github.com/marketcalls/openalgo-desktop`), a significant discovery, is a full Tauri 2.0 native desktop application that clones OpenAlgo's web interface with SQLite/DuckDB storage, OS Keychain security (AES-256-GCM, Argon2id), and broker adapters for Angel One, Zerodha, and Fyers. This eliminates server dependency entirely.

### Design specification for the custom scalping terminal

The terminal should be a **separate React application** communicating with OpenAlgo's backend via REST (`http://host:5000/api/v1/`) and WebSocket (`ws://host:8765`). OpenAlgo handles all broker abstraction across 29 supported brokers.

**The canonical 3-chart layout** — borrowed from FYERS' scalper terminal and INDstocks Flash Trading — places three synchronized TradingView Lightweight Charts v5 panels in a CSS Grid: Call Option (CE) on the left, Spot/Index center, Put Option (PE) on the right. A strike selector dropdown above the charts instantly updates CE/PE panels. Each chart instance is independent but synchronized via `timeScale().subscribeVisibleTimeRangeChange()` and crosshair event propagation.

**Execution architecture** uses these OpenAlgo endpoints:

- `/api/v1/placesmartorder` — Position-aware orders (auto-calculates delta between desired and current position; prevents duplicates)
- `/api/v1/optionchain` — Full chain with CE/PE LTP, bid, ask, volume, OI, and strike labels
- `/api/v1/optiongreeks` — Black-76 model returning Delta, Gamma, Theta, Vega, Rho, IV
- `/api/v1/positions` — Real-time position data for P&L display
- `/api/v1/splitorder` — Splits large orders into tranches to reduce slippage
- `/api/v1/cancelallorder` — Emergency cancel all pending orders
- `/api/v1/closeposition` — Square off all open positions

**Keyboard shortcuts** follow the FYERS pattern: `Shift+ArrowUp` for Buy, `Shift+ArrowDown` for Sell, with configurable mappings. **Partial exits** (25%/50%/75%/100%) use a button row that calculates quantity from the open position via the `/api/v1/openposition` endpoint. **Pre-defined order templates** (borrowed from 1Cliq's design) save complete order configurations — segment, strike offset, product type, SL/target — as favorites for instant recall.

The React component architecture should include: `ChartPanel/` (CE/Spot/PE charts with sync manager and strike selector), `OrderPanel/` (QuickTrade buttons, OrderForm, QuantityPresets, KeyboardShortcuts handler), `OptionChain/` (table with Greeks, straddle view), `Positions/` (live P&L, partial exits, square-off-all), `MarketDepth/` (bid/ask order book), and shared hooks (`useOpenAlgoREST`, `useOpenAlgoWebSocket`, `useKeyboardTrading`, `useChartSync`). State management via Zustand stores for positions, orders, and market data.

**TradingView Lightweight Charts v5.1.0** is the correct library: **~35kB** bundle, Apache-2.0 licensed (requires attribution), supports multi-pane charts, custom series, plugin system, and real-time updates via `series.update()`. No official React wrapper exists; build a custom wrapper using `useRef` + `useEffect` from TradingView's tutorial pattern. Throttle updates to **~50ms intervals** to prevent excessive re-renders.

---

## 2. AlgoMirror turns one OpenAlgo into many

**AlgoMirror** (`github.com/marketcalls/algomirror`) is not a plugin — it's a **standalone Flask application** (port 8000) that sits as an orchestration layer on top of multiple OpenAlgo instances (each on port 5000). With **301 commits**, 23 stars, and AGPL-3.0 license, it's the most architecturally sophisticated component in the ecosystem.

### How multi-broker routing actually works

Each OpenAlgo instance connects to exactly one broker. AlgoMirror connects to multiple OpenAlgo instances simultaneously, creating a **many-to-many** relationship:

```
AlgoMirror (Port 8000) → OpenAlgo Instance 1 (Dhan)  → Dhan API
                       → OpenAlgo Instance 2 (Kotak) → Kotak Neo API
                       → OpenAlgo Instance 3 (Angel) → Angel One API
```

Accounts have a **primary/secondary hierarchy**. The primary account provides the WebSocket market data connection for real-time monitoring. Secondary accounts are execution-only. This directly enables the desired architecture: **Dhan as primary** (superior historical data API, better developer ecosystem) for data, backtesting, and paper trading; **Kotak Neo as secondary** for live execution at ₹0 brokerage.

Signal routing is **API-based**, not webhook-based. AlgoMirror's `strategy_executor.py` (110KB) uses **ThreadPoolExecutor** for parallel order placement across all selected accounts simultaneously. A TradingView webhook blueprint also exists for external signal sources.

### Family account mirroring

AlgoMirror's GitHub tagline is literally "Multi Account (Self and Family Account) Handler." When creating a strategy, you select which accounts participate. **Dynamic lot sizing** adjusts per account based on available margin — Account A with ₹5L and Account B with ₹10L receive proportional lots automatically. The margin calculator grades trade quality: **A** (95% fill probability), **B** (65%), **C** (36%).

### Enterprise-grade risk management

AlgoMirror includes **AFL-style Trailing Stop Loss** (peak P&L ratcheting — only moves up, never down), **Supertrend-based exits** (Pine Script v6 compatible, Numba JIT-optimized), max loss/max profit targets with automatic exits, and full **Risk Event Audit Logging** with timestamps, thresholds, and exit order IDs. Holiday detection and special sessions (Muhurat trading) are database-driven, not hardcoded.

### Failover caveat

The README claims "Primary/secondary account hierarchy with automatic failover," and health checking exists via a custom `/api/v1/ping` endpoint. However, **sophisticated conditional routing** (e.g., "if Kotak Neo is down, automatically route to Dhan for execution") is not explicitly documented as a built-in feature. Implementing broker-level failover would require extending `strategy_executor.py` with try/except logic around the OpenAlgo API calls and a fallback account list. This is architecturally straightforward given the existing ThreadPoolExecutor pattern — approximately 50-100 lines of additional code in the executor.

---

## 3. Kotak Neo at zero brokerage is verified and real

**Confirmed: Kotak Neo charges ₹0 brokerage and ₹0 API platform fees on all API-placed orders**, effective November 1, 2025, across all Trade Free plans. This applies to equity delivery, intraday, F&O, cover orders, bracket orders, and AMO orders. The sole exception: bracket order square-off legs attract standard brokerage.

This is not marketing spin — it's documented in Kotak Securities' official press release and the kotakneo.com/platform page. **Only statutory/regulatory charges** apply (identical at every broker):

- **STT**: Currently 0.02% futures (sell side), 0.1% options (sell on premium). **Increasing April 1, 2026** to 0.05% futures (+150%) and 0.15% options (+50%) per Union Budget 2026
- **Exchange transaction charges (NSE)**: ₹1.73/lakh for futures, ₹35.03/lakh premium for options
- **GST**: 18% on brokerage + exchange charges + SEBI fees
- **SEBI fees**: ₹10/crore; **Stamp duty**: 0.002% buy-side futures, 0.003% options
- **Demat AMC**: ₹600/year (unavoidable)

### API capabilities and limitations

Kotak Neo's API claims **sub-50ms order execution latency** with a **10 orders/second** rate limit. WebSocket streaming supports live market data across equities, derivatives, and currency. The official Python SDK (`neo_api_client`) handles authentication, order management, and real-time data. **OpenAlgo fully supports Kotak Neo** as broker key `kotak`, migrated to API v2 with TOTP-based authentication and WebSocket support for 1000 symbols per connection.

**The critical gap is historical data** — Kotak Neo's API does not provide a dedicated historical data endpoint. GitHub issues confirm this limitation. This is precisely why the Dhan-primary/Kotak-secondary architecture matters: **use Dhan's historical data API for backtesting and strategy development**, Kotak Neo purely for cost-optimized live execution.

### Cost savings quantified

For a trader executing **100 F&O option trades per day** via API:
- Kotak Neo brokerage: **₹0**
- Dhan brokerage: ₹20 × 100 = **₹2,000/day** = ~₹44,000/month
- Annual saving: **~₹5.3 lakh** in brokerage alone

The calculus is clear: Kotak Neo for execution, Dhan for everything else.

---

## 4. Solving the 3 AM broker login problem

This was flagged as the most critical operational risk. The good news: **the 3 AM login is unnecessary**. The solution is straightforward and battle-tested across the Indian algo trading community.

### Why 3 AM is wrong

OpenAlgo's default `SESSION_EXPIRY_TIME` is `03:00` IST, but this is **configurable** in `.env`. More importantly, broker tokens don't need to be generated at session expiry time — they need to be generated **before market opens at 9:15 AM**. The correct approach:

- Zerodha tokens flush between **6:45-7:30 AM** daily — generate after 7:35 AM
- Dhan tokens last **24 hours from generation** — generate at 8:30 AM
- Angel One tokens are day-scoped — generate at 8:30 AM
- Kotak Neo tokens are daily — generate at 8:30 AM

**Set `SESSION_EXPIRY_TIME=08:00` and schedule automated login at 8:30 AM IST** (45 minutes before market open, ample buffer for retries).

### The pyotp solution

Every major Indian broker's TOTP-based login is fully automatable using the **pyotp** Python library. The TOTP secret is extracted once during initial 2FA setup (from the QR code URI's `secret=` parameter) and stored securely.

**Angel One** — the simplest to automate. The official SmartAPI SDK includes pyotp as a dependency. One API call generates the session:

```python
from SmartApi import SmartConnect
import pyotp
totp = pyotp.TOTP('YOUR_TOTP_SECRET').now()
data = smartApi.generateSession(username, pwd, totp)
```

**Dhan** — fully automatable via a direct token generation endpoint (`POST https://auth.dhan.co/app/generateAccessToken`) accepting client ID, PIN, and TOTP. Uniquely offers a **RenewToken API** that extends an active token by 24 hours without re-authentication — providing a resilience buffer.

**Kotak Neo** — two-step TOTP + MPIN validation, both programmable via the `neo_api_client` SDK with pyotp-generated TOTP codes.

**Zerodha** — requires simulating the OAuth2 browser flow via HTTP requests + pyotp (no Selenium needed). Multiple production-ready implementations exist. The `zlogin` PyPI package specifically handles this.

### Recommended cron architecture

```cron
# Generate new broker tokens at 8:30 AM IST, weekdays only
30 8 * * 1-5 python3 /home/trader/auto_login.py >> /var/log/trading/login.log 2>&1

# Health check at 9:10 AM (5 min before market open)
10 9 * * 1-5 python3 /home/trader/check_session.py >> /var/log/trading/health.log 2>&1
```

The login script should implement: **TOTP timing edge-case handling** (if generated within last 5 seconds of a 30-second period, wait for the next code), **3 retries with 30-second intervals**, and a **Telegram alert** on failure for manual intervention. Skip weekends and NSE holidays using jugaad-data's `holidays()` function.

**No Indian broker offers persistent sessions** — exchange regulations mandate daily re-authentication. But with pyotp, the daily login is invisible: a cron job at 8:30 AM handles everything, and the system is fully operational by 8:31 AM.

---

## 5. The full OpenAlgo ecosystem: 25 repos mapped

The marketcalls GitHub account hosts a "Mini FOSS Universe" far larger than previously analyzed. Here are the highest-value repos for an F&O platform, ranked by criticality:

### Tier 1 — Critical for F&O operations

**openalgo-portfoliogreeks** — Portfolio-level options Greeks calculator using Black-Scholes. Fetches dynamic lot sizes from OpenAlgo, applies position-aware sign conventions (BUY/SELL × CE/PE), displays lot-based Greeks, and aggregates Delta/Gamma/Theta/Vega across the entire portfolio. This is **the** core risk management tool for multi-leg options positions.

**OpenQuest** (`openquest`) — Real-time tick data aggregation into QuestDB (time-series database) with TradingView streaming charts. Captures LTP, Quote, and Depth data across NSE, BSE, NFO, BFO, MCX at high frequency. Essential for live Greeks computation, options analytics, and any strategy requiring tick-level data.

**AlgoMirror** — Multi-account family handler with trailing SL, Supertrend exits, margin calculation, and trade quality grading. Covered in detail in Section 2.

**OpenAlgo Desktop** — Full Tauri 2.0 native app with zero server dependency, OS Keychain security, SQLite/DuckDB storage. Currently supports Angel One, Zerodha, and Fyers broker adapters.

**OpenAlgo-Excel** — C#/Excel-DNA add-in providing `=oa_placesmartorder()`, `=oa_splitorder()`, `=oa_modifyorder()` functions plus **WebSocket streaming directly into Excel cells** (LTP, Quote, Depth modes). For F&O traders who think in spreadsheets, this enables custom option chain sheets, payoff diagrams, and one-click execution without leaving Excel.

### Tier 2 — High value integrations

**openalgo-python-library** — Official Python SDK (`pip install openalgo`) with full options support: multi-leg orders (Iron Condors, spreads), ATM/OTM/ITM offset-based strike selection, WebSocket streaming, basket orders. The primary SDK for strategy development.

**openalgo-chrome** — Lightweight Chrome extension providing a draggable floating widget with LE/LX/SE/SX buttons on any charting page. Enables instant order placement while viewing TradingView or any web-based chart.

**openalgo-mobile** — Flutter app (Dart SDK 3.35.4) with watchlist management, real-time quotes (5-second refresh), full order management, position tracking, and TradingView Lightweight Charts via WebView. Builds for Android APK and web.

**openalgo-mcp** — Model Context Protocol server exposing 15+ trading tools for AI-driven natural language trading. Users describe complex options strategies in plain English; the MCP server translates to OpenAlgo API calls.

**openalgo-rust** — Rust SDK with ultra-low-latency options multi-order support (Bull Call Spread example included), WebSocket streaming, and the `tokio` async runtime.

**openengine** — Event-driven backtesting engine with live trading support via OpenAlgo's PlaceOrder API. Extensible for F&O strategy testing.

**p2c2e/openalgo-backtrader** — Community-built Backtrader framework integration, listed in OpenAlgo's official Mini FOSS Universe.

### Tier 3 — Supporting ecosystem

**openalgo-node**, **openalgo-go**, **openalgo-java**, **openalgo.NET** — SDKs in JavaScript/TypeScript, Go, Java, and C#/.NET respectively. The Node SDK mirrors the Python library's functionality for web-based dashboards. The Go and Rust SDKs target performance-critical applications.

**OpenAlgoPlugin** — Native C++ AmiBroker data plugin for WebSocket-based real-time streaming and historical data backfill. Sub-second latency with intelligent 5-second TTL caching.

**openalgo-docs** — GitBook-based documentation published at docs.openalgo.in. **openalgo-webpage** — Next.js marketing site.

---

## 6. Screening and market data layer

### OpenAlgo is an execution layer, not a screener — but it integrates with one

OpenAlgo includes basic indicator scanning (RSI oversold/overbought, EMA crossover, SuperTrend buy, volume spike) via its Skills system, plus a comprehensive Option Chain API and Greeks API. However, it does not replicate the full screening capabilities of Sensibull or Opstra.

**ChartInk integration is native and documented** at docs.openalgo.in. ChartInk webhook alerts trigger OpenAlgo strategies with dual-queue order processing (regular queue at 10 orders/sec for BUY/SHORT, smart queue for SELL/COVER), auto square-off for intraday strategies, and symbol-level configuration. Requires ChartInk paid account and Ngrok with custom domain for local hosting. For automation without webhooks, ChartInk's internal API (`POST https://chartink.com/screener/process` with CSRF token and `scan_clause` parameter) can be scraped directly.

### Sensibull and Opstra feature targets for replication

**Sensibull's "Options Central"** screens on ATM IV, IV Percentile (vs 6-month average), PCR, volume change, futures OI change, long/short buildup detection, sector filtering, and FII/DII data integration. **Opstra** adds 3D volatility surface, OI dynamics (max OI strikes, additions, unwinding), MWPL/ban list tracking, and intraday options backtesting on 5-minute data.

**Core screener features are replicable** using free data sources:

- ✅ Live option chain with OI, volume, LTP — via `jugaad-data NSELive().option_chain()`
- ✅ PCR calculation — sum put OI ÷ sum call OI
- ✅ OI change/buildup analysis — compare current vs previous bhavcopies
- ✅ IV Rank — store daily IV, compute against 52-week range
- ✅ Technical indicators — TA-Lib or pandas_ta on historical data
- ❌ Real-time intraday IV charts (need tick-level data — use OpenQuest)
- ❌ Intraday options backtesting (requires stored tick data)

### jugaad-data: the essential free data library

**jugaad-data** (`pip install jugaad-data`, v0.29, ~492 GitHub stars, YOLO License) provides the most comprehensive free NSE data access:

**Historical data**: `stock_df()` for equities, `index_df()` for indices, `derivatives_df()` for futures and options (FUTSTK/FUTIDX/OPTSTK/OPTIDX) with fields including OHLC, settle price, volume, OI, change in OI. Supports specific strike and option type filtering. **Bhavcopies**: `bhavcopy_save()` (equity) and `bhavcopy_fo_save()` (F&O) download full daily CSVs. **Live data**: `NSELive()` class provides `stock_quote()`, `option_chain()`, `all_indices()`, `live_index()`, `tick_data()`, `trade_info()`, `announcements()`, `market_status()`, and `equity_derivative_turnover()`. Also includes **RBI economic data** (policy rates, deposit rates, T-Bill rates) and an `expiry_dates()` utility.

**Critical rate limiting caveat**: NSE actively blocks IPs making too many requests. Space out requests, use the built-in caching, avoid bulk historical downloads in rapid succession, and use `holidays()` to skip non-trading days.

**nsefin** (`pip install nsefin`) adds two features jugaad-data lacks: **pre-market data** (`get_pre_market_info(category="FO")`) for gap analysis before market open, and **built-in Greek computation** (`compute_greek(option_chain, strike_diff=50)`) without requiring external Black-Scholes implementations. However, it has less extensive historical data coverage overall.

---

## 7. Expanding the capability surface

### Highest-priority additions (low complexity, very high value)

**Telegram bot for monitoring** is the single most impactful addition. Using `python-telegram-bot`, implement: trade execution notifications (via OpenAlgo webhook), P&L threshold alerts, position/exposure summary on `/positions` command, OI spurt notifications, and market open/close summaries. OpenAlgo already has native Telegram integration with `/chart`, `/indicator-chart`, `/link`, and `/status` commands — extend this with custom monitoring commands. Near-zero cost, universally accessible on mobile.

**OI spurts and PCR alert system** monitors the NSE option chain for sudden OI spikes indicating institutional positioning. The `Python-NSE-Option-Chain-Analyzer` (GitHub: VarunS2002) is a mature open-source tool calculating Call/Put OI sums, detecting trend changes, and sending toast notifications. Build as a background daemon that polls `NSELive().option_chain()` every 3 minutes (respecting rate limits), computes PCR, identifies long/short buildups via the price+OI change matrix, and alerts via Telegram when thresholds are breached.

**FII/DII flow tracker** scrapes NSE's daily FII/DII activity data (published 6-7 PM IST at nseindia.com/reports/fii-dii) covering cash and F&O segments. The `nse-python` library provides Pandas-formatted FII/DII data. Track net institutional flows relative to market levels as a directional sentiment indicator.

**Brokerage calculator** is straightforward arithmetic: brokerage + STT + exchange charges + GST + SEBI fees + stamp duty across Zerodha, Dhan, Kotak Neo, Angel One, FYERS, and Groww. Critical post-April 2026 given the **150% STT increase on futures** (0.02% → 0.05%) and **50% on options** (0.1% → 0.15%).

### Medium-priority additions (medium complexity, high value)

**Options strategy builder with payoff diagrams** using **OptionLab** (`pip install optionlab`) — supports multi-leg strategies, Black-Scholes + Monte Carlo probability-of-profit calculation, per-leg Greeks, and dynamic strategy support with `prev_pos`. Alternatively, **opstrat** provides lightweight payoff charts. Visualize via Plotly in a Streamlit dashboard.

**IV surface visualization** using **volvisualizer** (`pip install volvisualizer`) for interactive 3D Plotly surfaces with spline/mesh/RBF smoothing, or build custom using `py_vollib` for IV calculation + SciPy optimization + Plotly for rendering. OpenAlgo v2 already includes a 3D Volatility Surface blueprint (`vol_surface.py`) — leverage this existing infrastructure.

**Tax optimization module** tracking all F&O charges (STT, CTT, GST, stamp duty, exchange fees) per trade, computing turnover for audit thresholds (₹1 Crore / ₹10 Crore), identifying tax-loss harvesting opportunities, and estimating advance tax obligations. F&O income is **non-speculative business income** taxed at slab rates (ITR-3 filing required). With the 2026 STT hike, a trader doing 20 futures contracts of ₹20L each pays **₹20,000 in STT alone** — cost awareness is no longer optional.

**Earnings calendar with IV crush analysis** requires collecting historical IV data across earnings cycles. Track: pre-earnings IV percentile, implied move (ATM straddle price), historical actual moves, and IV30/ex-earnings IV ratio. Identify high-probability premium selling opportunities where implied move consistently exceeds actual move.

### Lower-priority additions (higher complexity or experimental)

**Portfolio margin optimizer** requires implementing SPAN margin calculation (16 risk scenarios) and cross-margining rules. High complexity but high value — optimal hedging can reduce margin consumption by **20-30%**.

**OpenClaw integration** is experimental. OpenClaw (formerly ClawdBot) is an open-source AI agent framework with 250,000+ GitHub stars. Marketcalls has posted about "Automate Your Trading and Workflows with OpenClaw and OpenAlgo." The integration enables voice-commanded and AI-monitored trading. **Caution**: 1,184 malicious skills were caught in OpenClaw's marketplace distributing wallet-stealing malware. Use only as a monitoring/alerting layer, never for autonomous execution without human approval gates.

---

## 8. Four CLAUDE.md files for four machines

Based on best practices from Anthropic's official documentation and expert practitioners, CLAUDE.md files should be **under 200 lines**, focus on what Claude Code can't infer from the codebase, and use progressive disclosure (point to docs rather than inlining everything). Never include code style rules (use linters instead). Claude loads CLAUDE.md files hierarchically: home directory → parent directories → project root → subdirectories.

### File 1: Project root CLAUDE.md (committed to git, shared across all machines)

```markdown
# Indian F&O Autonomous Trading Platform

Autonomous + manual F&O trading platform built on OpenAlgo (v2.0+) with
multi-broker routing via AlgoMirror, React scalping terminal, and options analytics.

## Architecture
- `/openalgo/` — OpenAlgo core instance (Flask, port 5000)
- `/algomirror/` — Multi-account router (Flask, port 8000)
- `/terminal/` — React manual scalping terminal (Vite, port 3000)
- `/strategies/` — Python strategy modules (autonomous execution)
- `/analytics/` — Options analytics (Greeks, IV surface, screeners)
- `/data/` — Market data layer (jugaad-data, DuckDB, QuestDB)
- `/alerts/` — Telegram bot + OI/PCR monitoring daemons
- `/infra/` — Docker, cron jobs, auto-login scripts, deployment

## Tech Stack
- Python 3.12+, Flask, React 19, TradingView Lightweight Charts v5
- OpenAlgo Python SDK (`pip install openalgo`)
- Broker targets: Dhan (data/primary), Kotak Neo (execution/₹0 brokerage)
- DuckDB for historical data, QuestDB for real-time ticks, Redis for caching
- pyotp for automated broker TOTP login

## Commands
- `cd openalgo && python app.py` — Start OpenAlgo (port 5000)
- `cd algomirror && gunicorn -w 1 -k gthread app:app -b 0.0.0.0:8000`
- `cd terminal && npm run dev` — Start React terminal (port 3000)
- `cd strategies && python run.py --strategy momentum_v3`
- `python -m pytest tests/ -v` — Run all tests
- `docker-compose up` — Full stack

## Key Patterns
- ALL broker calls go through OpenAlgo API — never call broker APIs directly
- Strategies implement `BaseStrategy` abstract class in `/strategies/base.py`
- Use `placesmartorder` (position-aware) over `placeorder` for all execution
- Option symbols follow NSE format: NIFTY28MAR2620800CE
- F&O lot sizes change periodically — always fetch dynamically via API
- Market hours: 9:15 AM - 3:30 PM IST; pre-open: 9:00-9:08 AM

## Critical Rules
- NEVER commit .env files, API keys, or TOTP secrets
- NEVER modify OpenAlgo core — build extensions on top via API
- Always handle TOTP timing edge case (wait if <5 seconds remaining in period)
- Test all strategies in Analyze/Sandbox mode before live execution
- STT rates change April 1, 2026 — verify charge calculations
```

### File 2: Development machine (~/.claude/CLAUDE.md, NOT committed)

```markdown
# Machine: Development Laptop (macOS)

This is the primary development machine. Runs OpenAlgo locally for testing.
No live trading from this machine — Analyze/Sandbox mode only.

## Environment
- macOS, Homebrew, Python via pyenv (3.12.x)
- Node 20 LTS, npm, Rust/Cargo for Tauri builds
- Docker Desktop for local QuestDB and Redis
- VS Code with Ruff, ESLint, Prettier

## Local Services
- OpenAlgo: http://127.0.0.1:5000 (Dhan sandbox broker)
- QuestDB: http://127.0.0.1:9000 (tick data store)
- Redis: 127.0.0.1:6379

## Workflow
- Strategy development → test in Sandbox → PR to main → deploy to trading server
- React terminal development uses Vite hot reload on port 3000
- Use `openalgo` Python SDK pointed at localhost for all data/order testing
```

### File 3: Trading server (~/.claude/CLAUDE.md, NOT committed)

```markdown
# Machine: Trading Server (Ubuntu 24.04, cloud VPS)

LIVE TRADING SERVER — changes here affect real money. Extreme caution required.
Static IP registered with Dhan and Kotak Neo for SEBI compliance.

## Environment
- Ubuntu 24.04 LTS, Python 3.12, Node 20 LTS
- Systemd services for OpenAlgo, AlgoMirror, alert daemons
- Nginx reverse proxy on port 443 (SSL)
- PostgreSQL for AlgoMirror, DuckDB for OpenAlgo Historify

## Critical Services
- OpenAlgo (Dhan): systemctl status openalgo-dhan
- OpenAlgo (Kotak): systemctl status openalgo-kotak
- AlgoMirror: systemctl status algomirror
- Auto-login cron: 8:30 AM IST weekdays (`/home/trader/infra/auto_login.py`)
- Health check cron: 9:10 AM IST (`/home/trader/infra/check_session.py`)
- Telegram alert daemon: systemctl status telegram-alerts

## NEVER do on this machine
- Run pytest against live broker (use Sandbox mode)
- Restart OpenAlgo during market hours without stopping strategies first
- Modify .env files without restarting dependent services
- Deploy untested strategy code directly
```

### File 4: Analytics/data server (~/.claude/CLAUDE.md, NOT committed)

```markdown
# Machine: Analytics Server (Ubuntu 24.04, local NAS)

Data collection, backtesting, and analytics. No live order execution.
Runs QuestDB for tick storage and DuckDB for historical analysis.

## Environment
- Ubuntu 24.04, Python 3.12, QuestDB, DuckDB, Grafana
- jugaad-data for NSE data downloads (respect rate limits!)
- OpenQuest for real-time tick aggregation from OpenAlgo WebSocket

## Services
- QuestDB: http://localhost:9000 (tick data, options chains)
- Grafana: http://localhost:3000 (dashboards)
- OpenQuest: systemctl status openquest
- Nightly bhav copy download: 6:00 PM IST cron

## Data Conventions
- All timestamps in IST (Asia/Kolkata)
- Historical F&O data in DuckDB: `/data/fno_history.duckdb`
- Tick data in QuestDB: tables per symbol (e.g., `ticks_NIFTY`)
- NSE bhavcopies stored: `/data/bhavcopies/equity/` and `/data/bhavcopies/fno/`
- Rate limit jugaad-data: max 1 request per 3 seconds for live, 1 per second for historical
```

---

## What this blueprint now covers that it didn't before

The original autonomous trading blueprint gains **nine new capability layers** through these additions. The manual scalping terminal fills the largest gap — autonomous traders still need to intervene manually when markets move unexpectedly, and a keyboard-driven React terminal with synchronized CE/Spot/PE charts provides that capability without abandoning the OpenAlgo infrastructure. AlgoMirror transforms a single-broker setup into a multi-account operation capable of mirroring strategies across family accounts while routing execution to the cheapest broker. The pyotp-based automated login eliminates the single biggest operational friction point — daily broker authentication — by reducing it to a silent 8:30 AM cron job that completes in under 2 seconds.

The data layer is now fully specified: jugaad-data for free NSE historical and live data, nsefin for pre-market data and Greek computation, OpenQuest/QuestDB for real-time tick storage, and DuckDB for analytical queries. The screening capability gap is addressed through ChartInk integration (native in OpenAlgo), custom Python screeners using NSE option chain data, and a clear path to replicating Sensibull/Opstra's core metrics. The CLAUDE.md specification ensures that Claude Code operates effectively across all four machines with appropriate context and safety guardrails — particularly the trading server, where changes affect real capital.