import { useState, useCallback, useEffect, lazy, Suspense } from "react";
import { DockviewReact } from "dockview-react";
import type { DockviewReadyEvent } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { LayoutGrid, Layers } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLayoutStore } from "@/stores/layoutStore";
import useGlobalKeys from "@/hooks/useGlobalKeys";
import WidgetPicker from "@/chrome/WidgetPicker";
import ToolsDropdown from "@/chrome/ToolsDropdown";
import PresetPicker from "@/chrome/PresetPicker";
import { widgetComponents } from "@/layout/widgetFactory";
import { applyPreset, DEFAULT_PRESET_ID } from "@/layout/workspacePresets";
import type { ToolId } from "@/types/widgets";

// Full-page tools available from the TOOLS dropdown on /trade.
// backtest-lab → /lab, strategy-builder → /lab, flow-builder → /automate
// are full routes now and are no longer overlaid on the /trade canvas.
const tools: Record<ToolId, React.LazyExoticComponent<React.ComponentType<{ onClose: () => void }>>> = {
  "settings": lazy(() => import("../tools/Settings/SettingsTool")),
  "trade-journal": lazy(() => import("../tools/TradeJournal/TradeJournalTool")),
  "pnl-dashboard": lazy(() => import("../tools/PnLDashboard/PnLDashboardTool")),
  "market-intelligence": lazy(() => import("../tools/MarketIntelligence/MarketIntelligenceTool")),
};

export default function TerminalRoute() {
  const [activeTool, setActiveTool] = useState<ToolId | null>(null);
  const [panelCount, setPanelCount] = useState<number | null>(null);

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

      // Track panel count for the empty-state overlay.
      setPanelCount(event.api.panels.length);
      event.api.onDidAddPanel(() => setPanelCount(event.api.panels.length));
      event.api.onDidRemovePanel(() => setPanelCount(event.api.panels.length));

      const activeTabId = useLayoutStore.getState().activeTabId;
      const savedLayout = useLayoutStore.getState().getTabLayout(activeTabId);

      if (savedLayout) {
        // Check if the setup wizard left a pending preset request instead of a
        // real serialized layout.
        const pendingPreset = (savedLayout as Record<string, unknown>).__pendingPreset;
        if (typeof pendingPreset === "string") {
          // Clear the placeholder and apply the chosen preset.
          useLayoutStore.getState().saveTabLayout(activeTabId, {});
          applyPreset(event.api, pendingPreset);
        } else {
          try {
            // Restore the persisted layout for this workspace tab.
            // Cast through unknown because we store as Record<string,unknown> in Zustand.
            event.api.fromJSON(savedLayout as unknown as Parameters<typeof event.api.fromJSON>[0]);
          } catch {
            // Corrupted saved layout — fall back to the default preset
            applyPreset(event.api, DEFAULT_PRESET_ID);
          }
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

  // Listen for the custom event dispatched by DailyWelcome's "Open Trade Journal" link.
  useEffect(() => {
    function onOpenTool(e: Event) {
      const detail = (e as CustomEvent<{ toolId: ToolId }>).detail;
      if (detail?.toolId) {
        setActiveTool(detail.toolId);
      }
    }
    window.addEventListener("flinttrade:open-tool", onOpenTool);
    return () => window.removeEventListener("flinttrade:open-tool", onOpenTool);
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
          {/* Empty-state overlay: shown when the canvas has no open panels */}
          {panelCount === 0 && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
              <div
                className="pointer-events-auto flex flex-col items-center gap-4 px-8 py-10 rounded-xl border border-border-default bg-surface-card/80 backdrop-blur-sm shadow-lg animate-fade-in text-center max-w-xs"
                role="status"
              >
                <LayoutGrid className="h-10 w-10 text-text-muted" />
                <div className="space-y-1">
                  <p className="font-heading font-semibold text-base text-text-primary">
                    Your workspace is empty
                  </p>
                  <p className="text-sm text-text-secondary">
                    Add widgets or choose a template to get started
                  </p>
                </div>
                <div className="flex gap-2 mt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 text-xs border-border-default text-text-secondary hover:text-text-primary"
                    onClick={() => setWidgetPickerOpen(true)}
                  >
                    <LayoutGrid className="h-3.5 w-3.5 mr-1.5" />
                    Add Widgets
                  </Button>
                  <Button
                    size="sm"
                    className="h-8 text-xs bg-primary hover:bg-primary/90 text-primary-foreground"
                    onClick={() => setPresetPickerOpen(true)}
                  >
                    <Layers className="h-3.5 w-3.5 mr-1.5" />
                    Choose Template
                  </Button>
                </div>
              </div>
            </div>
          )}
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
