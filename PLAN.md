# FlintTrade — Build Plan

> Living document. Claude Code reads this to know what to do next.
> Pick the first unchecked item under "Next", implement it, check it off.

## Completed

- [x] Monorepo structure (13 packages with src/, tests/, CLAUDE.md, AGENTS.md)
- [x] Core: async OpenAlgo client with 45+ endpoint wrappers, rate limiting, retry
- [x] Core: Pydantic models (Order, Position, Quote, Fund, OptionGreek, etc.)
- [x] Core: Workspace config system (~/.flinttrade/workspace.json)
- [x] Core: FlintTradeConfig (two-tier: .env + workspace.json)
- [x] Engine: 5-layer safety system, order router, strategy scheduler
- [x] Engine: EMACrossover strategy, per-exchange market hours
- [x] Data: SEBI audit logger (JSONL append-only), DuckDB storage, tick recorder
- [x] Historical: downloader, free NSE data, DuckDB pipeline, expiry manager
- [x] Screener: option chain, OI analysis, futures quadrant, Greeks, IV
- [x] Backtest-engine: event-driven simulator, 12 templates, optimizer, metrics
- [x] AI: LLM client, RAG pipeline, ML signals, news sentiment
- [x] Integration: TradingView webhooks, ChartInk, flow builder
- [x] Automation: cron scheduler, Telegram bot, OpenClaw bridge, post-market
- [x] Ditto: account manager, position mirroring, margin calc, trailing SL
- [x] Terminal: React app on port 5173, 8-module sidebar (F1-F8)
- [x] Terminal: dashboard module with live index quotes, funds, positions, orders
- [x] Dashboard: React app skeleton on port 5174
- [x] Backtest: React app skeleton on port 5175
- [x] Infrastructure: Makefile, setup.sh, systemd, health-check, deploy scripts
- [x] .env trimmed to 4 vars, workspace.json for user prefs
- [x] TOTP removed (OpenAlgo handles broker auth)
- [x] README rewritten for open-source standards
- [x] Versioning fixed (0.1.0-alpha)
- [x] CI: GitHub Actions (python-tests, node-tests, secrets-check, claude-review)
- [x] First sandbox trade through FlintTrade → OpenAlgo → Dhan
- [x] 670 tests passing

## In Progress

- [ ] Terminal UI redesign — research real broker platforms (OiPulse, 1Cliq, Dhan, FYERS, INDmoney) for design patterns
- [ ] Clone OpenAlgo into infra/openalgo/ to read actual API routes and response formats

## Next (Priority Order)

1. [ ] Terminal: Design system — screenshot real brokers, establish component library, color palette, layout grid
2. [ ] Terminal: Dashboard module rewrite — professional design, real data, exchange-aware market hours
3. [ ] Terminal: Option Chain module (F3) — fetch optionchain API, strikes with CE/PE LTP, OI, IV, Greeks, max pain, PCR
4. [ ] Terminal: Scalper module (F2) — 3-chart layout (CE/Spot/PE), one-click orders, keyboard shortcuts, SL/target
5. [ ] Terminal: Charts module (F4) — TradingView Lightweight Charts, history API, multiple timeframes
6. [ ] Terminal: Screener module (F5) — OI analysis, futures quadrant, PCR, max pain, IV smile
7. [ ] Terminal: Settings module (F8) — workspace.json editor, connection status, risk limits
8. [ ] Terminal: WebSocket live ticks replacing REST polling
9. [ ] Terminal: Error boundaries, toast notifications, request validation
10. [ ] Dashboard package (port 5174): separate portfolio overview app
11. [ ] Backtest package (port 5175): UI for backtest config and results
12. [ ] OpenClaw skill for OpenAlgo natural language trading
13. [ ] First strategy running live on Dhan Sandbox

## Future

- Docker deployment testing
- Windows PowerShell setup.ps1
- Multi-broker via Ditto package
- AI signals integration (LM Studio + ChromaDB RAG)
- Historical data from Dhan Rolling Option API
- OpenClaw cron jobs (autonomous trading)
- SEBI compliance documentation
- GitNexus code indexing
- Tauri 2.0 desktop wrapper

## Machine Roles

| Machine | Role | Does | Does NOT |
|---|---|---|---|
| **Nitro** (Windows) | Primary dev | Write code, run tests, push | Start OpenAlgo, run trading |
| **Mac** (macOS) | Secondary dev | Write code, run tests, push | Start OpenAlgo, run trading |
| **Ubuntu** (Linux) | Server | Pull, verify, run OpenAlgo, trade | Write new features |
