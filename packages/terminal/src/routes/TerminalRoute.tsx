import { useState, useCallback, useEffect, lazy, Suspense } from "react";
import { DockviewReact } from "dockview-react";
import type { DockviewReadyEvent } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { useLayoutStore } from "@/stores/layoutStore";
import useGlobalKeys from "@/hooks/useGlobalKeys";
import WidgetPicker from "@/chrome/WidgetPicker";
import ToolsDropdown from "@/chrome/ToolsDropdown";
import PresetPicker from "@/chrome/PresetPicker";
import { widgetComponents } from "@/layout/widgetFactory";
import { applyPreset, DEFAULT_PRESET_ID } from "@/layout/workspacePresets";
import type { ToolId } from "@/types/widgets";

// Full-page tools (lazy loaded -- only fetched when opened)
const tools: Record<ToolId, React.LazyExoticComponent<React.ComponentType<{ onClose: () => void }>>> = {
  "settings": lazy(() => import("../tools/Settings/SettingsTool")),
  "backtest-lab": lazy(() => import("../tools/BacktestLab/BacktestLabTool")),
  "trade-journal": lazy(() => import("../tools/TradeJournal/TradeJournalTool")),
  "strategy-builder": lazy(() => import("../tools/StrategyBuilder/StrategyBuilderTool")),
  "pnl-dashboard": lazy(() => import("../tools/PnLDashboard/PnLDashboardTool")),
  "market-intelligence": lazy(() => import("../tools/MarketIntelligence/MarketIntelligenceTool")),
  "flow-builder": lazy(() => import("../tools/FlowBuilder/FlowBuilderTool")),
};

export default function TerminalRoute() {
  const [activeTool, setActiveTool] = useState<ToolId | null>(null);

  const setDockviewApi = useLayoutStore((s) => s.setDockviewApi);
  const widgetPickerOpen = useLayoutStore((s) => s.widgetPickerOpen);
  const setWidgetPickerOpen = useLayoutStore((s) => s.setWidgetPickerOpen);
  const toolsMenuOpen = useLayoutStore((s) => s.toolsMenuOpen);
  const setToolsMenuOpen = useLayoutStore((s) => s.setToolsMenuOpen);
  const presetPickerOpen = useLayoutStore((s) => s.presetPickerOpen);
  const setPresetPickerOpen = useLayoutStore((s) => s.setPresetPickerOpen);

  // Global keyboard shortcuts (Esc, Ctrl+K, X=exit all, C=cancel all)
  useGlobalKeys({
    onEscape: useCallback(() => {
      if (activeTool) { setActiveTool(null); return; }
      if (presetPickerOpen) { setPresetPickerOpen(false); return; }
      if (widgetPickerOpen) { setWidgetPickerOpen(false); return; }
      if (toolsMenuOpen) { setToolsMenuOpen(false); return; }
    }, [activeTool, presetPickerOpen, widgetPickerOpen, toolsMenuOpen, setPresetPickerOpen, setWidgetPickerOpen, setToolsMenuOpen]),
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
          // Restore the persisted layout for this workspace tab.
          // Cast through unknown because we store as Record<string,unknown> in Zustand.
          event.api.fromJSON(savedLayout as unknown as Parameters<typeof event.api.fromJSON>[0]);
        } catch {
          // Corrupted saved layout — fall back to the default preset
          applyPreset(event.api, DEFAULT_PRESET_ID);
        }
      } else {
        // No layout saved yet — apply the default "Market Watch" preset
        applyPreset(event.api, DEFAULT_PRESET_ID);
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
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden select-none">
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
            singleTabMode="fullwidth"
          />
        </div>
      )}

      {/* Widget picker dialog */}
      <WidgetPicker
        isOpen={widgetPickerOpen}
        onClose={() => setWidgetPickerOpen(false)}
      />

      {/* Preset picker dialog */}
      <PresetPicker
        isOpen={presetPickerOpen}
        onClose={() => setPresetPickerOpen(false)}
      />
    </div>
  );
}
