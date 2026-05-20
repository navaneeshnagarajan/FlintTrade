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

## Widgets (82 TSX)
Trading (22): under `src/widgets/trading/` — Dashboard, Scalper, OrderPad, Positions, Orders, Holdings, TradeBook, MTMMonitor, RiskPanel, ActionCenter, IntradayPnL, NetPosition, OrderLadder, PortfolioAllocation, PositionHeatMap, QuickTrade, RiskDashboard, SessionStats, StrategyMonitor, TradeCopier, TradeLog, TradePerformance.
Analysis (38): under `src/widgets/analysis/` — Chart, OptionChain, OIChart, Straddle, Depth, Greeks, SectorMap, GEX, VolSurface, IVSmile, StraddlePnL, OIProfile, OrderFlow, DepthHeatmap, CorrelationMatrix, CorrelationPairs, DOMHeatmap, Footprint, GapAnalysis, GreeksHeatmap, GreeksSurface, HeatCalendar, ImpliedMove, InstrumentCompare, IVSkew, MarketBreadth, Microstructure, MultiTimeframe, OIHeatmap, OptionsFlow, OrderBookReplay, PCRTrend, PivotPoints, SectorPerformance, SpreadView, ThreePanel, VolatilityCone, VWAPBands.
Utility (22): under `src/widgets/utility/` — Watchlist, Calculator, News, Ticker, AIAdvisor, Scanner, Alerts, AuditTrail, CurrencyConverter, EarningsCalendar, EconomicCalendar, ExpiryCountdown, FundingRate, GlobalIndices, Health, MarketClock, MarketSummary, PositionSizing, ProfitTarget, StrategyTemplates, TickSpeed, TradeIdea.

## Tools (7)
Under `src/tools/`: BacktestLab, FlowBuilder, MarketIntelligence, PnLDashboard, Settings, StrategyBuilder, TradeJournal.

## Routes (12 public + DEV `/admin` + 404)
/welcome, /explore, /setup, /setup-account, /settings, /home, /trade (with `/terminal` alias), /invest, /learn, /lab, /automate, /ai, /ditto. Plus DEV-only `/admin` and `*` 404 catch-all.

## Tests
Vitest — ~2,973 tests across 264 files. Run: `npx vitest run`. Verified 2026-05-19.
