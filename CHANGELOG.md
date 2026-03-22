# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- SEBI compliance doc rewritten with full circular reference (SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013), implementation timeline, compliance matrix, White Box classification
- README SEBI section updated with circular link, Section I.c personal use position, full enforcement date (April 1, 2026)
- 50 internal dev docs removed from public repo (moved to .local/)
- docs/REFERENCES.md added (public contributor reference)
- Test counts and package counts corrected across all docs

## [0.1.0-alpha] — 2026-03-21

Feature-complete alpha release. 13 packages, 1,021 tests, 7 routes, 21 widgets, full-stack wiring.

### Added — UI Foundation
- Geist font (headings) + Inter (body) + JetBrains Mono (data) — 3-tier font system
- 60+ design tokens (surfaces, borders, text, trading semantics)
- 5 built-in themes: Midnight, Obsidian, Terminal Green, Ocean Blue, Light
- SVG Logo component (LogoIcon, LogoWordmark, LogoFull)
- Density modes (comfortable/compact, auto-detect on small screens)

### Added — Routes & Navigation
- 7 app routes: /learn, /invest, /trade, /lab, /automate, /ai, /settings
- Cinematic /welcome screen with pillar cards and theme switcher
- /explore demo mode with sample data previews (no broker needed)
- /setup onboarding wizard with persona x interest matrix
- Global route tabs in TopBar (Learn · Invest · Trade · Lab · Automate · AI)
- 6 workspace presets: Scalper Zone, Options Desk, Market Watch, Analysis, Risk Monitor, Investor View

### Added — Full-Stack Wiring
- 100% OpenAlgo API coverage (45+ endpoints wired to UI)
- 20 FlintTrade backend endpoints (backtest, signals, sentiment, RAG, cron, audit, safety, webhooks)
- ftApi.ts TypeScript client for FlintTrade Python backend
- Market Intelligence: 4 new tabs (GEX, IV Smile, Max Pain, OI Profile)
- Synthetic Future in OptionChain header, Margin in OrderPad
- Market status badge in TopBar, holiday-aware DailyWelcome
- REST ticker fallback when WebSocket disconnects
- AI Advisor embedded in /ai Chat section with streaming + MCP

### Added — UI Libraries
- Tremor (dashboard charts, KPI cards, sparklines, tracker)
- Magic UI (AnimatedCounter, ShimmerButton, Particles, BlurFade)
- Aceternity UI (HoverCard spotlight, TextGenerateEffect, Meteors)

### Added — Infrastructure
- ErrorBoundary wrapping entire app
- 404 catch-all route (NotFoundRoute)
- connectionStore persisted to localStorage
- Mobile/small screen warning overlay
- prefers-reduced-motion media query (WCAG 2.3.3)
- Semantic landmarks (<header>, <main>, <nav>), skip-to-content link
- ARIA roles on route tabs, sidebar navigation, icon buttons

### Fixed
- 80+ hardcoded palette colors → design tokens (text-profit/text-loss/text-warning)
- isMarketHours() deduplicated to lib/market.ts, polling now dynamic
- Dockview: slim tabs (28px), singleTabMode, hidden close buttons
- window.prompt/confirm → inline rename/delete UI
- TOOLS/WIDGETS buttons hidden on non-trade routes
- Sidebar border-l-2 jump fixed (transparent border on inactive)
- Light theme Dockview CSS uses var() tokens
- Setup wizard presets mapped to real workspace presets
- Empty Dockview state shows Add Widgets / Choose Template overlay
- DailyWelcome suggestions now clickable
- Removed unused deps (lodash, oakscriptjs)
- docker-compose: removed deleted packages, fixed ports

### Tests
- Python: 985 passed, 3 skipped
- Vitest: 36 passed (10 new ticker fallback tests)
- TypeScript: 0 errors (strict mode)
- Build: clean

## [0.0.1-dev] — 2026-03-14

### Added — Core
- async OpenAlgo client — 45+ endpoints, rate limiting (10 OPS orders,
  2 OPS smart, 50 OPS general), exponential backoff retry
- Pydantic models — Order, Position, Quote, Fund, OptionGreek, etc.
- Settings.from_env(), exceptions hierarchy
- FlintTradeApp entry point — wires all 12 packages into single startup

### Added — Engine
- 5-layer SafetySystem (OrderValidation, PositionLimits, PortfolioRisk,
  DailyPnL, KillSwitch)
- Per-exchange market hours (NFO/BFO 15:30, CDS 17:00, MCX 23:30, DELTA 24/7)
- OrderRouter wired to OpenAlgoClient + AuditLogger
- StrategyRunner + StrategyScheduler — async tick loop, deploy freeze guard
- EMACrossover — first concrete strategy with position reversal

### Added — Data & Historical
- SEBI audit trail (JSONL append-only, gzip rotation, 5-year retention)
- DuckDB storage — ticks, trades, daily summaries
- Multi-source downloader, free NSE data, DuckDB pipeline, expiry manager

### Added — Screener & Analysis
- Option chain, OI spurt, futures quadrant, portfolio Greeks, IV analysis

### Added — Backtest
- Event-driven simulator, walk-forward optimizer, 12 strategy templates
- Monte Carlo analysis, performance metrics (Sharpe, Sortino, Calmar, VaR)
- React backtest UI — config panel, results, equity curves, compare mode

### Added — AI & Integration
- LLM client (LM Studio, Ollama, Anthropic, OpenAI), RAG, ML signals
- News sentiment, MCP bridge, stock advisor
- TradingView webhooks, ChartInk, visual flow builder, alerter

### Added — Automation & Ditto
- Cron manager (5 jobs), Telegram bot with /kill switch
- Position mirroring, margin-aware allocation, trailing SL, risk manager

### Added — Frontend
- terminal: Dockview widget-composable trading terminal — 14 widgets (TSX),
  7 tools, TypeScript strict, shadcn/ui, Zustand+Jotai+TanStack Query

### Added — Infrastructure
- Docker support — docker-compose.yml for Windows/macOS/Linux/Raspberry Pi
- Cross-platform setup guides (docs/setup/)
- systemd service file, production deployment scripts
- Feature flags — ENABLE_BACKTEST, ENABLE_AI

## [0.0.1-dev] — 2026-03-14

### Added
- Monorepo — 12 packages with per-package CLAUDE.md + AGENTS.md
- CI/CD — GitHub Actions (pytest, ruff, secrets check)
- SEBI compliance framework — rate limits, kill switch architecture, audit
- Infrastructure — nginx, systemd, WireGuard, fail2ban, deploy scripts
- Git-native bug tracking system
- Documentation — OpenAlgo API reference, tools guide, machine configs
