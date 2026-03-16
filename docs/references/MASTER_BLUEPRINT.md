# The definitive master blueprint for autonomous Indian F&O trading

**Dhan is the unequivocal primary broker, Ubuntu Server 24.04 LTS powers the 24/7 trading server, and a 20-week phased roadmap transforms three machines — a custom PC, an Acer Nitro laptop, and a MacBook Air M4 — into an institutional-grade autonomous F&O platform built on OpenAlgo v2.** This blueprint covers every hardware component, software subscription, broker API, OS configuration, AI model, trading strategy, data pipeline, safety system, and SEBI compliance requirement. It is designed to serve as the `CLAUDE.md` context file for Claude Code to execute the entire build.

---

## 1. Broker analysis: Dhan wins by a decisive margin

After evaluating all 29 brokers supported by OpenAlgo, **Dhan is the only broker providing 5 years of minute-level expired options data with pre-calculated IV, OI, volume, and spot price** — a capability no other Indian broker matches. The Rolling Option API endpoint (`POST https://api.dhan.co/v2/charts/rollingoption`) returns ATM ± 10 strikes for index options across weekly and monthly expiries at 1/5/15/25/60-minute intervals, with a 30-day window per call and **100,000 requests/day** with no rate limits on minute-level data.

Dhan also leads in execution quality. OpenAlgo latency benchmarks show **45ms average RTT with 99.9% success rate** — faster than Zerodha (65ms), Angel One (85ms), and all other tested brokers. The WebSocket supports 5 connections × 5,000 instruments each, delivering full packets (LTP + OI + market depth up to 200 levels). The option chain API provides real-time Greeks, OI, volume, and bid/ask data. Trading APIs are **free** for all users; data APIs are free with 25+ F&O trades per month (otherwise ₹499/month).

**Recommended broker architecture:**

| Role | Broker | Rationale |
|------|--------|-----------|
| Primary (execution + data) | **Dhan** | Fastest RTT, best expired options API, richest WebSocket, free APIs |
| Secondary (backup + OHLC data) | **Upstox** | Contract-level expired options data (OHLC only), mature v3 API, ₹499/month |
| Sandbox/paper trading | **Dhan Sandbox** | Built into OpenAlgo as `dhan_sandbox`, ₹1 Cr virtual capital, same API structure |

**Brokers to avoid for this use case:** Kotak Neo (no historical data API), TradeSmart Online (not in OpenAlgo, no data API), Groww (too new, limited API features). Zerodha's ₹500/month Kite Connect subscription offers no expired options data and inferior latency. Fyers offers 50-level market depth and 25+ years of daily data but the user lacks an account.

**Key Dhan API endpoints:**

| Purpose | Endpoint |
|---------|----------|
| Rolling expired options | `POST /v2/charts/rollingoption` |
| Daily historical | `POST /v2/charts/historical` |
| Intraday historical | `POST /v2/charts/intraday` |
| Market quote (full) | `POST /v2/marketfeed/quote` |
| Option chain | DhanHQ Python SDK |
| Place order | `POST /v2/orders` |
| WebSocket | DhanHQ SDK (5 connections × 5000 instruments) |

Dhan requires a **static IP for order APIs**, aligning perfectly with the ER605's static IP WAN configuration and SEBI's April 2026 mandate.

---

## 2. OS and device configuration across three machines

### Custom PC: Ubuntu Server 24.04 LTS (24/7 trading server)

Install **Ubuntu Server 24.04 LTS** with the HWE kernel for latest hardware support. The RX 6600 XT (gfx1032) requires **ROCm 6.4.3+** with the critical environment variable `HSA_OVERRIDE_GFX_VERSION=10.3.0` — this GPU is not officially in ROCm's supported list but works reliably with this override. The i3-9350KF has no integrated GPU (the "F" suffix), eliminating iGPU conflicts.

Install XFCE4 as an on-demand lightweight desktop (`sudo systemctl set-default multi-user.target` keeps it in CLI mode by default; start GUI with `sudo systemctl start lightdm` when needed on the 32" monitor). Deploy **Cockpit** on port 9090 for web-based server management from any browser. Key installation sequence:

```bash
# ROCm installation
wget https://repo.radeon.com/amdgpu-install/6.4.3/ubuntu/noble/amdgpu-install_6.4.60403-1_all.deb
sudo dpkg -i ./amdgpu-install_6.4.60403-1_all.deb && sudo apt update
sudo amdgpu-install --usecase=rocm
sudo usermod -aG render,video $LOGNAME

# Ollama with ROCm override
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl edit ollama  # Add: Environment="HSA_OVERRIDE_GFX_VERSION=10.3.0"

# OpenAlgo v2 (native install per docs)
cd /opt && sudo git clone https://github.com/marketcalls/openalgo.git
cd openalgo/install && chmod +x install.sh && sudo ./install.sh
```

**Storage layout:** 512GB SSD holds OS + applications (~100GB used), 5TB HDD mounted at `/data` for historical data and archived logs, 1TB external SSD mounted at `/backup` for daily rsync of databases and critical configs.

### Acer Nitro: Keep Windows 11 + WSL2 Ubuntu 24.04

The current setup is optimal. Google Antigravity IDE runs natively on Windows. The RTX 5050 (Blackwell architecture, sm_120) needs **CUDA 12.8 + PyTorch 2.7+** — the NVIDIA driver on Windows passes through to WSL2 with near-native performance. Unsloth explicitly supports RTX 50-series and provides WSL2-specific installation guides.

Configure `.wslconfig` to allocate 12GB RAM to WSL2 (leaving 4GB for Windows). Install Miniconda inside WSL2, create a dedicated `unsloth_env` with Python 3.12, and set `TORCH_CUDA_ARCH_LIST=12.0` when building xformers. The RTX 5050's 8GB VRAM handles QLoRA fine-tuning of 8B models at batch_size=1 with gradient checkpointing.

### MacBook Air M4: macOS with Homebrew stack

Install core tools via Homebrew: Python 3.12, Node.js 22, Rust toolchain, Ollama (uses Metal/MLX backend), Docker/OrbStack, Claude Code CLI (`npm install -g @anthropic-ai/claude-code`). Configure SSH with port forwarding to the trading server for Cockpit (9090), Uptime Kuma (3001), and OpenAlgo (5000). The 256GB SSD demands lean local storage — keep large models and datasets on the server.

### Complete device role assignment

| Attribute | Custom PC (Server) | Acer Nitro (Dev) | MacBook M4 (Mobile) |
|---|---|---|---|
| **OS** | Ubuntu Server 24.04 LTS + XFCE on-demand | Windows 11 + WSL2 Ubuntu 24.04 | macOS Sequoia/Tahoe |
| **Primary role** | 24/7 production trading | ML training + fine-tuning | Mobile dev + code review |
| **GPU purpose** | Ollama LLM inference (ROCm) | Unsloth QLoRA, PyTorch, CUDA | MLX inference (Metal) |
| **Always-on** | Yes (UPS protected) | On-demand | On-demand |
| **Key software** | OpenAlgo, OpenClaw, Ollama, nginx, Cockpit, NUT | Antigravity IDE, VS Code+WSL2, Unsloth, PyTorch | VS Code, Antigravity, Claude Code, Ollama |
| **Power draw** | ~120-200W | ~60-100W | ~10-15W |

### UPS configuration: 7-9 hours of backup

The 2kW inverter with 2×200Ah batteries (24V system) provides **4,800Wh nominal** energy. At 50% depth of discharge (optimal for lead-acid longevity) and 85% inverter efficiency, usable energy is **2,040Wh**. Running the headless server (~200W), router (~12W), and one mesh unit (~10W) gives approximately **9.2 hours of backup**. Even at 80% DoD, the system provides **14+ hours**.

Since home inverters typically lack USB data communication, place a small UPS with USB (APC Back-UPS 600VA) between the inverter output and the PC for NUT monitoring. Configure ASRock H370M-HDV BIOS: **Advanced → ACPI Configuration → Restore on AC/Power Loss → "Power On"** for automatic restart. Create a systemd service that cancels all open orders, stops OpenAlgo/OpenClaw, syncs databases to the external SSD, then initiates shutdown when NUT detects low battery.

---

## 3. The combined fork: 20 repos into one monorepo

The `marketcalls` GitHub account contains **20 repositories** forming the OpenAlgo ecosystem. The recommended approach is **git subtree** (not submodules) — subtrees embed code directly, avoid detached HEAD issues, and allow local modifications while maintaining the ability to pull upstream changes.

**Core repositories to include:**

| Repository | Purpose | Language | Monorepo path |
|---|---|---|---|
| `openalgo` (★1,400+, 720 forks) | Trading backend, 29 broker adapters | Python Flask | `packages/openalgo/` |
| `openclaw` (external: openclaw/openclaw) | AI agent gateway with persistent memory | Node.js/TypeScript | `packages/openclaw-gateway/` |
| `fastscalper-tauri` | Rust desktop scalping tool | Rust + Tauri | `packages/fastscalper/` |
| `openalgo-desktop` | Full desktop app (Tauri 2.0) | Rust + TypeScript | `packages/openalgo-desktop/` |
| `historify` | Historical data management | Python + DuckDB | `data/historify/` |
| `openquest` | Real-time tick aggregation to QuestDB | Python + QuestDB | `data/openquest/` |
| `openalgo-pinets` | TradingView charts + PineTS indicators | Python + JS | `frontend/charts/` |
| `openalgo-python-library` | Python SDK | Python | `libs/python-sdk/` |
| `openalgo-node` | Node.js SDK | JavaScript | `libs/node-sdk/` |
| `openalgo-rust` | Rust SDK (async + tokio) | Rust | `libs/rust-sdk/` |
| `openalgo-go` | Go SDK | Go | `libs/go-sdk/` |
| `openalgo-mcp` | MCP server for AI agent bridge | Python FastMCP | `skills/mcp-server/` |
| `vectorbt-backtesting-skills` | VectorBT backtesting for 40+ AI agents | Python | `skills/backtesting/` |
| `openalgo-chrome` | Chrome extension trading UI | Chrome API | `extensions/chrome/` |
| `OpenAlgo-Excel` | Excel add-in | VBA/Office | `extensions/excel/` |
| `openalgo-docs` | GitBook documentation | Markdown | `docs/` |

**Initial subtree setup commands:**
```bash
git subtree add --prefix=packages/openalgo https://github.com/marketcalls/openalgo.git main --squash
git subtree add --prefix=data/historify https://github.com/marketcalls/historify.git main --squash
git subtree add --prefix=skills/mcp-server https://github.com/marketcalls/openalgo-mcp.git main --squash
# ... repeat for each repo
```

Maintain a `scripts/subtree-sync.sh` that iterates through all subtree prefixes and runs `git subtree pull --squash` weekly. Orchestrate all services with a root `docker-compose.yml` mapping OpenAlgo to port 5000, OpenClaw to 18789, OpenQuest to 5001, PineTS charts to 5005, and nginx as reverse proxy on 80/443.

**Third-party libraries to integrate:** TradingView Lightweight Charts v5.0.8 (already used in openalgo-pinets), Plotly (backtesting visualization), Recharts (React dashboard charts), D3.js (custom orderflow visualization), VectorBT + TA-Lib + QuantStats (backtesting pipeline).

**Architecture flow:**
```
OpenClaw (AI Brain) → REST API → OpenAlgo (Execution Engine) → Broker APIs
                                      ↕                           ↕
                              Historify (DuckDB)          WebSocket (Market Data)
                              OpenQuest (QuestDB)         MCP Server (AI Tools)
                                      ↓
                              VectorBT (Backtesting) → PineTS Charts (Visualization)
```

---

## 4. OpenAlgo v2 complete ecosystem audit

OpenAlgo v2.0.0.0 represents a **complete frontend rewrite** from Flask/Jinja2 to React 19 SPA, with 212 commits introducing major new capabilities. The platform provides a unified API layer across **29 Indian brokers** with plugin-based architecture, multi-database design (SQLite for user data, DuckDB for historical data), and real-time WebSocket streaming via ZeroMQ.

**Feature inventory:**

**Trading & Execution:** Python strategy hosting (isolated processes with scheduling), Flow Visual Builder (node-based drag-and-drop: trigger → condition → action → output nodes with order types including Market, Limit, Smart, Basket, Options, Modify, Cancel, Close Position), TradingView webhook integration, ChartInk scanner integration, Fast Scalper (Rust/Tauri desktop app), Action Center for portfolio management, API Playground for testing.

**Market Data & Analytics:** Historify (DuckDB-powered, 1m/5m/15m/30m/1h/daily with computed weekly/monthly/quarterly/yearly, Parquet import support, TradingView charts), Option Greeks (Black-76 model via py_vollib with forward_price parameter), IV Smile visualization, Option Chain API (OI + Greeks + volume + bid/ask per strike), PnL Tracker (broker tradebook + 1-minute historical), Traffic & Latency Monitor (RTT tracking, API analytics, endpoint-level insights).

**AI & Automation:** MCP Server (15+ trading tools via SSE transport for Claude, Cursor, Windsurf), Telegram bot notifications, API Analyzer/Sandbox Mode (₹1 Cr virtual capital, realistic execution with SB-prefixed orders, auto square-off, Dracula theme indicator), WebSocket proxy server (3 modes: LTP, Quote, Depth across all 29 brokers).

**Security:** Argon2 password hashing, Fernet symmetric encryption for broker tokens, API rate limiting (configurable 10-60 req/min), IP ban system (auto-ban after 10 invalid API keys or 20 suspicious 404s), CSRF protection, CSP headers, audit logging, daily session expiry at 3:30 AM IST.

**Technical indicators library:** **80+ Numba-optimized indicators** across categories — trend (EMA, SMA, KAMA, SuperTrend, Ichimoku), momentum (RSI, MACD, CCI, Stochastic, Williams %R), volatility (Bollinger Bands, ATR, Keltner Channels), volume (OBV, VWAP, MFI, ADL, CMF, Relative Volume), and hybrid (Aroon, ADX). Custom indicator creation supported via Numba JIT + NumPy.

**SDKs:** Python (`openalgo` v1.0.45+), Node.js (`openalgo-node`), Rust (`openalgo` crate v1.0.5), Go (`openalgo-go`), Java (async WebSocket), .NET. All expose identical API surfaces: order management, market data, account operations, WebSocket streaming.

**Platform integrations:** TradingView (webhooks), AmiBroker (data plugin), MetaTrader 5, ChartInk (scanner → execution), n8n (workflow automation), Excel (VBA add-in with `oa_history` function), Google Sheets, Chrome extension (draggable LE/LX/SE/SX buttons).

---

## 5. Fully autonomous trading architecture

### The four-phase loop

The autonomous system operates on a continuous **perception → decision → execution → learning** cycle, orchestrated by OpenClaw as the agent brain and powered by a stack of specialized models.

**Perception layer** ingests data through three channels: Dhan WebSocket for real-time tick data (LTP, OI, market depth), OpenAlgo's option chain API for Greeks and IV surface, and computed features from the ML pipeline (regime indicators, PCR, max pain, technical indicators). LightGBM processes **50+ engineered features** — price returns at multiple horizons, Bollinger %B, RSI, VWAP deviation, OI change ratios, IV rank/percentile, PCR, days-to-expiry, time-of-day, and day-of-week cyclical encodings.

**Decision layer** operates in a hierarchical cascade. First, the regime detector classifies market state using VIX levels (<13 low, 13-18 normal, 18-25 high, >25 crisis) crossed with ADX trend strength (<20 range-bound, 20-40 moderate, >40 strong trend). This classification feeds the strategy selector — a decision matrix mapping regime × time-of-day → optimal strategy with position sizing. For complex decisions (unusual market conditions, conflicting signals), OpenClaw queries Ollama with structured prompts and parses JSON responses.

**Execution layer** routes orders through OpenAlgo's REST API with a 5-layer safety check at every stage. Orders flow through validation → risk check → broker API → fill monitoring → position reconciliation. The system respects **SEBI's 10 OPS limit** by queuing orders and rate-limiting to 8 orders/second with headroom.

**Learning layer** runs post-market: calculates P&L attribution per strategy, updates ChromaDB RAG knowledge base with trade outcomes, triggers LightGBM retraining on rolling 6-month windows, and writes learning summaries to OpenClaw's persistent memory for next-day context.

### Daily lifecycle automation

| Time (IST) | Action | Component |
|---|---|---|
| 3:00 AM | System health check, service restart, session expiry (OpenAlgo default) | Systemd timer + cron |
| 8:30 AM | Pre-market analysis: download previous day's NSE bhav copy, compute max pain, analyze FII/DII data | Python script → DuckDB |
| 9:00 AM | Dhan API login (2FA + OAuth), download pre-open OI data, update option chain | OpenAlgo broker login |
| 9:15 AM | WebSocket connects, ORB range establishment begins (no trading) | OpenAlgo WebSocket proxy |
| 9:30 AM | Regime detection runs, strategy deployed based on regime + VIX + PCR | OpenClaw → Ollama → OpenAlgo API |
| 10:00-11:30 AM | Active trading: straddle/strangle entries, scalping setups | Python strategies in OpenAlgo |
| 12:00-1:30 PM | Reduced activity (dead zone), position monitoring only | Watchdog process |
| 1:30-3:00 PM | Afternoon session: adjustments, theta harvesting | Strategy adjusters |
| 3:15 PM | Square off all intraday MIS positions | OpenAlgo `closeposition` API |
| 3:30 PM | Market close, WebSocket disconnect | OpenAlgo |
| 4:00 PM | Post-market: P&L calculation, trade logging, performance attribution | PnL Tracker + custom scripts |
| 5:00 PM | Data archival (append to Parquet/DuckDB), trigger nightly jobs | Cron + rsync |
| 10:00 PM | Overnight analysis: model retraining trigger, next-day preparation | LightGBM retrain + Ollama analysis |

### Five-layer safety architecture

**Layer 1 — Order validation:** Every order passes through price sanity checks (within ±5% of LTP), quantity limits (max lot size per order), symbol validation, and product type verification. Rejects malformed orders before they reach the broker. Implemented in OpenAlgo's order pipeline.

**Layer 2 — Position limits:** Maximum 5 simultaneous positions, maximum margin utilization capped at 60%, per-instrument exposure limits. Checks run against OpenAlgo's position tracker. Trigger: auto-reject new orders when limits breached.

**Layer 3 — Portfolio risk:** Daily P&L limit (3% of capital loss = pause trading), maximum drawdown (15% = kill all strategies), portfolio Greeks limits (net delta ±500 NIFTY points, net vega ≤1% of portfolio per VIX point). Trigger: close all positions and disable strategy execution.

**Layer 4 — System watchdog:** Systemd monitors all processes (OpenAlgo, OpenClaw, Ollama, nginx). Heartbeat check every 60 seconds — if any critical service is down for >3 minutes, trigger graceful position closure. Memory and CPU monitoring via btop/rocm-smi alerts.

**Layer 5 — External kill switch:** Telegram command `/killswitch` sent to the OpenAlgo Telegram bot immediately closes all positions and disables trading. Cockpit web UI provides manual override. The ER605's static IP can be temporarily blocked to cut all API access as a nuclear option.

### OpenClaw as the agent brain

OpenClaw's persistent memory system stores market context across sessions in structured Markdown files under `~/.openclaw/memory/`:

- `daily_context.md`: Today's regime, VIX level, key OI levels, active strategies, running P&L
- `strategy_performance.md`: Win rates, Sharpe ratios, and drawdown metrics per strategy over rolling 30/90/365 days
- `risk_state.md`: Current margin utilization, daily P&L, drawdown status, active positions
- `learning_log.md`: Post-trade analyses, pattern observations, strategy adaptation notes

The **heartbeat system** (every 30 minutes) checks `HEARTBEAT.md` for scheduled tasks: pre-market data download, position monitoring, adjustment triggers, and end-of-day procedures. Custom trading skills (SKILL.md files) define capabilities: `market_analysis.md` (query Ollama for regime assessment), `trade_execution.md` (call OpenAlgo REST API), `risk_management.md` (enforce limits), `portfolio_review.md` (generate performance summaries).

Decision flow: OpenClaw receives market signal → queries Ollama with structured prompt including full context from memory → Ollama returns JSON-formatted analysis → OpenClaw validates against risk limits → calls `POST http://openalgo:5000/api/v1/placeorder` → logs outcome to memory.

---

## 6. AI/ML models optimized for each GPU

### AMD RX 6600 XT (server, ROCm, 24/7 inference)

The primary model is **Qwen3 8B at Q4_K_M quantization** (~6-7GB VRAM), leaving headroom for KV cache at 8K context. This model excels at mathematical reasoning and structured analysis — ideal for trading signal interpretation. As a fast fallback, **Qwen3 4B** (~3-4GB) handles speed-critical tasks. The embedding model **nomic-embed-text** (~300MB) runs on CPU for the RAG pipeline.

ROCm setup requires `HSA_OVERRIDE_GFX_VERSION=10.3.0` and `ROCR_VISIBLE_DEVICES=0` as systemd environment overrides for the Ollama service. Q4_K_M quantization retains ~95% quality versus FP16 and is the sweet spot for 8GB systems. Maximum recommended context is 8K tokens — at 32K, KV cache alone consumes 4.5GB for an 8B model.

### NVIDIA RTX 5050 (laptop, CUDA, training)

Same inference models as above, but this GPU's primary value is **QLoRA fine-tuning via Unsloth**. Confirmed: 8B models can be fine-tuned on 8GB VRAM with Unsloth at batch_size=1, LoRA rank=16, gradient checkpointing enabled, and max_seq_length=2048. Training 1,000 examples for 3 epochs takes approximately **30-60 minutes**, producing adapter weights of ~100-200MB that deploy to the RX 6600 XT server via Ollama GGUF export.

Setup: PyTorch 2.7+ with CUDA 12.8 (`pip install torch --index-url https://download.pytorch.org/whl/cu128`), then `pip install unsloth`. Fine-tuning data should include trading Q&A pairs (~500-1000), market analysis examples (~300-500), strategy evaluations (~500), and historical trade outcomes with lessons (~1000+) in ChatML/ShareGPT format.

### Apple M4 MacBook (mobile, MLX/Ollama)

With **120 GB/s memory bandwidth** and 12-13GB usable for models, the M4 runs Qwen3 8B at **~30 tokens/sec** via MLX (20-30% faster than Ollama on Apple Silicon). 14B models at Q4 quantization are technically possible (~10-11GB) but leave little headroom. MLX provides the best performance; Ollama provides API consistency across all three machines. Use Ollama as primary for consistent API access.

### Time series foundation models

**IBM TTM (Tiny Time Mixer)** is the primary forecasting model — only **1M parameters**, runs on CPU, supports multivariate input with exogenous variables (perfect for OHLCV + indicators), and outperforms larger models by 4-40% on financial benchmarks. **Chronos-2** (120M parameters) serves as the ensemble partner, fitting easily on any GPU. Both are significantly better than generic LLMs for price prediction tasks.

**LightGBM** is the primary signal generation engine — faster than XGBoost with native categorical support and lower memory footprint. Feature engineering should include 50+ features across price (returns, moving averages, Bollinger %B), volume (OI ratios, VWAP deviation), volatility (IV rank, ATR), options-specific (PCR, max pain distance, Greeks aggregates), and temporal (day-of-week, hour, DTE) categories. Use **walk-forward validation with TimeSeriesSplit** — never random k-fold for time series.

### RAG pipeline

LlamaIndex + ChromaDB + Ollama with Qwen3 8B provides the trading knowledge base. ChromaDB stores persistent embeddings in `./trading_knowledge_db/`. Index strategy rules, market analysis notes, trade history with outcomes, risk management procedures, options knowledge, and regulatory requirements. Use nomic-embed-text for embeddings (~300MB, CPU-capable).

### Reinforcement learning

FinRL with Stable-Baselines3 **PPO** handles options position management. RL models are tiny (100K-500K parameters, <500MB VRAM) and train comfortably on CPU. State space: positions + Greeks + P&L + time-to-expiry + IV + VIX. Action space: hold, add, reduce, roll, hedge delta, close. Reward: risk-adjusted P&L. Train on the RTX 5050, deploy on CPU.

---

## 7. Historical data pipeline: 12-120 GB covers everything

### Dhan Rolling Option API (primary source)

The endpoint `POST https://api.dhan.co/v2/charts/rollingoption` accepts parameters including `exchangeSegment`, `securityId` (13=NIFTY, 25=BANKNIFTY), `instrument`, `expiryFlag` (WEEK/MONTH), `expiryCode` (1=near, 2=next, 3=far), `strike` (ATM, ATM±1 to ATM±10), `drvOptionType` (CALL/PUT), and `requiredData` array (open, high, low, close, volume, iv, oi, spot, strike).

The download strategy loops through 30-day windows across 5 years for each combination of underlying × expiry type × expiry code × strike offset × option type. For 4 indices, this requires approximately **60,000-100,000 API calls** — completable within 1-2 days given the 100K/day limit. An important limitation: data is **rolling (ATM-relative), not absolute-strike** — you cannot fetch "NIFTY 24000 CE 27-Mar-2025" specifically, only "ATM+2 CALL for near-month weekly."

### Upstox (secondary, contract-level)

Upstox's expired instruments API provides contract-level access to specific absolute strikes via `GET /v2/expired-instruments/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}`. It returns **OHLCV + OI but no IV** — IV must be calculated using `py_vollib_vectorized` with Black-Scholes (risk-free rate ~6.5% RBI repo rate). Use Upstox when backtesting strategies requiring specific absolute strike prices.

### Storage calculations

| Dataset | Rows (5 years) | Parquet compressed |
|---|---|---|
| NIFTY options (ATM±10, all expiries) | ~79M | ~800 MB |
| BANKNIFTY options | ~79M | ~800 MB |
| FINNIFTY + SENSEX | ~60M | ~800 MB |
| Stock F&O (50 stocks, ATM±3) | ~945M | ~9.6 GB |
| Index spot + futures | ~7.5M | ~50 MB |
| **Total (Dhan rolling)** | **~1.17B** | **~12 GB** |
| **Total (all strikes via Upstox)** | **~5-10B** | **~60 GB** |

### Tiered storage strategy

**512GB internal SSD (hot):** OS + applications (~100GB), active DuckDB database with last 6 months of minute data (~10GB), Python environments (~50GB). **1TB external SSD (warm):** Complete 5-year DuckDB for backtesting (~25-120GB), computed Greeks databases, strategy-specific datasets, working backtesting space. **5TB internal HDD (cold):** Raw JSON/CSV API downloads (~200-500GB), complete NSE bhav copy archive (11+ years), Parquet archive of all strikes, backup of DuckDB databases, 5-year audit logs (SEBI requirement).

### DuckDB integration

OpenAlgo's Historify stores data in `db/historify.duckdb` with tables for `market_data` (OHLCV candles), `watchlist`, `download_jobs`, `job_items`, and `symbol_metadata`. External Parquet files import directly: `INSERT INTO market_data SELECT * FROM read_parquet('/data/options/*.parquet')`. Partition Parquet files by underlying/year/month using Hive-style partitioning for optimal DuckDB predicate pushdown. Use **ZSTD compression** and sort by timestamp within each file.

---

## 8. Trading strategies: the complete playbook

### Intraday options selling (primary edge)

**Short straddle with rolling adjustments** is the flagship strategy, already implemented as an OpenAlgo sample. Sell ATM CE + PE at 10:00 AM, roll when underlying moves ±0.4% (NIFTY) or ±0.5% (BANKNIFTY) from reference spot, maximum 3 rolls per day, forced exit at 3:15 PM. Expected win rate: **65-75%** with 1:2.5 win/loss ratio.

**Short strangle with OI-based strike selection** sells at maximum Put OI strike (support) and maximum Call OI strike (resistance), targeting 15-25 delta on each side. Exit at 50-70% of premium collected. **Iron condor** uses 15-16 delta short strikes with 100-point wings (NIFTY weekly), adjusted when underlying breaches short strike. Expected win rate: **60-64%**.

### Scalping strategies

**VWAP bounce** (best 9:30-11:00 AM): long when price tests VWAP from above with bullish candle + volume confirmation, target 15-25 points on option premium. **ORB 15-minute** is the most popular among Indian intraday traders with **65-70% success rate** — mark first 15 minutes' high/low, enter on 5-minute candle close beyond range, SL at opposite side, target 1x range width. **CPR breakout** identifies narrow CPR days (<0.1% of price) for trending setups.

### 0DTE (Thursday expiry) strategies

Sell ATM straddle at 9:20-9:30 AM to capture maximum theta decay, target 60-80% of premium by 2:30 PM, close by 3:00 PM to avoid pin risk. Best time windows: 9:15-9:45 for momentum buying, 10:00-11:30 for straddle entry, and 2:00-3:00 for maximum theta harvesting. **The 12:00-1:30 PM "dead zone" should be avoided entirely.**

### Market regime detection and strategy selection

```
VIX < 13 AND ADX < 20 → Calendar spreads, diagonal spreads
VIX 13-18 AND ADX < 25 → Short straddle, short strangle, iron condor
VIX 13-18 AND ADX > 25 → Bull/bear credit spreads, directional debit spreads
VIX 18-25 AND ADX < 20 → Iron butterfly centered at expected pin
VIX 18-25 AND ADX > 25 → Hedged directional debit spreads with stop-loss
VIX > 25               → Long straddle/strangle (buyers) or wide iron condors (sellers)
```

### Position sizing framework

Use **Quarter Kelly** (25% of Kelly Criterion output) for options — full Kelly is too aggressive given estimation error. Never risk more than **3% of capital per trade**. Conservative daily loss limit: 2% of capital. Maximum drawdown kill switch: **15%** of capital triggers immediate closure of all positions and strategy suspension. Portfolio Greeks limits: net delta ±500 NIFTY points equivalent, net theta positive and capped at 0.5% of capital/day.

### Multi-timeframe indicator framework

Weekly chart identifies overall trend (200 EMA direction + ADX). Daily chart identifies setup (support/resistance, IV rank, OI levels). 1-hour chart confirms entry timing (RSI divergence, MACD crossover). 15-minute chart executes entry (VWAP + price action + volume confirmation). 5-minute chart manages position (trailing stop with Bollinger Bands).

**Best indicator combinations:** Options scalping uses RSI(14) + VWAP + Bollinger Bands(20,2) + SuperTrend(10,3). Options selling uses IV Rank + IV Percentile + OI levels + PCR + India VIX. Equity swing uses EMA(9/21) crossover + MACD(12/26/9) + RSI(14) + ADX(14).

---

## 9. Backtesting with real expired options data

VectorBT is the primary backtesting engine, integrated via OpenAlgo's backtesting skills (`npx skills add marketcalls/vectorbt-backtesting-skills`). It provides vectorized operations (NumPy + Numba) capable of **1M+ simulations in ~20 seconds**, walk-forward optimization via rolling splits, and multi-parameter grid optimization. QuantStats generates tearsheets with Sharpe, Sortino, Calmar ratios, max drawdown, profit factor, and complete trade analytics.

**The critical advantage is backtesting with real expired options data from Dhan** — not synthetic/reconstructed data that ignores volatility smile and skew dynamics. Download 5 years of actual minute-level options prices with IV and OI, import into DuckDB via Historify's Parquet import, and backtest on actual historical premiums.

**Anti-overfitting protocol:** Use rolling walk-forward validation (30 windows of 2-year in-sample, 180-day out-of-sample), require minimum 100 trades for statistical significance, verify parameter stability (profitable across a range of parameters, not just one point), run Monte Carlo simulation (10,000+ randomized trade sequences) to confirm metrics hold. A profitable strategy should show consistent Sharpe >1.0, max drawdown <15%, and profit factor >1.5 across both in-sample and out-of-sample periods.

---

## 10. SEBI compliance and the April 2026 deadline

### Regulatory framework

SEBI's master circular (SEBI/HO/MIRSD/MIRSD-PoD/P/2025/0000013, February 4, 2025) and NSE's implementation standards (NSE/INVG/67858, May 5, 2025) established the comprehensive framework for retail algorithmic trading, with **full enforcement on April 1, 2026**.

**The 10 OPS threshold** (Threshold Orders Per Second) is measured on the calendar clock second of the broker server. It includes all order placements, modifications, and cancellations within any one-second window. **Below 10 OPS, a retail investor developing their own algorithm does not need to register it** — a Generic Algo ID prescribed by the exchange is used. Orders are still tagged as algo orders for audit trail purposes.

### What the user must do

**Static IP is mandatory** for all API trading. The ER605's primary WAN with static IP satisfies this requirement. Provide 1 primary + 1 secondary (redundancy) static IP to the broker. IP updates are limited to once per calendar week.

**Daily API session logout** is compulsory — all sessions must be logged out before the next trading day. OpenAlgo's default session expiry at 3:30 AM IST handles this automatically.

**2FA + OAuth authentication** is mandatory for every API session login. OpenAlgo supports OAuth2 for Dhan and other brokers.

**5-year audit log retention** is required for all order and trade audit trails. Store on the 5TB HDD using xz-compressed logrotate with daily rotation (1825 days retention = 5 years). Estimated storage: even with extensive tick-by-tick logging, **under 200GB over 5 years** — the 5TB HDD is vastly sufficient.

**Kill switch capability** must exist. Implement via Telegram command, Cockpit web UI, and programmatic position closure API. Brokers can also kill specific Algo IDs remotely.

**Algo must be hosted on Indian servers.** The home-based trading server with a static Indian IP satisfies this requirement.

### ER605 network configuration

Configure WAN1 as Static IP (primary, for SEBI compliance), WAN/LAN1 as secondary WAN (failover). Enable Load Balancing → Link Backup with failover mode. Set Online Detection to Manual with 5-second ping intervals to 8.8.8.8 and broker server IPs. Create a VLAN (ID 10, subnet 192.168.10.0/24) for the trading server on a dedicated LAN port, with ACL rules blocking traffic from the general network VLAN.

### WireGuard VPN

Run WireGuard on the Ubuntu trading server (the ER605 does not natively support WireGuard). Configure as a 10.10.10.0/24 network with the server at 10.10.10.1, laptop at 10.10.10.2, MacBook at 10.10.10.3. Forward UDP 51820 on the ER605 from WAN to the server. Access OpenAlgo through the VPN tunnel at `http://10.10.10.1:5000` — never expose OpenAlgo directly to the public internet.

---

## 11. Development workflow: three AI tools in concert

**Claude Code** (terminal CLI) serves as the primary coding agent — use it on the trading server via SSH for writing strategies, debugging broker adapters, and refactoring the OpenAlgo codebase. Structure the `CLAUDE.md` file with project architecture, coding conventions, available APIs, and current sprint goals. Claude Cowork handles multi-file management across the monorepo. Claude Desktop with MCP integration connects directly to OpenAlgo's MCP server for natural language trade execution during development.

**Google Antigravity IDE** (VS Code fork with Gemini integration) excels at large codebase analysis with its **1M token context** — feed the entire OpenAlgo source for architecture reviews, dependency audits, and cross-module refactoring. Jules coding agent handles automated coding tasks like generating boilerplate broker adapters or writing test suites. Install on both Windows (Acer Nitro) and macOS (MacBook).

**Perplexity Pro** provides deep research for trading strategy literature, API documentation analysis, and real-time market research. Its API access enables integration into the trading pipeline for automated news sentiment analysis.

**Workflow pattern:** Perplexity researches strategy concepts and API docs → Claude Code implements the code → Gemini/Antigravity reviews the entire codebase for consistency → VectorBT backtests → deploy to Dhan Sandbox → paper trade → go live.

**Remote development:** VS Code Remote SSH from MacBook/laptop to the trading server provides full IDE capability over the VPN tunnel. Configure SSH with `LocalForward` for Cockpit (9090), Uptime Kuma (3001), and OpenAlgo (5000). Use tmux on the server for persistent terminal sessions that survive SSH disconnections.

---

## 12. Network monitoring and alerting

Deploy **Uptime Kuma** (Docker, port 3001) on the trading server to monitor OpenAlgo (HTTP), OpenClaw (WebSocket), Ollama (HTTP), nginx (HTTP), and external broker API endpoints (TCP ping). Configure Telegram notifications for downtime alerts. Use **Smokeping** for continuous latency monitoring to broker servers with historical graphs. Create a cron job that pings the primary WAN gateway every minute and sends a Telegram alert if failover activates.

Monitor the RX 6600 XT temperature with `rocm-smi --showtemp` logged every 10 minutes. The btop terminal monitor provides real-time CPU, RAM, disk, and network visualization. Cockpit on port 9090 provides web-based server management accessible from any device.

---

## 13. The 20-week roadmap from current state to full autonomy

### Phase 1: Foundation (Weeks 1-3)

**Week 1:** Install Ubuntu Server 24.04 LTS on the custom PC. Configure ROCm + Ollama with gfx1032 override. Set up Cockpit, Docker, nginx. Verify Ollama runs Qwen3 8B successfully. Configure ER605 with static IP WAN1 + failover WAN2. Set up WireGuard VPN. Configure VLAN for trading server. *Validation: Ollama inference working, VPN accessible from laptop and MacBook, Cockpit dashboard operational.*

**Week 2:** Install OpenAlgo v2 natively on the server, configure Dhan as primary broker, enable Dhan Sandbox. Test broker login, place test orders in sandbox mode. Install OpenClaw, verify integration with OpenAlgo REST API. Set up the monorepo with git subtrees for core repos (openalgo, openclaw, openalgo-mcp, historify, vectorbt-backtesting-skills). *Validation: OpenAlgo sandbox trades working, OpenClaw can call OpenAlgo API, monorepo building successfully.*

**Week 3:** Configure WSL2 on the Acer Nitro with CUDA 12.8 + PyTorch 2.7 + Unsloth. Install Antigravity IDE on Windows and macOS. Set up VS Code Remote SSH from both laptop and MacBook. Configure NUT for UPS monitoring. Set BIOS auto-restart after power loss. Create systemd services for all components. Set up Uptime Kuma monitoring. *Validation: Fine-tuning a test model on RTX 5050 works, remote development from MacBook operational, UPS graceful shutdown tested.*

### Phase 2: Data pipeline (Weeks 4-6)

**Week 4:** Build Dhan Rolling Option API download pipeline. Download NIFTY + BANKNIFTY 5-year expired options data (1-minute with IV + OI). Store as Parquet on 1TB external SSD. Import into DuckDB via Historify. *Validation: 5 years of NIFTY/BANKNIFTY options data queryable in DuckDB.*

**Week 5:** Download FINNIFTY + SENSEX + top 20 liquid stock options. Set up Upstox API for contract-level supplementary data. Download 11 years of NSE bhav copies via jugaad-data. Cross-validate OI data between sources. *Validation: Complete historical database covering all major indices and top stocks.*

**Week 6:** Build daily incremental data pipeline (nightly Dhan API pull → Parquet append → DuckDB refresh). Set up data validation checks. Configure IV calculation for Upstox data (py_vollib). Build real-time option chain aggregator using OpenQuest + QuestDB for live data. *Validation: Automated nightly data updates, real-time option chain streaming.*

### Phase 3: Backtesting and strategies (Weeks 7-9)

**Week 7:** Set up VectorBT backtesting framework with OpenAlgo skills. Implement top 3 strategies: short straddle with rolling adjustments, short strangle with OI-based strike selection, ORB 15-minute. Backtest all three on real expired options data. *Validation: All strategies backtested with >100 trades each, Sharpe >1.0 on in-sample.*

**Week 8:** Implement walk-forward optimization (30 rolling windows). Run Monte Carlo simulations. Implement iron condor and VWAP bounce strategies. Build market regime detector (VIX + ADX classification). Implement strategy selection matrix. *Validation: Walk-forward results consistent with in-sample, regime detector classifies historical data correctly.*

**Week 9:** Begin paper trading on Dhan Sandbox with top 2 strategies. Run automated daily lifecycle (pre-market analysis → strategy deployment → square-off). Monitor performance daily. Implement 5-layer safety architecture. *Validation: Paper trading running autonomously for 5 consecutive trading days without intervention.*

### Phase 4: AI/ML integration (Weeks 10-12)

**Week 10:** Build RAG pipeline (LlamaIndex + ChromaDB + Ollama Qwen3 8B). Index trading strategy documentation, risk rules, and historical analysis. Build LightGBM signal generation model with 50+ features. Train on 3 years of data, validate on 2 years. *Validation: RAG answers trading questions accurately, LightGBM AUC >0.55 on out-of-sample.*

**Week 11:** Integrate IBM TTM for time series forecasting. Deploy Chronos-2 as ensemble partner. Build market regime detection model combining VIX, ADX, PCR, and ML predictions. Integrate LightGBM signals into the strategy selection pipeline. *Validation: TTM forecasts show positive Spearman IC, combined signals improve backtest Sharpe.*

**Week 12:** Integrate OpenClaw as the autonomous agent brain. Configure persistent memory structure. Build custom trading skills (market_analysis, trade_execution, risk_management). Configure heartbeat system for scheduled tasks. Connect OpenClaw → Ollama → OpenAlgo decision pipeline. *Validation: OpenClaw autonomously executes a complete trading day on sandbox.*

### Phase 5: Testing and hardening (Weeks 13-15)

**Week 13:** Full autonomous paper trading with AI pipeline. OpenClaw manages daily lifecycle, regime detection, strategy selection, and risk management. All 5 safety layers active. Monitor for edge cases and errors. *Validation: 5 consecutive days of autonomous paper trading, all safety layers triggered and recovered correctly.*

**Week 14:** Error handling and resilience testing. Simulate WebSocket disconnection, broker API timeout, LLM inference timeout, network failover. Implement exponential backoff, broker failover (Dhan → Upstox), and rule-based fallback for LLM timeouts. *Validation: System handles all simulated failures gracefully without orphaned positions.*

**Week 15:** Performance optimization. Analyze paper trading results — which strategies work, which need adjustment. Tune LightGBM features based on feature importance (SHAP values). Optimize strategy parameters based on walk-forward results. SEBI compliance audit: static IP verified, audit logs complete, kill switch functional, session management correct. *Validation: Paper trading Sharpe >0.8 over 3 weeks, SEBI compliance checklist 100% complete.*

### Phase 6: Live deployment (Weeks 16-18)

**Week 16:** Go live with **minimal capital** (2-3 lots NIFTY). Run only the highest-confidence strategy (short straddle with rolling adjustments). Conservative risk parameters: 1% per trade, 2% daily loss limit. Monitor every trade manually while autonomous system runs. *Validation: 5 consecutive profitable trading days (or controlled losses within limits).*

**Week 17:** Gradually add second strategy (short strangle with OI selection). Increase capital to 5-7 lots. Enable automated position adjustments. Continue monitoring but reduce manual oversight. *Validation: Both strategies running simultaneously with positive P&L over the week.*

**Week 18:** Add scalping strategies (ORB, VWAP bounce) for complementary alpha. Enable full daily lifecycle automation. Set up comprehensive alerting via Telegram for all trades, adjustments, and safety triggers. *Validation: 3+ strategies running autonomously with minimal intervention needed.*

### Phase 7: Advanced capabilities (Weeks 19-20)

**Week 19:** Fine-tune Qwen3 8B on accumulated trading data using Unsloth QLoRA on the RTX 5050. Deploy fine-tuned model to RX 6600 XT server. Implement FinRL PPO agent for options position management. Train on historical data, validate on paper trading. *Validation: Fine-tuned model provides measurably better analysis, RL agent manages positions within risk limits.*

**Week 20:** Implement ML-based strategy auto-discovery — use pattern recognition on historical data to identify new edge opportunities. Build performance dashboard with Recharts/D3.js. Document complete system for future maintenance. Gradual capital scaling based on validated Sharpe and drawdown metrics. *Validation: System running fully autonomously with documented edge, clear monitoring, and SEBI compliance.*

### Priority ranking by expected alpha vs difficulty

| Priority | Component | Expected Alpha | Implementation Difficulty |
|---|---|---|---|
| 1 | Historical data pipeline + backtesting | Foundational | Medium |
| 2 | Short straddle with adjustments | High (proven edge) | Low |
| 3 | OI-based strike selection | High | Low |
| 4 | Market regime detection | Medium-High | Medium |
| 5 | LightGBM signal generation | Medium-High | Medium |
| 6 | 5-layer safety architecture | Risk reduction | Medium |
| 7 | RAG knowledge base | Compounding | Medium |
| 8 | 0DTE theta harvesting | Medium | Low |
| 9 | Time series forecasting (TTM) | Medium | Low |
| 10 | RL position management | Medium | High |
| 11 | LLM fine-tuning | Low-Medium | Medium |
| 12 | Strategy auto-discovery | Speculative High | Very High |

---

## Conclusion: what makes this blueprint different

This plan is executable because every recommendation maps to specific hardware the user owns, software already running, and broker accounts already active. **Dhan's unmatched expired options API** provides the historical data foundation that most retail traders lack — 5 years of minute-level options data with IV is typically available only through expensive institutional data vendors. The three-GPU setup (ROCm for inference, CUDA for training, Metal for mobile) creates a genuine edge in local AI capability without cloud costs. OpenAlgo's 29-broker abstraction layer means the entire strategy stack is broker-agnostic and can fail over instantly.

The most important insight from this research: **the fastest path to edge is not the AI pipeline — it's systematic options selling with proper risk management, backtested on real expired options data.** Short straddles with rolling adjustments produce consistent returns in normal VIX regimes. The AI/ML layer amplifies this edge through better regime detection and position management, but the base strategy works without it. Start simple, validate with real data, paper trade until confident, then go live with minimal capital. The autonomous AI layer is the destination, not the starting point.