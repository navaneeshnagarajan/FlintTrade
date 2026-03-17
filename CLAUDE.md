# FlintTrade — Project Context

> Single source of truth for any AI agent working on this repo.
> Read this file first. Then read PLAN.md to know what to do next.

## What This Is

Open-source modular trading platform for Indian markets built on OpenAlgo.
13 packages, monorepo, AGPL-3.0.
Repo: https://github.com/navaneeshnagarajan/FlintTrade

## Architecture

FlintTrade sits ON TOP of OpenAlgo. Never modifies it.

- **OpenAlgo** handles broker connections (30+ brokers), REST API on port 5000, WebSocket on port 8765
- **FlintTrade** handles everything else: terminal UI, strategies, backtesting, AI, data, screener, multi-account
- Three git submodules: `infra/openalgo`, `infra/algomirror`, `infra/openclaw`

```
FlintTrade (React + Python) ──── REST/WS ────→ OpenAlgo (Flask, port 5000) ──→ Broker API
```

## Configuration Architecture

Two-tier config. No exceptions.

| Layer | File | What goes here |
|---|---|---|
| Infrastructure | `.env` | `OPENALGO_HOST`, `OPENALGO_PORT`, `OPENALGO_API_KEY`, `OPENALGO_WS_PORT` |
| User preferences | `~/.flinttrade/workspace.json` | Storage paths, enabled modules, LLM config, Telegram, theme, SEBI settings |

- `.env.example` has ALL values blank. Only 4 variables.
- Broker credentials are configured in OpenAlgo, NOT FlintTrade.
- TOTP auto-login is NOT implemented. OpenAlgo handles broker authentication.
- Cross-platform workspace: `~/.flinttrade/` (Linux), `~/Library/Application Support/flinttrade/` (macOS), `%APPDATA%/flinttrade/` (Windows)

## Monorepo Structure

### Python packages (10)

| Package | Description |
|---|---|
| `core` | OpenAlgo API client, Workspace config, models, exceptions |
| `engine` | Strategy execution, 5-layer safety system, order routing |
| `data` | Tick capture, DuckDB storage, SEBI audit logs |
| `historical` | Historical OHLCV download, DuckDB/Parquet pipeline |
| `screener` | OI analysis, PCR, max pain, portfolio Greeks, IV |
| `backtest-engine` | Event-driven simulator, 12 strategy templates, optimizer |
| `ai` | LLM client, RAG pipeline, ML signals, news sentiment |
| `integration` | TradingView webhooks, ChartInk, visual flow builder |
| `automation` | Cron scheduler, Telegram bot, OpenClaw bridge, post-market |
| `ditto` | Multi-broker multi-account mirroring, margin calc, trailing SL |

### React packages (3)

| Package | Port | Description |
|---|---|---|
| `terminal` | 5173 | Trading terminal — scalper, option chain, charts, screener |
| `dashboard` | 5174 | Portfolio overview, P&L analytics |
| `backtest` | 5175 | Backtest configuration and results UI |

## Current State

- **Version:** 0.1.0-alpha
- **Tests:** 670 passing (pytest + vitest)
- **Terminal:** React 19 on port 5173, dashboard module with live OpenAlgo API, dark theme, 8-module sidebar (F1-F8)
- **Infrastructure:** Makefile, setup.sh, systemd templates, health check
- **Workspace:** Cross-platform config system, created on `make setup`
- **First trade:** Successfully placed through FlintTrade → OpenAlgo → Dhan Sandbox

## Decisions Made (do not revisit)

- No TOTP auto-login — OpenAlgo handles broker auth
- Storage via `workspace.json`, not hardcoded paths or `.env`
- `.env` has exactly 4 variables — nothing else
- Ports: OpenAlgo 5000, WS 8765, Terminal 5173, Dashboard 5174, Backtest 5175
- Dev on Nitro (Windows) / Mac, Ubuntu = deployment only
- `.env.example` values ALL BLANK
- No personal hostnames, IPs, or provider names in committed code
- FlintTrade (capital T) in display text, `flinttrade` in paths/packages
- Pre-release (v0.x): all commits to main, no PRs required

## OpenAlgo API Quick Reference

All POST unless marked GET. Body: `{ "apikey": "...", ...params }`.

### Orders (12 endpoints)
| Endpoint | Method | What |
|---|---|---|
| `placeorder` | POST | Place single order |
| `placesmartorder` | POST | Smart order with position sizing |
| `modifyorder` | POST | Modify pending order |
| `cancelorder` | POST | Cancel single order |
| `cancelallorder` | POST | Cancel all orders for strategy |
| `closeposition` | POST | Close all positions for strategy |
| `openposition` | POST | Get open position for strategy |
| `orderstatus` | POST | Check order status |
| `optionsorder` | POST | Place options order with strike calc |
| `optionsmultiorder` | POST | Multiple options legs |
| `basketorder` | POST | Batch multiple orders |
| `splitorder` | POST | Split large order into chunks |

### Accounts (9 endpoints)
| Endpoint | Method | What |
|---|---|---|
| `funds` | POST | Available balance, margin, collateral |
| `orderbook` | POST | Today's orders with statistics |
| `tradebook` | POST | Today's executed trades |
| `positionbook` | POST | Open positions with P&L |
| `holdings` | POST | Long-term holdings |
| `margin` | POST | Margin requirement for order |
| `ping` | **GET** | Connection check, returns broker name |
| `analyzer/status` | **GET** | Sandbox mode status |
| `analyzer/toggle` | POST | Toggle sandbox mode |

### Data (21 endpoints)
| Endpoint | Method | What |
|---|---|---|
| `quotes` | POST | LTP, OHLC, volume for single symbol |
| `multiquotes` | POST | Quotes for multiple symbols |
| `depth` | POST | Order book (5 or 50 level) |
| `history` | POST | Historical OHLCV data |
| `optionchain` | POST | Full option chain with Greeks |
| `optiongreeks` | POST | Greeks for single option |
| `multioptiongreeks` | POST | Greeks for multiple options |
| `optionsymbol` | POST | Resolve option symbol |
| `symbol` | POST | Symbol lookup |
| `search` | POST | Fuzzy symbol search |
| `expiry` | POST | Expiry dates for symbol |
| `intervals` | **GET** | Supported chart intervals |
| `syntheticfuture` | POST | Synthetic future price |
| `ticker` | POST | Subscribe to ticker |
| `instruments` | **GET** | Full instrument list |
| `gex` | POST | Gamma exposure |
| `iv_smile` | POST | IV smile curve |
| `max_pain` | POST | Max pain strike |
| `oi_profile` | POST | OI profile |
| `telegram` | POST | Send Telegram message |
| `health` | **GET** | System health check |

### Utilities (2 endpoints)
| Endpoint | Method | What |
|---|---|---|
| `holidays` | **GET** | Market holidays list |
| `timings` | **GET** | Exchange trading hours |

### Rate limits
- Orders: 10/sec
- Smart orders: 2/sec
- General API: 50/sec

### WebSocket (port 8765)
- Mode 1: LTP only
- Mode 2: Quote (LTP + bid/ask + volume + OI)
- Mode 3: Depth (full order book)
- Subscribe: `{ "action": "subscribe_ltp", "instruments": [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}] }`

## Code Standards

- **Python:** PEP 8, ruff linting, type hints, Google-style docstrings
- **React:** Functional components, hooks only, Tailwind CSS v4, lucide-react icons
- **Tests:** pytest with `--import-mode=importlib`, vitest for React
- **Git:** Conventional commits (`feat(pkg):`, `fix(pkg):`, `docs:`, `refactor(pkg):`)
- **Branch:** main only during pre-alpha (v0.x)

## How to Work on This Project

1. Read this file (CLAUDE.md)
2. Read PLAN.md — find the next unchecked task
3. Implement it
4. Run tests: `python -m pytest packages/*/tests/ tests/ -v --tb=short --import-mode=importlib`
5. Update PLAN.md (check off completed task)
6. Append to DEVLOG.md
7. Commit with conventional message
8. Push to origin main

## DEVLOG Format

```
## YYYY-MM-DD HH:MM IST | Machine | @username | IDE/Tool | AI Model/Agent | Branch | Summary
```

Machines: `nitro-dev` (Windows), `mac-dev` (macOS), `ubuntu-server` (production)

## Do NOT

- Modify files in `infra/openalgo/`, `infra/algomirror/`, `infra/openclaw/` (submodules)
- Hardcode credentials, IPs, hostnames, or personal values
- Use mock/placeholder data in the terminal — every number comes from API
- Commit `.env` files
- Use ports 3000/3001/3002 (reserved for other tools)
- Reference specific brokers in package code — OpenAlgo abstracts them
- Skip DEVLOG entries
- Add TOTP auto-login (OpenAlgo handles broker auth)
