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
- Branch: main (pre-release, all commits to main)

## Widgets (30 TSX)
Trading (10): Dashboard, Scalper, OrderPad, Positions, Orders, Holdings, TradeBook, MTMMonitor, RiskPanel, ActionCenter
Analysis (14): Chart, OptionChain, OIChart, Straddle, Depth, Greeks, SectorMap, GEX, VolSurface, IVSmile, StraddlePnL, OIProfile, OrderFlow, DepthHeatmap
Utility (6): Watchlist, Calculator, News, Ticker, AIAdvisor, Scanner

## Tools (6)
Canvas overlays: P&L Dashboard, Market Intelligence, Trade Journal
Full-page tools: Backtest Lab, Flow Builder, Strategy Builder

## Routes (13)
/welcome, /explore, /setup, /settings, /trade, /invest, /learn, /lab, /automate, /ai, /ditto, /admin, 404

## Invest Tabs (16)
Portfolio overview, holdings, mutual funds, SIPs, net worth, tax harvesting, goals, dividends, fixed deposits, gold/silver, PPF/EPF, NPS, insurance, real estate, crypto, summary

## Tests
Vitest — 1,696 tests. Run: `npx vitest run`
