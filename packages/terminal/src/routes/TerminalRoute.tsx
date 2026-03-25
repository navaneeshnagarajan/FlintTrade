import { useState, useCallback, useEffect, useRef, lazy, Suspense, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { CinematicLayout } from "@/components/layout/CinematicLayout";
import { DockviewReact } from "dockview-react";
import type { DockviewReadyEvent } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { LayoutGrid, Layers, ShieldOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLayoutStore } from "@/stores/layoutStore";
import { useThemeStore } from "@/stores/themeStore";
import { useTradingStore } from "@/stores/tradingStore";
import { useSettingsStore } from "@/stores/settingsStore";
import useGlobalKeys from "@/hooks/useGlobalKeys";
import WidgetPicker from "@/chrome/WidgetPicker";
import PresetPicker from "@/chrome/PresetPicker";
import { widgetComponents } from "@/layout/widgetFactory";
import { applyPreset } from "@/layout/workspacePresets";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useDockviewTheme } from "@/hooks/useDockviewTheme";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import type { ToolId } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Kill Switch Pill — floating daily loss monitor
// ---------------------------------------------------------------------------

/**
 * Shown in the bottom-left when daily P&L exceeds 50% of the configured
 * MTM stop-loss threshold. Provides a one-click emergency kill switch that
 * calls POST /api/v1/safety/kill-switch to cancel all orders and close all
 * positions via the backend SafetySystem (Layer 5).
 */
function KillSwitchPill() {
  const totalPnl = useTradingStore((s) => s.totalPnl);
  // mtmStoploss is stored as a positive rupee value, e.g. 5000 = ₹5,000 daily loss limit
  const mtmStoploss = useSettingsStore((s) => s.riskLimits.mtmStoploss);
  const [isTriggering, setIsTriggering] = useState(false);
  const [triggered, setTriggered] = useState(false);

  // Show pill when loss exceeds 50% of configured MTM stop-loss
  const threshold = mtmStoploss > 0 ? mtmStoploss * 0.5 : Infinity;
  const isNearLimit = totalPnl < 0 && Math.abs(totalPnl) >= threshold;

  if (!isNearLimit) return null;

  const isAtLimit = mtmStoploss > 0 && Math.abs(totalPnl) >= mtmStoploss;

  async function handleKillSwitch() {
    if (isTriggering || triggered) return;
    setIsTriggering(true);
    try {
      await fetch("/api/v1/safety/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Manual kill switch — trader initiated from terminal" }),
      });
      setTriggered(true);
    } catch {
      // Silent — the pill remains visible so the user can retry
    } finally {
      setIsTriggering(false);
    }
  }

  return (
    <div
      role="status"
      aria-live="assertive"
      aria-atomic="true"
      aria-label={`Daily loss alert: ₹${Math.abs(totalPnl).toFixed(0)}`}
      className="fixed bottom-4 left-4 z-40 bg-surface-card border border-loss/30 rounded-lg p-3 backdrop-blur-sm shadow-lg max-w-[180px]"
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <ShieldOff size={13} className="text-loss shrink-0" aria-hidden="true" />
        <span className="text-xs text-loss font-medium font-mono">
          -₹{Math.abs(totalPnl).toFixed(0)}
        </span>
      </div>
      <div className="text-xxs text-text-muted mb-2 leading-tight">
        {isAtLimit
          ? "MTM limit reached"
          : `${((Math.abs(totalPnl) / mtmStoploss) * 100).toFixed(0)}% of daily limit`}
      </div>
      <Button
        size="sm"
        variant="destructive"
        className="w-full h-7 text-xs gap-1"
        onClick={handleKillSwitch}
        disabled={isTriggering || triggered}
        aria-label="Activate emergency kill switch to cancel all orders and close all positions"
      >
        <ShieldOff size={11} aria-hidden="true" />
        {triggered ? "Kill Active" : isTriggering ? "Activating..." : "Kill Switch"}
      </Button>
    </div>
  );
}

/**
 * Returns the best default preset for the given skill level on /trade.
 *   Beginner      → "beginner-core" (applied manually — 5 widgets)
 *   Intermediate  → "market-watch"
 *   Advanced      → "scalper-zone"
 */
function getDefaultPresetId(level: "beginner" | "intermediate" | "advanced"): string {
  if (level === "advanced") return "scalper-zone";
  if (level === "intermediate") return "market-watch";
  return "beginner-core"; // handled as a special case below
}

/**
 * Apply the beginner-friendly 5-widget layout:
 * Dashboard, Chart, Watchlist, OrderPad, Positions — simple top/bottom split.
 */
function applyBeginnerLayout(api: import("dockview-react").DockviewApi): void {
  const ts = Date.now();
  const chartId = `chart-${ts}-a`;
  const watchlistId = `watchlist-${ts}-b`;
  const orderpadId = `orderpad-${ts}-c`;
  const positionsId = `positions-${ts}-d`;
  const dashboardId = `dashboard-${ts}-e`;

  api.addPanel({ id: chartId, component: "chart", title: "Chart" });

  api.addPanel({
    id: watchlistId,
    component: "watchlist",
    title: "Watchlist",
    position: { referencePanel: chartId, direction: "right" },
    initialWidth: 240,
  });

  api.addPanel({
    id: orderpadId,
    component: "orderpad",
    title: "Order Pad",
    position: { referencePanel: watchlistId, direction: "below" },
  });

  api.addPanel({
    id: positionsId,
    component: "positions",
    title: "Positions",
    position: { referencePanel: chartId, direction: "below" },
    initialHeight: 200,
  });

  api.addPanel({
    id: dashboardId,
    component: "dashboard",
    title: "Dashboard",
    position: { referencePanel: positionsId, direction: "within" },
  });
}

// Full-page tools available from the TOOLS dropdown on /trade.
// backtest-lab → /lab, strategy-builder → /lab, flow-builder → /automate
// are full routes now and are no longer overlaid on the /trade canvas.
// "settings" navigates to /settings (handled in flinttrade:open-tool event listener).
const tools: Omit<Record<ToolId, React.LazyExoticComponent<React.ComponentType<{ onClose: () => void }>>>, "settings"> = {
  "trade-journal": lazy(() => import("../tools/TradeJournal/TradeJournalTool")),
  "pnl-dashboard": lazy(() => import("../tools/PnLDashboard/PnLDashboardTool")),
  "market-intelligence": lazy(() => import("../tools/MarketIntelligence/MarketIntelligenceTool")),
};

export default function TerminalRoute() {
  const navigate = useNavigate();
  const [activeTool, setActiveTool] = useState<ToolId | null>(null);
  const [panelCount, setPanelCount] = useState<number | null>(null);
  const disposablesRef = useRef<Array<{ dispose(): void }>>([]);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const level = useSkillLevel("trade");
  const resolvedMode = useThemeStore((s) => s.getResolvedMode());
  const dockviewThemeClass = resolvedMode === "light" ? "dockview-theme-light" : "dockview-theme-dark";
  const dockviewThemeCssVars = useDockviewTheme();
  const dockviewStyle = useMemo(
    () => dockviewThemeCssVars as React.CSSProperties,
    [dockviewThemeCssVars],
  );

  const setDockviewApi = useLayoutStore((s) => s.setDockviewApi);
  const widgetPickerOpen = useLayoutStore((s) => s.widgetPickerOpen);
  const setWidgetPickerOpen = useLayoutStore((s) => s.setWidgetPickerOpen);
  const presetPickerOpen = useLayoutStore((s) => s.presetPickerOpen);
  const setPresetPickerOpen = useLayoutStore((s) => s.setPresetPickerOpen);

  // Global keyboard shortcuts (Esc, Ctrl+K, X=exit all, C=cancel all)
  useGlobalKeys({
    onEscape: useCallback(() => {
      if (activeTool) { setActiveTool(null); return; }
      if (presetPickerOpen) { setPresetPickerOpen(false); return; }
      if (widgetPickerOpen) { setWidgetPickerOpen(false); return; }
    }, [activeTool, presetPickerOpen, widgetPickerOpen, setPresetPickerOpen, setWidgetPickerOpen]),
    onCommandPalette: useCallback(() => {
      // Future: open command palette (Ctrl+K)
    }, []),
  });

  // ---------------------------------------------------------------------------
  // ARIA injection for Dockview panels (Issue #46)
  // Dockview v5 does not expose ARIA props. We patch the DOM after every
  // layout change so that tabs satisfy WCAG 2.1 SC 4.1.2 (name, role, value).
  // ---------------------------------------------------------------------------
  const applyDockviewAria = useCallback(() => {
    // tablist role on every tab strip container
    document.querySelectorAll(".dv-tabs-container").forEach((container) => {
      container.setAttribute("role", "tablist");
      container.querySelectorAll(".dv-tab").forEach((tab) => {
        tab.setAttribute("role", "tab");
        tab.setAttribute(
          "aria-selected",
          tab.classList.contains("dv-active-tab") ? "true" : "false",
        );
      });
    });
    // tabpanel role on every panel content container
    document.querySelectorAll(".dv-content-container").forEach((panel) => {
      panel.setAttribute("role", "tabpanel");
    });
  }, []);

  const onDockviewReady = useCallback(
    (event: DockviewReadyEvent) => {
      setDockviewApi(event.api);

      // Track panel count for the empty-state overlay.
      setPanelCount(event.api.panels.length);
      const d1 = event.api.onDidAddPanel(() => setPanelCount(event.api.panels.length));
      const d2 = event.api.onDidRemovePanel(() => setPanelCount(event.api.panels.length));
      disposablesRef.current.push(d1, d2);

      // Re-apply ARIA attributes after every Dockview layout mutation so that
      // newly added/removed tabs and panels stay annotated.
      const d4 = event.api.onDidLayoutChange(() => applyDockviewAria());
      disposablesRef.current.push(d4);
      // Apply once immediately after Dockview finishes its initial render.
      // rAF ensures the DOM has been painted before we query it.
      requestAnimationFrame(applyDockviewAria);

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
            // Corrupted saved layout — apply skill-appropriate default
            const skillPreset = getDefaultPresetId(level);
            if (skillPreset === "beginner-core") {
              applyBeginnerLayout(event.api);
            } else {
              applyPreset(event.api, skillPreset);
            }
          }
        }
      } else {
        // No layout saved yet — apply the skill-appropriate default preset.
        // Beginner: 5 core widgets (dashboard, chart, watchlist, orderpad, positions)
        // Intermediate: Market Watch preset
        // Advanced: Scalper Zone preset
        const skillPreset = getDefaultPresetId(level);
        if (skillPreset === "beginner-core") {
          applyBeginnerLayout(event.api);
        } else {
          applyPreset(event.api, skillPreset);
        }
      }
    },
    // level intentionally omitted — we only use it for the initial layout decision.
    // Re-running onDockviewReady on every skill change would reset the layout.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setDockviewApi, applyDockviewAria]
  );

  // Auto-save layout on changes (debounced 500ms to avoid thrashing on rapid panel ops)
  useEffect(() => {
    const api = useLayoutStore.getState().dockviewApi;
    if (!api) return;
    const d3 = api.onDidLayoutChange(() => {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => {
        const activeTabId = useLayoutStore.getState().activeTabId;
        const layout = api.toJSON();
        useLayoutStore.getState().saveTabLayout(activeTabId, layout as unknown as Record<string, unknown>);
      }, 500);
    });
    disposablesRef.current.push(d3);
    return () => {
      disposablesRef.current.forEach(d => d.dispose());
      disposablesRef.current = [];
      clearTimeout(saveTimerRef.current);
    };
  }, []);

  // Listen for the custom event dispatched by DailyWelcome's "Open Trade Journal" link,
  // and also by TopBar's ToolsDropdown (which replaced the old inline ToolsDropdown).
  useEffect(() => {
    function onOpenTool(e: Event) {
      const detail = (e as CustomEvent<{ toolId: ToolId }>).detail;
      if (!detail?.toolId) return;
      // "settings" navigates to the dedicated route, not a canvas overlay.
      if (detail.toolId === "settings") {
        navigate("/settings");
        return;
      }
      setActiveTool(detail.toolId);
    }
    window.addEventListener("flinttrade:open-tool", onOpenTool);
    return () => window.removeEventListener("flinttrade:open-tool", onOpenTool);
  }, [navigate]);

  // activeTool is never "settings" (navigate handles it), so the cast is safe.
  const ToolComponent = activeTool
    ? (tools as Record<string, React.LazyExoticComponent<React.ComponentType<{ onClose: () => void }>>>)[activeTool]
    : null;

  return (
    <CinematicLayout mode="focused">
    <div className="h-full flex flex-col text-text-primary overflow-hidden select-none">
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
        <div
          className="flex-1 relative overflow-hidden"
          data-tour-target="workspace"
          style={dockviewStyle}
        >
          <DockviewReact
            className={dockviewThemeClass}
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
                    {level === "beginner"
                      ? "Add your first widget — start with the Watchlist or Chart"
                      : "Add widgets or choose a template to get started"}
                  </p>
                </div>
                <div className="flex gap-2 mt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 text-xs border-border-default text-text-secondary hover:text-text-primary"
                    onClick={() => setWidgetPickerOpen(true)}
                    data-tour-target="widget-picker"
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

      {/* Guided tour — only shown to beginners on their first visit */}
      {level === "beginner" && (
        <SpotlightTour
          tourId="trade-beginner"
          steps={TOUR_DEFINITIONS["trade-beginner"] ?? []}
        />
      )}

      {/* Kill switch pill — floats over the canvas when daily loss threshold is reached */}
      <KillSwitchPill />
    </div>
    </CinematicLayout>
  );
}
