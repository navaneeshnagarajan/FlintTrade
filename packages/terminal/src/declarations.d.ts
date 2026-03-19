// Temporary module declarations for JSX files during incremental TSX migration.
// Remove each declaration as the corresponding file is migrated to .tsx in Phase 4.
//
// Batch 1 DONE (trading widgets) — declarations removed:
//   DashboardWidget, ScalperWidget, PositionsWidget, OrdersWidget,
//   HoldingsWidget, TradeBookWidget, OrderPadWidget

// Widgets — analysis (Batch 2)
declare module "@/widgets/analysis/Chart/ChartWidget";
declare module "@/widgets/analysis/OptionChain/OptionChainWidget";
declare module "@/widgets/analysis/OIChart/OIChartWidget";
declare module "@/widgets/analysis/Straddle/StraddleWidget";
declare module "@/widgets/analysis/Depth/DepthWidget";
declare module "@/widgets/analysis/Greeks/GreeksWidget";

// Widgets — utility (Batch 2)
declare module "@/widgets/utility/Watchlist/WatchlistWidget";

// Tools (Batch 3)
declare module "@/tools/Settings/SettingsTool";
declare module "@/tools/BacktestLab/BacktestLabTool";
declare module "@/tools/TradeJournal/TradeJournalTool";
declare module "@/tools/StrategyBuilder/StrategyBuilderTool";
declare module "@/tools/PnLDashboard/PnLDashboardTool";
declare module "@/tools/MarketIntelligence/MarketIntelligenceTool";
declare module "@/tools/FlowBuilder/FlowBuilderTool";

// Components still in JSX
declare module "@/components/Chart";

// JS hooks awaiting TSX migration
declare module "@/hooks/useWebSocket" {
  import type { WsInstrument, WsTick } from "@/types/api";
  type TickMap = Record<string, WsTick>;
  function useWebSocket(
    instruments: WsInstrument[],
    mode: "ltp" | "quote" | "depth",
  ): { ticks: TickMap; connected: boolean };
  export default useWebSocket;
}
