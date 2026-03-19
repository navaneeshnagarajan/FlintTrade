// Temporary module declarations for JSX files during incremental TSX migration.
// Remove each declaration as the corresponding file is migrated to .tsx in Phase 4.

// Widgets
declare module "@/widgets/trading/Dashboard/DashboardWidget";
declare module "@/widgets/trading/Scalper/ScalperWidget";
declare module "@/widgets/trading/Positions/PositionsWidget";
declare module "@/widgets/trading/Orders/OrdersWidget";
declare module "@/widgets/trading/Holdings/HoldingsWidget";
declare module "@/widgets/trading/TradeBook/TradeBookWidget";
declare module "@/widgets/trading/OrderPad/OrderPadWidget";
declare module "@/widgets/analysis/Chart/ChartWidget";
declare module "@/widgets/analysis/OptionChain/OptionChainWidget";
declare module "@/widgets/analysis/OIChart/OIChartWidget";
declare module "@/widgets/analysis/Straddle/StraddleWidget";
declare module "@/widgets/analysis/Depth/DepthWidget";
declare module "@/widgets/analysis/Greeks/GreeksWidget";
declare module "@/widgets/utility/Watchlist/WatchlistWidget";

// Tools
declare module "@/tools/Settings/SettingsTool";
declare module "@/tools/BacktestLab/BacktestLabTool";
declare module "@/tools/TradeJournal/TradeJournalTool";
declare module "@/tools/StrategyBuilder/StrategyBuilderTool";
declare module "@/tools/PnLDashboard/PnLDashboardTool";
declare module "@/tools/MarketIntelligence/MarketIntelligenceTool";
declare module "@/tools/FlowBuilder/FlowBuilderTool";

// Components
declare module "@/components/Chart";
