import { useState, useRef, useCallback, useEffect, lazy, Suspense } from "react";
import { Model } from "flexlayout-react";
// DataConnector removed in v2 — WebSocket bridge is now useWsBridge hook
import TopBar from "./chrome/TopBar";
import TickerBar from "./chrome/TickerBar";
import WidgetPicker from "./chrome/WidgetPicker";
import ToolsDropdown from "./chrome/ToolsDropdown";
import LayoutManager from "./layout/LayoutManager";
import {
  loadLayout, saveLayout, getAllLayouts,
  getActiveLayoutId, setActiveLayoutId, generateLayoutId,
} from "./layout/layoutStore";
import minimalPreset from "./layout/presets/minimal.json";
import useGlobalKeys from "./hooks/useGlobalKeys";

// Full-page tools (lazy loaded — only fetched when opened)
const tools = {
  "settings": lazy(() => import("./tools/Settings/SettingsTool")),
  "backtest-lab": lazy(() => import("./tools/BacktestLab/BacktestLabTool")),
  "trade-journal": lazy(() => import("./tools/TradeJournal/TradeJournalTool")),
  "strategy-builder": lazy(() => import("./tools/StrategyBuilder/StrategyBuilderTool")),
  "pnl-dashboard": lazy(() => import("./tools/PnLDashboard/PnLDashboardTool")),
  "market-intelligence": lazy(() => import("./tools/MarketIntelligence/MarketIntelligenceTool")),
  "flow-builder": lazy(() => import("./tools/FlowBuilder/FlowBuilderTool")),
};

function initLayoutTabs() {
  const saved = getAllLayouts();
  const entries = Object.values(saved);
  if (entries.length > 0) {
    return entries.map((e) => ({ id: e.id, name: e.name }));
  }
  const id = generateLayoutId();
  saveLayout(id, "Workspace", minimalPreset);
  return [{ id, name: "Workspace" }];
}

function initModel(activeId) {
  const saved = loadLayout(activeId);
  try {
    return Model.fromJson(saved || minimalPreset);
  } catch {
    return Model.fromJson(minimalPreset);
  }
}

export default function App() {
  // Layout state
  const [layoutTabs, setLayoutTabs] = useState(initLayoutTabs);
  const [activeTab, setActiveTab] = useState(() => getActiveLayoutId() || layoutTabs[0]?.id);
  const [model, setModel] = useState(() => initModel(activeTab));

  // UI state
  const [widgetPickerOpen, setWidgetPickerOpen] = useState(false);
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const [activeTool, setActiveTool] = useState(null);

  // FlexLayout ref for adding widgets
  const layoutRef = useRef(null);

  // Save layout whenever it changes
  const handleModelChange = useCallback((newModel) => {
    setModel(newModel);
    const tab = layoutTabs.find((t) => t.id === activeTab);
    if (tab) {
      saveLayout(activeTab, tab.name, newModel.toJson());
    }
  }, [activeTab, layoutTabs]);

  // Switch between layout tabs
  const handleTabSelect = useCallback((id) => {
    // Save current layout first
    const currentTab = layoutTabs.find((t) => t.id === activeTab);
    if (currentTab && model) {
      saveLayout(activeTab, currentTab.name, model.toJson());
    }

    setActiveTab(id);
    setActiveLayoutId(id);
    const saved = loadLayout(id);
    try {
      setModel(Model.fromJson(saved || minimalPreset));
    } catch {
      setModel(Model.fromJson(minimalPreset));
    }
    setActiveTool(null);
  }, [activeTab, layoutTabs, model]);

  // Create new layout
  const handleNewLayout = useCallback(() => {
    const id = generateLayoutId();
    const name = `Layout ${layoutTabs.length + 1}`;
    setLayoutTabs((prev) => [...prev, { id, name }]);
    saveLayout(id, name, minimalPreset);
    setActiveTab(id);
    setActiveLayoutId(id);
    setModel(Model.fromJson(minimalPreset));
    setActiveTool(null);
  }, [layoutTabs]);

  // Add widget from picker
  const handleAddWidget = useCallback((componentId, name) => {
    if (layoutRef.current) {
      layoutRef.current.addWidget(componentId, name);
    }
  }, []);

  // Open full-page tool
  const handleSelectTool = useCallback((toolId) => {
    setActiveTool(toolId);
  }, []);

  // DataConnector removed in v2 — WS bridge now handled by useWsBridge hook

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

  const ToolComponent = activeTool ? tools[activeTool] : null;

  return (
    <div className="h-screen flex flex-col bg-surface-base text-text-primary overflow-hidden select-none">
      {/* Chrome Layer 1: Top Bar */}
      <TopBar
        layoutTabs={layoutTabs}
        activeTab={activeTab}
        onTabSelect={handleTabSelect}
        onNewLayout={handleNewLayout}
        onWidgetPicker={() => setWidgetPickerOpen(true)}
        onToolsMenu={() => setToolsMenuOpen(!toolsMenuOpen)}
      />

      {/* Chrome Layer 1: Ticker Bar */}
      <TickerBar />

      {/* Tools dropdown (absolute positioned) */}
      <ToolsDropdown
        isOpen={toolsMenuOpen}
        onClose={() => setToolsMenuOpen(false)}
        onSelectTool={handleSelectTool}
      />

      {/* Main content: FlexLayout canvas OR full-page tool */}
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
        <LayoutManager
          ref={layoutRef}
          model={model}
          onModelChange={handleModelChange}
        />
      )}

      {/* Widget picker popup */}
      <WidgetPicker
        isOpen={widgetPickerOpen}
        onClose={() => setWidgetPickerOpen(false)}
        onAddWidget={handleAddWidget}
      />
    </div>
  );
}
