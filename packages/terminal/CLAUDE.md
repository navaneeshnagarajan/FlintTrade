# FlintTrade — terminal

> Trading UI — widget-composable workspace with Dockview v5
> Port: 5173 | Branch: main (pre-release, no PRs)

## Architecture
- Single React app serving 3 personas via routes: /terminal, /invest, /learn, /setup
- Dockview v5 for widget-composable layout (floating, popout, tabs, serializable)
- 14 existing widgets + 7 planned
- 7 full-page tools (Settings functional, 6 stubs)

## Tech Stack
- TypeScript 5.9 (strict mode, no `any`)
- React 19 + Vite 6.4
- Tailwind CSS v4 with @tailwindcss/vite
- shadcn/ui (16+ components) — no raw HTML controls
- Dockview v5 (layout engine)
- Lightweight Charts v5 (financial charts)
- Glide Data Grid (canvas-rendered option chain)
- TanStack Table v8 (positions, orders, holdings)

## State Architecture
| Layer | Library | What |
|-------|---------|------|
| Real-time ticks | Jotai atoms | Per-instrument LTP/quote/depth via WebSocket |
| REST cache | TanStack Query v5 | Positions, orders, holdings, funds, option chain |
| App state | Zustand v5 | Connection, layout, settings, trading aggregates |
| Forms | react-hook-form + zod | Order entry, settings forms |

Boundary rule: data enters through ONE path only, never duplicated across stores.

## Widgets (14 existing)
| Category | Widget | Status |
|----------|--------|--------|
| Trading | Dashboard, Scalper, Positions, Orders, Holdings, TradeBook, OrderPad | Built (JSX, migrating to TSX) |
| Analysis | Chart, OptionChain, OIChart, Straddle, Depth, Greeks | Built (JSX, migrating to TSX) |
| Utility | Watchlist | Built (JSX, migrating to TSX) |

## Widgets (7 planned)
SectorMap, NewsFeed, Calculator, Ticker, MTMMonitor, RiskPanel, AIAdvisor

## Tools (7)
Settings (functional), BacktestLab, TradeJournal, StrategyBuilder, PnLDashboard, MarketIntelligence, FlowBuilder (6 stubs)

## Absorbs (from cloned repos)
| Repo | What | Target |
|------|------|--------|
| openalgo-flow | 54-node flow builder | FlowBuilder tool |
| openalgo-chart | SectorHeatmap, Calculator, Alerts | SectorMap, Calculator widgets |
| etftracker | 10 React dashboards | /invest route + MarketIntelligence |
| trading-journal | Trade journal with analytics | TradeJournal tool |
| openalgo-portfoliogreeks | Greeks calculator | Greeks widget enhancement |
| fastscalper-tauri | Rust scalper UI patterns | Scalper widget |
| openalgo-pinets | PineTS indicators | Chart indicator overlays |

## Multi-exchange support
- 10 exchange codes: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, NSE_INDEX, BSE_INDEX
- MCX different hours (9:00-23:55), lot sizes per commodity
- CDS decimal strikes (USDINR 85.50)
- Crypto (Delta Exchange): 24/7, fractional lots, INR settlement

## Theme (locked)
- Background: #0a0a0f, Cards: #12121a, Borders: #1e1e2e
- Inter for UI, JetBrains Mono for numbers
- shadcn/ui dark theme with CSS variables
- Dockview dark theme overrides

## Rules
- TypeScript strict — no `any` types
- shadcn/ui components — no raw HTML controls
- Every widget is a Dockview panel
- Absorb from repos before writing new code
- No mock/placeholder/fake data
- Test with Playwright after UI changes
