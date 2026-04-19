# FlintTrade Widgets

Every widget is a lazy-loaded Dockview panel registered in [`packages/terminal/src/layout/widgetFactory.tsx`](../../packages/terminal/src/layout/widgetFactory.tsx). Source directories live under `packages/terminal/src/widgets/{trading,analysis,utility}/`.

**Registry count (from `widgetFactory.tsx`):** 82 widgets + 1 alias (`chartgrid` reuses the `Chart` folder) = 83 entries.
**On-disk directories:** 22 under `trading/`, 38 under `analysis/`, 22 under `utility/` = **82 unique widget folders**.

Status column meanings:
- **working** — registered in `widgetCatalog`, wired to a hook, directory exists, uses real API/atom/store.
- **placeholder** — described as AI/external-only in code, or marked as scaffolded (none found by spot-checks at report time; the AI Advisor, Scanner, etc. all have real implementations).
- **broken** — not observed by this report; would require a runtime smoke test to assert.

API/state columns are from static import analysis of each `<Name>Widget.tsx` file header. A widget may transitively use other APIs not shown.

## Trading widgets (22)

| Widget | Purpose (from catalog) | APIs / WS | State |
|---|---|---|---|
| Dashboard | Overview of open positions, real-time P&L, and market status | Composite (positions/funds/orderbook via sub-hooks) | TanStack Query + Zustand |
| Scalper | One-click order entry panel optimised for intraday F&O scalping | `placeorder`, `quotes` | Jotai + TanStack Query |
| Positions | Live position book with MTM P&L, quantity, and average price | `positionbook` via `usePositions` | TanStack Query + Jotai (LTP merge) |
| Orders | Order book showing pending, executed, rejected orders | `orderbook`, `cancelorder`, `modifyorder` via `useOrders` | TanStack Query |
| Holdings | Long-term equity and mutual fund holdings | `holdings` via `useHoldings` | TanStack Query |
| TradeBook | Executed trade history for the current session | `tradebook` via `useTrades` | TanStack Query |
| OrderPad | Full-featured order entry form | `placeorder`, `placesmartorder`, `optionsorder` | react-hook-form + zod + TanStack Query |
| IntradayPnL | Intraday profit and loss chart updated tick by tick | `pnl/symbols`, Jotai LTP atoms | Jotai + TanStack Query |
| MTMMonitor | MTM monitor with target and stop-loss level alerts | Jotai LTP, `positionbook` | Jotai + Zustand (alerts) |
| RiskPanel | Real-time risk metrics (drawdown, margin, exposure) | `margin`, `funds`, `positionbook` | TanStack Query |
| ActionCenter | Emergency actions: exit all, cancel all, flatten book | `cancelallorder`, `closeposition` | TanStack Query + Zustand (confirm dialog) |
| PositionHeatMap | Heatmap of positions coloured by P&L | `positionbook` + Jotai LTP | Jotai |
| TradeCopier | Mirror trades across multiple accounts | FlintTrade backend `/ditto/*` | Zustand |
| PortfolioAllocation | Pie chart breakdown by sector/instrument | `holdings`, `positionbook` | TanStack Query |
| QuickTrade | Minimal order ticket | `placeorder` | react-hook-form |
| SessionStats | Key session stats: trades, win rate, turnover | `tradebook` | TanStack Query |
| RiskDashboard | Consolidated risk: Greeks, VaR, concentration | `multioptiongreeks`, `positionbook` | TanStack Query + Jotai |
| TradeLog | Annotated trade journal | FlintTrade backend trade log | Zustand |
| TradePerformance | Expectancy, Sharpe, streak analysis | `tradebook`, analytics backend | TanStack Query |
| StrategyMonitor | Live status of running automated strategies | FlintTrade backend `/engine/strategies/*` | TanStack Query |
| NetPosition | Aggregated net position across accounts | `positionbook` per-account | TanStack Query |
| OrderLadder | Ladder-style DOM for limit orders | `depth`, `placeorder`, `cancelorder` | Jotai + TanStack Query |

## Analysis widgets (38)

| Widget | Purpose | APIs / WS | State |
|---|---|---|---|
| Chart | Interactive candlestick chart with indicators | `history`, `chart` prefs, `intervals` | Zustand (prefs) + local |
| ChartGrid | 1×1, 1×2, 2×1, or 2×2 chart grid | same as Chart, replicated | Zustand |
| OptionChain | Live option chain with OI, volume, IV, Greeks | `optionchain`, `getMaxPain`, `placeorder`, `getInstruments`, `getOptionSymbol`, `getSymbol` | TanStack Query + custom `useOptionChainData` hook |
| OIChart | Open-interest-change chart across strikes | `optionchain` | TanStack Query |
| Straddle | Straddle/strangle builder with premium, breakeven, IV | `quotes`, `positionbook`, `optionchain` via services/api | TanStack Query + `useChartTheme` |
| Depth | Level-2 market depth top-5 / top-50 | `getDepth` + WebSocket mode 4 | TanStack Query fallback + WS subscription |
| Greeks | Position-level Greeks summary | `getPositionbook`, `getMultiOptionGreeks` | TanStack Query |
| SectorMap | Sector tree map showing intraday performance | FlintTrade backend `/screener/rrg`/`/screener/sector` | TanStack Query |
| GEX | Gamma Exposure by strike | FT backend `/ft-api/v1/gex` | TanStack Query |
| VolSurface | 3-D IV surface | FT backend `/ft-api/v1/volsurface` | TanStack Query |
| IVSmile | IV smile curve | FT backend `/ft-api/v1/ivsmile` | TanStack Query |
| StraddlePnL | Payoff diagram | FT backend `/ft-api/v1/straddlepnl` | TanStack Query |
| OIProfile | OI distribution profile | FT backend `/ft-api/v1/oiprofile` | TanStack Query |
| OrderFlow | Buy/sell order flow footprint | WebSocket ticks + inference | Jotai |
| DepthHeatmap | Time-series heatmap of depth | WebSocket mode 4 | Jotai |
| ThreePanel | Three synced chart panels | `history` × 3 | Zustand |
| OIHeatmap | OI changes across strikes & expiries | `optionchain`, `expiry` | TanStack Query |
| GreeksSurface | 3-D Greeks surface across strikes/DTE | `multioptiongreeks` | TanStack Query |
| PivotPoints | Classic/Camarilla/Woodie pivots | `history` | TanStack Query |
| OrderBookReplay | Historical order book replay | FT backend analytics | TanStack Query |
| MarketBreadth | A/D ratio, new highs/lows, breadth oscillators | NSE breadth via `/historical` backend | TanStack Query |
| VolatilityCone | IV vs historical percentiles | `history`, `iv_smile` | TanStack Query |
| HeatCalendar | Calendar heatmap of daily P&L/returns | `tradebook` / analytics backend | TanStack Query |
| VWAPBands | VWAP with std dev bands | `history` | TanStack Query |
| CorrelationPairs | Rolling correlation between pairs | `history` × N | TanStack Query |
| MultiTimeframe | Four charts, same instrument, different TFs | `history` × 4 | Zustand |
| PCRTrend | Put-Call Ratio trend line | `optionchain` history | TanStack Query |
| InstrumentCompare | % comparison for up to five instruments | `history` × N | TanStack Query |
| SpreadView | Spread/basis between two instruments | `quotes` × 2, `syntheticfuture` | TanStack Query |
| GreeksHeatmap | Aggregate Greeks heat map across portfolio | `multioptiongreeks` | TanStack Query |
| GapAnalysis | Historical gap statistics | `history` | TanStack Query |
| ImpliedMove | Expected move from ATM straddle | `optionchain`, `quotes` | TanStack Query |
| OptionsFlow | Unusual options activity scanner | FT backend `/screener/optionsflow` | TanStack Query |
| Microstructure | Tick microstructure (aggressor ratio, VPIN, …) | WebSocket ticks | Jotai |
| CorrelationMatrix | Full correlation matrix heatmap | `history` × N | TanStack Query |
| IVSkew | OTM put/call IV skew | `iv_smile` | TanStack Query |
| SectorPerformance | Bar chart ranking sectors | FT backend `/screener/sector` | TanStack Query |
| Footprint | Footprint chart with buy/sell volume, delta, POC | WebSocket ticks + local aggregation | Jotai |
| DOMHeatmap | Historical depth-of-market heatmap | WebSocket mode 4 tape | Jotai |

## Utility widgets (22)

| Widget | Purpose | APIs / WS | State |
|---|---|---|---|
| Watchlist | Customisable watchlist with live LTP | WebSocket subscription, `quotes` fallback | Jotai (`selectedSymbolAtom`, LTP atoms) + Zustand (persistence) |
| Calculator | Options payoff / break-even calculator | client-side only | local |
| News | Curated market news feed | FT backend `/ai/news` | TanStack Query |
| Ticker | Horizontal scrolling price ticker | WebSocket subscription | Jotai + Zustand (symbols) |
| AIAdvisor | AI chat trade assistant | FT backend `/ai/chat`, SSE/WS streaming | Zustand (`settingsStore`, `aiConversationStore`) |
| Scanner | Pre-market gap scanner | FT backend `/screener/scanner` | TanStack Query + TanStack Table |
| Alerts | Price / indicator alerts with Telegram | FT backend `/alerts/*` | TanStack Query + Zustand |
| Health | OpenAlgo connection, WS latency, API health | `ping`, FT backend `/health/*` | TanStack Query |
| FundingRate | Perpetual futures funding rates | FT backend crypto bridge | TanStack Query |
| CurrencyConverter | Live currency converter | `quotes` (CDS) / external | TanStack Query |
| EarningsCalendar | Upcoming earnings | FT backend `/historical/earnings` | TanStack Query |
| GlobalIndices | Global indices prices | `quotes` (global) | TanStack Query |
| StrategyTemplates | Library of option strategy templates | FT backend `/engine/templates` | TanStack Query |
| AuditTrail | SEBI-compliant immutable audit log | FT backend `/audit/*` | TanStack Query |
| EconomicCalendar | Macro event calendar | FT backend `/historical/economic` | TanStack Query |
| ProfitTarget | Position-aware target/stop calculator | `positionbook`, client-side | TanStack Query |
| ExpiryCountdown | Countdown to weekly/monthly expiry | `expiry` | TanStack Query |
| PositionSizing | Kelly / fixed-risk sizing calculator | `funds`, client-side | TanStack Query |
| MarketClock | Multi-timezone market clock | client-side (session definitions) | local |
| TradeIdea | AI-generated trade ideas | FT backend `/ai/signals` | TanStack Query |
| TickSpeed | Tick arrival rate gauge | WebSocket subscription | Jotai |
| MarketSummary | Breadth + FII/DII + sector rotation snapshot | FT backend `/screener/market-summary` | TanStack Query |

## Verification notes

- Mappings in the "APIs / WS" and "State" columns above were derived from **static imports** at the top of each `<Name>Widget.tsx` entry file and from the public OpenAlgo + FlintTrade backend endpoint tables in `CLAUDE.md`. Transitive usage via custom hooks (`usePositions`, `useOrders`, `useOptionChainData`, etc.) has been attributed to the top-level widget where the hook is called.
- No widget was invoked in a browser during this report. Runtime status ("working" vs "broken") is therefore inferred from: (a) presence of implementation, (b) successful terminal `npm run build` (which compiles every widget via `lazy()`), (c) absence of TODO/placeholder markers in the widget file.
- Some widgets (e.g. OrderFlow, Footprint, DOMHeatmap, Microstructure) depend on a live WebSocket tick stream from OpenAlgo; they compile and render shells without it, but their actual data display is UNKNOWN without a running broker session.
- "Status: working / placeholder / broken" is therefore a **best-effort static verdict**. Every widget above is annotated "working" unless the code explicitly marks itself as a placeholder — none did at report time.
