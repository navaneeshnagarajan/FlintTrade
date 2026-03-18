# FlintTrade — Build Plan

> Living document. Claude Code reads this to know what to do next.
> Pick the first unchecked item under "Next", implement it, check it off.

## Completed

- [x] Monorepo structure (13 packages)
- [x] All 10 Python packages: source code + tests
- [x] All 3 React packages: initialized, terminal dashboard built
- [x] Terminal: professional dark theme, live OpenAlgo API, 8-module sidebar
- [x] Core: OpenAlgo client with 45+ endpoint wrappers
- [x] Core: Workspace config system (~/.flinttrade/workspace.json)
- [x] Core: FlintTradeConfig (two-tier: .env + workspace.json)
- [x] Engine: 5-layer safety system, order router, scheduler, strategy registry
- [x] Engine: EMACrossover strategy, per-exchange market hours
- [x] Data: SEBI audit logger (JSONL append-only), DuckDB storage, tick recorder
- [x] Historical: downloader, free NSE data, DuckDB pipeline, expiry manager
- [x] Screener: option chain, OI analysis, futures quadrant, Greeks, IV
- [x] Backtest-engine: event-driven simulator, 12 templates, optimizer, metrics
- [x] AI: LLM client, RAG pipeline, ML signals, news sentiment
- [x] Integration: TradingView webhooks, ChartInk, flow builder, alerter
- [x] Automation: cron scheduler, Telegram bot, OpenClaw bridge, post-market
- [x] Ditto: account manager, position mirroring, margin calc, trailing SL
- [x] Infrastructure: Makefile, setup.sh, start/stop/status scripts, systemd
- [x] Git submodules: openalgo, algomirror, openclaw
- [x] First sandbox trade (SBIN BUY 1 MIS via Dhan Sandbox)
- [x] README rewrite, full audit, versioning 0.1.0-alpha
- [x] CI: GitHub Actions (python-tests, node-tests, secrets-check, claude-review)
- [x] 670 tests passing

## In Progress

- [ ] Terminal: verify dashboard shows live data during market hours
- [ ] Terminal: .env needs to be created per-machine (not committed)

## Next — Priority Order

1. [ ] **Terminal Option Chain module (F3)**
   - Fetch from `/api/v1/optionchain` with symbol, exchange, expiry
   - Fetch expiry list from `/api/v1/expiry`
   - Display: strike grid with CE side (LTP, OI, IV, volume, change) and PE side
   - Highlight ATM strike, color ITM/OTM differently
   - Greeks display per strike from `/api/v1/optiongreeks`
   - PCR and max pain summary at top
   - Auto-refresh every 3 seconds during market hours

2. [ ] **Terminal Scalper module (F2)**
   - 3-panel layout: CE chart (left), Spot/Index chart (center), PE chart (right)
   - TradingView Lightweight Charts for all three
   - Strike selector dropdown that updates CE/PE charts
   - Quick order buttons: BUY CE, SELL CE, BUY PE, SELL PE
   - Keyboard shortcuts: Shift+Up=Buy, Shift+Down=Sell
   - Position display with P&L
   - Partial exit buttons: 25%, 50%, 75%, 100%

3. [ ] **Terminal Charts module (F4)**
   - TradingView Lightweight Charts
   - Symbol search with autocomplete from `/api/v1/search`
   - Interval selector (1m, 5m, 15m, 1h, 1d)
   - Fetch from `/api/v1/history`
   - Volume bars below price
   - Drawing tools (horizontal line, trend line)

4. [ ] **Terminal Screener module (F5)**
   - OI analysis: support/resistance from OI, OI change
   - Futures quadrant: long buildup, short buildup, short covering, long unwinding
   - PCR chart over time
   - Max pain visualization
   - IV skew chart
   - Fetch from: optionchain, quotes, depth endpoints

5. [ ] **Terminal Settings module (F8)**
   - Read and write `~/.flinttrade/workspace.json`
   - Storage path picker (fast data + archive)
   - Module enable/disable toggles
   - Theme selection
   - OpenAlgo connection test
   - LLM provider config

6. [ ] **WebSocket integration**
   - Replace REST polling with WebSocket live ticks
   - Subscribe to symbols, dispatch to components
   - Fall back to REST if WS disconnects

7. [ ] **Dashboard package (port 5174)**
   - Standalone portfolio overview
   - Reuse components from terminal dashboard module

8. [ ] **Backtest package (port 5175)**
   - Strategy selector, parameter config, date range
   - Results: equity curve, drawdown, trade log, metrics
   - Compare mode: side-by-side backtests

9. [ ] **OpenClaw trading skill**
   - Create `workspace/skills/openalgo/SKILL.md`
   - Full OpenAlgo API reference for the agent
   - Safety rules, common workflows

10. [ ] **First live strategy on Dhan Sandbox**
    - EMA crossover on NIFTY or BANKNIFTY
    - Uses engine package safety layers
    - Runs during market hours
    - Logs to audit system

## Future

- Docker deployment testing
- Windows PowerShell setup.ps1
- Multi-broker support via Ditto
- AI signals from LLM analysis
- Historical data from Dhan Rolling Option API (5yr expired options)
- OpenClaw cron: pre-market check, post-market summary, health monitor
- SEBI algo registration documentation
- ChromaDB RAG for trading knowledge base
- GitNexus codebase intelligence indexing
- Fine-tuning with Unsloth QLoRA on trading data

See `docs/references/REPOS.md` for the full repository knowledge base (120 entries)
See `RESTRUCTURE.md` for the complete platform restructuring blueprint
