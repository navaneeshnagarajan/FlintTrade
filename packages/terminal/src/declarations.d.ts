// Temporary module declarations for JSX files during incremental TSX migration.
// Remove each declaration as the corresponding file is migrated to .tsx in Phase 4.
//
// Batch 1 DONE (trading widgets) — declarations removed:
//   DashboardWidget, ScalperWidget, PositionsWidget, OrdersWidget,
//   HoldingsWidget, TradeBookWidget, OrderPadWidget
//
// Batch 2 DONE (analysis widgets + Chart component) — declarations removed:
//   ChartWidget, OptionChainWidget, OIChartWidget, StraddleWidget,
//   DepthWidget, GreeksWidget, Chart

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
