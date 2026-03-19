# terminal — Agent Instructions

Read `packages/terminal/CLAUDE.md` first. This is the React frontend.

## Key Facts
- Port: 5173 (Vite dev server)
- Framework: React 19 + TypeScript 5.x strict
- Layout: Dockview v5.1 (widget-composable, NOT fixed modules)
- Components: shadcn/ui + Radix (accessible, copy-paste ownership)
- State: Zustand 5 (UI) + Jotai (market data atoms) + TanStack Query 5 (REST cache)
- Charting: Lightweight Charts v5
- Data grids: Glide Data Grid (streaming) + TanStack Table v8 (static)
- Branch: main (pre-alpha, no PRs)

## Widgets (21 TSX)
Trading: Dashboard, Scalper, OrderPad, Positions, Orders, Holdings, TradeBook
Analysis: Chart, OptionChain, OIChart, Straddle, Depth, Greeks
Utility: Watchlist
New: SectorMap, Calculator, MTMMonitor, RiskPanel, NewsFeed, Ticker, AIAdvisor

## Tools (7, all functional)
Settings, TradeJournal, PnLDashboard, StrategyBuilder, BacktestLab, MarketIntelligence, FlowBuilder

## Routes
/terminal (trader), /setup (wizard), /invest (investor), /learn (beginner)

## Tests
Vitest — 26 tests passing. Run: `npx vitest run`
