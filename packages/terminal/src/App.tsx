import { useState, useCallback, useEffect, lazy, Suspense } from "react";
import { DockviewReact } from "dockview-react";
import type { DockviewReadyEvent } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { useLayoutStore } from "@/stores/layoutStore";
import { useWsBridge } from "@/hooks/useWsBridge";
import useGlobalKeys from "@/hooks/useGlobalKeys";
import TopBar from "@/chrome/TopBar";
import TickerBar from "@/chrome/TickerBar";
import WidgetPicker from "@/chrome/WidgetPicker";
import ToolsDropdown from "@/chrome/ToolsDropdown";
import { widgetComponents } from "@/layout/widgetFactory";
import type { ToolId } from "@/types/widgets";

// Full-page tools (lazy loaded -- only fetched when opened)
const tools: Record<ToolId, React.LazyExoticComponent<React.ComponentType<{ onClose: () => void }>>> = {
  "settings": lazy(() => import("./tools/Settings/SettingsTool")),
  "backtest-lab": lazy(() => import("./tools/BacktestLab/BacktestLabTool")),
  "trade-journal": lazy(() => import("./tools/TradeJournal/TradeJournalTool")),
  "strategy-builder": lazy(() => import("./tools/StrategyBuilder/StrategyBuilderTool")),
  "pnl-dashboard": lazy(() => import("./tools/PnLDashboard/PnLDashboardTool")),
  "market-intelligence": lazy(() => import("./tools/MarketIntelligence/MarketIntelligenceTool")),
  "flow-builder": lazy(() => import("./tools/FlowBuilder/FlowBuilderTool")),
};

export default function App() {
  const [widgetPickerOpen, setWidgetPickerOpen] = useState(false);
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const [activeTool, setActiveTool] = useState<ToolId | null>(null);

  const setDockviewApi = useLayoutStore((s) => s.setDockviewApi);

  // Connect WebSocket bridge for live market data
  useWsBridge();

  // Global keyboard shortcuts (Esc, Ctrl+K, X=exit all, C=cancel all)
  useGlobalKeys({
    onEscape: useCallback(() => {
      if (activeTool) { setActiveTool(null); return; }
      if (widgetPickerOpen) { setWidgetPickerOpen(false); return; }
      if (toolsMenuOpen) { setToolsMenuOpen(false); return; }
    }, [activeTool, widgetPickerOpen, toolsMenuOpen]),
    onCommandPalette: useCallback(() => {
      // Future: open command palette (Ctrl+K)
    }, []),
  });

  const onDockviewReady = useCallback(
    (event: DockviewReadyEvent) => {
      setDockviewApi(event.api);
      const activeTabId = useLayoutStore.getState().activeTabId;
      const savedLayout = useLayoutStore.getState().getTabLayout(activeTabId);
      if (savedLayout) {
        try {
          event.api.fromJSON(savedLayout as any);
        } catch {
          event.api.addPanel({ id: "dashboard", component: "dashboard", title: "Dashboard" });
        }
      } else {
        event.api.addPanel({ id: "dashboard", component: "dashboard", title: "Dashboard" });
      }
    },
    [setDockviewApi]
  );

  // Auto-save layout on changes
  useEffect(() => {
    const api = useLayoutStore.getState().dockviewApi;
    if (!api) return;
    const disposable = api.onDidLayoutChange(() => {
      const activeTabId = useLayoutStore.getState().activeTabId;
      const layout = api.toJSON();
      useLayoutStore.getState().saveTabLayout(activeTabId, layout as unknown as Record<string, unknown>);
    });
    return () => disposable.dispose();
  }, []);

  const handleSelectTool = useCallback((toolId: ToolId) => {
    setActiveTool(toolId);
  }, []);

  const ToolComponent = activeTool ? tools[activeTool] : null;

  return (
    <div className="h-screen flex flex-col bg-surface-base text-text-primary overflow-hidden select-none">
      {/* Chrome Layer 1: Top Bar */}
      <TopBar
        onWidgetPicker={() => setWidgetPickerOpen(true)}
        onToolsMenu={() => setToolsMenuOpen(!toolsMenuOpen)}
      />

      {/* Chrome Layer 2: Ticker Bar */}
      <TickerBar />

      {/* Tools dropdown (absolute positioned) */}
      <ToolsDropdown
        isOpen={toolsMenuOpen}
        onClose={() => setToolsMenuOpen(false)}
        onSelectTool={handleSelectTool}
      />

      {/* Main content: Dockview canvas OR full-page tool */}
      {activeTool && ToolComponent ? (
        <div className="flex-1 overflow-auto">
          <Suspense
            fallback={
              <div className="flex items-center justify-center h-full text-text-secondary text-sm">
                Loading tool...
              </div>
            }
          >
            <ToolComponent onClose={() => setActiveTool(null)} />
          </Suspense>
        </div>
      ) : (
        <div className="flex-1 relative overflow-hidden">
          <DockviewReact
            className="dockview-theme-dark"
            onReady={onDockviewReady}
            components={widgetComponents}
          />
        </div>
      )}

      {/* Widget picker dialog */}
      <WidgetPicker
        isOpen={widgetPickerOpen}
        onClose={() => setWidgetPickerOpen(false)}
      />
    </div>
  );
}
