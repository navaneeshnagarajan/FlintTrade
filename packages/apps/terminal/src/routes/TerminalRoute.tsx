import { useState, useCallback, useEffect, useRef, lazy, Suspense, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import { CinematicLayout } from "@/components/layout/CinematicLayout";
import { DockviewReact } from "dockview-react";
import type { DockviewApi, DockviewReadyEvent, IDockviewPanelProps } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import {
  CandlestickChart,
  FileEdit,
  LayoutGrid,
  Layers,
  ShieldOff,
  Star,
  Table2,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLayoutStore } from "@/stores/layoutStore";
import { useThemeStore } from "@/stores/themeStore";
import { useTradingStore } from "@/stores/tradingStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useModeStore } from "@/stores/modeStore";
import WidgetPicker from "@/chrome/WidgetPicker";
import PresetPicker from "@/chrome/PresetPicker";
import { widgetCatalog, widgetComponents } from "@/layout/widgetFactory";
import { applyPreset } from "@/layout/workspacePresets";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import { useSkillContent } from "@/hooks/useSkillContent";
import { useDockviewTheme } from "@/hooks/useDockviewTheme";
import { SpotlightTour } from "@/components/help/SpotlightTour";
import { RouteBanner } from "@/components/help/RouteBanner";
import { TOUR_DEFINITIONS } from "@/lib/tourDefinitions";
import type { ToolId } from "@/types/widgets";
import { Group, Panel, Separator, useDefaultLayout, usePanelRef } from "react-resizable-panels";
import { SectionHeader } from "@/components/layout/SectionHeader";
import {
  activateKillSwitch,
  getSafetyConfig,
  type SafetyConfig,
} from "@/services/ftApi";
import { TradeBottomPanel } from "./trade/TradeBottomPanel";

// ---------------------------------------------------------------------------
// Kill Switch Pill — account-MTM warning and explicit Layer 5 control
// ---------------------------------------------------------------------------

const SAFETY_CONFIG_QUERY_KEY = ["safetyConfig"] as const;

/**
 * Persistent Layer 5 status for Live mode. Account MTM changes its warning
 * presentation, but cannot hide an active, loading, or unavailable kill switch.
 * Activation halts routing and asks the backend to attempt emergency actions.
 */
function KillSwitchPill() {
  const queryClient = useQueryClient();
  const mode = useModeStore((s) => s.mode);
  const totalPnl = useTradingStore((s) => s.totalPnl);
  // mtmStoploss is stored as a positive rupee value, e.g. 5000 = ₹5,000 daily loss limit
  const mtmStoploss = useSettingsStore((s) => s.riskLimits.mtmStoploss);
  const {
    data: safetyConfig,
    isLoading: safetyLoading,
    isError: safetyError,
  } = useQuery({
    queryKey: SAFETY_CONFIG_QUERY_KEY,
    queryFn: getSafetyConfig,
    refetchInterval: 5_000,
  });

  const activationMutation = useMutation({
    mutationFn: () => activateKillSwitch("Manual kill switch — trader initiated from terminal"),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: SAFETY_CONFIG_QUERY_KEY });
      const current = queryClient.getQueryData<SafetyConfig>(SAFETY_CONFIG_QUERY_KEY);
      if (current === undefined) {
        throw new Error("Authoritative safety state is unavailable");
      }
      return { safetyConfig: current };
    },
    onSuccess: (result, _variables, context) => {
      const flattenComplete = result.emergency_actions.complete;
      const current = queryClient.getQueryData<SafetyConfig>(SAFETY_CONFIG_QUERY_KEY) ?? context.safetyConfig;
      queryClient.setQueryData<SafetyConfig>(SAFETY_CONFIG_QUERY_KEY, {
        ...current,
        kill_switch_active: result.is_active,
        kill_switch_reason: result.reason,
        flatten_complete: flattenComplete,
        emergency_result: result.emergency_actions,
      });
      emitNotification({
        category: "system",
        title: "Kill switch ACTIVATED",
        body: flattenComplete
          ? "All live order routing is halted and emergency broker actions completed."
          : "Live order routing is halted, but one or more broker flattening actions did not complete. Review broker state before resetting.",
        action: {
          label: flattenComplete ? "Review kill switch" : "Retry emergency actions",
          href: "/automate",
        },
      });
    },
    onError: (error: Error) => {
      emitNotification({
        category: "system",
        title: "Kill switch activation failed",
        body: error.message || "Emergency control failed",
      });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: SAFETY_CONFIG_QUERY_KEY,
        refetchType: "active",
      });
    },
  });

  const threshold = mtmStoploss > 0 ? mtmStoploss * 0.5 : Infinity;
  const isNearLimit = totalPnl < 0 && Math.abs(totalPnl) >= threshold;
  const killSwitchState = safetyConfig === undefined
    ? safetyLoading ? "loading" : "unavailable"
    : safetyConfig.kill_switch_active ? "active" : "inactive";
  const killSwitchActive = killSwitchState === "active";
  const flattenComplete = killSwitchActive && safetyConfig?.flatten_complete === true;
  const flattenIncomplete = killSwitchActive && !flattenComplete;

  if (mode !== "live") return null;

  const isAtLimit = mtmStoploss > 0 && Math.abs(totalPnl) >= mtmStoploss;
  const isUnavailable = killSwitchState === "unavailable";
  const isLoading = killSwitchState === "loading";
  const statusLabel = isNearLimit && killSwitchState === "inactive"
    ? `Daily loss alert: ₹${Math.abs(totalPnl).toFixed(0)}; kill switch status: inactive`
    : `Kill switch status: ${killSwitchState}`;
  const baseStatusText = isLoading
    ? "Checking kill-switch state..."
    : isUnavailable
    ? "Authoritative kill-switch state is unavailable"
    : flattenIncomplete
    ? "Kill switch active; broker flattening is incomplete"
    : killSwitchActive
    ? "Kill switch active; live order routing is halted"
    : isAtLimit
    ? "MTM limit reached"
    : isNearLimit
    ? `${((Math.abs(totalPnl) / mtmStoploss) * 100).toFixed(0)}% of daily limit`
    : "Kill switch inactive";
  const statusText = safetyError && safetyConfig !== undefined
    ? `${baseStatusText} (last known state; latest refresh failed)`
    : baseStatusText;

  function handleKillSwitch() {
    if (safetyConfig === undefined || activationMutation.isPending || (killSwitchActive && flattenComplete)) return;
    activationMutation.mutate();
  }

  return (
    <div
      role={isUnavailable ? "alert" : "status"}
      aria-live={killSwitchActive || isNearLimit || isUnavailable ? "assertive" : "polite"}
      aria-atomic="true"
      aria-label={statusLabel}
      className={[
        "shrink-0 z-40 border-t px-4 py-2 backdrop-blur-sm",
        killSwitchActive || isNearLimit
          ? "border-loss/30 bg-loss/10"
          : isUnavailable
          ? "border-warning/30 bg-warning/10"
          : "border-border-default bg-surface-elevated/90",
      ].join(" ")}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex items-center gap-1.5">
            <ShieldOff
              size={13}
              className={killSwitchActive || isNearLimit ? "text-loss shrink-0" : "text-text-muted shrink-0"}
              aria-hidden="true"
            />
            <span
              className={[
                "text-xs font-medium font-mono",
                killSwitchActive || isNearLimit ? "text-loss" : "text-text-muted",
              ].join(" ")}
            >
              {isNearLimit && !killSwitchActive
                ? `-₹${Math.abs(totalPnl).toFixed(0)}`
                : killSwitchActive
                ? "L5 ACTIVE"
                : "L5"}
            </span>
          </div>
          <span className="text-xs text-text-secondary">{statusText}</span>
        </div>
        <Button
          size="sm"
          variant="destructive"
          className="h-7 text-xs gap-1 shrink-0"
          onClick={handleKillSwitch}
          disabled={
            // Emergency control fails AVAILABLE: a failed refresh with a
            // last-known state keeps the button live (the server is the
            // authority on activation); only never-loaded state blocks it.
            isLoading
            || isUnavailable
            || safetyConfig === undefined
            || activationMutation.isPending
            || (killSwitchActive && flattenComplete)
          }
          aria-label={flattenIncomplete
            ? "Retry emergency broker actions"
            : killSwitchActive
            ? "Kill switch is active; live order routing is halted"
            : "Activate emergency kill switch process-wide to halt routing and attempt order cancellation and position flattening"}
        >
          <ShieldOff size={11} aria-hidden="true" />
          {killSwitchActive && flattenComplete
            ? "Kill Active"
            : activationMutation.isPending
            ? "Activating..."
            : flattenIncomplete
            ? "Retry Flatten"
            : "Kill Switch"}
        </Button>
      </div>
      {activationMutation.isError && (
        <p role="alert" className="mt-2 text-xs text-loss">
          {activationMutation.error.message || "Emergency control failed"}
        </p>
      )}
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
 * Index Strip, Chart, Watchlist, OrderPad, Positions — an always-visible
 * index strip on top, then a simple left/right split. The strip replaces the
 * retired Dashboard widget (its positions/orders tables and funds cards were
 * duplicates of the Positions, Orders and Risk widgets; the index cards were
 * the part a beginner layout actually needs at a glance).
 */
function applyBeginnerLayout(api: import("dockview-react").DockviewApi): void {
  const ts = Date.now();
  const chartId = `chart-${ts}-a`;
  const watchlistId = `watchlist-${ts}-b`;
  const orderpadId = `orderpad-${ts}-c`;
  const positionsId = `positions-${ts}-d`;
  const indexStripId = `indexstrip-${ts}-e`;

  api.addPanel({ id: chartId, component: "chart", title: "Chart" });

  api.addPanel({
    id: indexStripId,
    component: "indexstrip",
    title: "Indices",
    position: { referencePanel: chartId, direction: "above" },
    initialHeight: 150,
  });

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
}

// Full-page tools available from the TOOLS dropdown on /trade.
// backtest-lab → /lab, strategy-builder → /lab, flow-builder → /automate
// are full routes now and are no longer overlaid on the /trade canvas.
// "settings" navigates to /settings (handled in flinttrade:open-tool event listener).
// "market-intelligence" is unmounted (ruling D4): every tab it carried is served
// by a Dockview widget now — Market Overview, OI Analytics, Dealer Gamma, IV
// Smile & Skew, Correlation Matrix and Delivery Data. The id stays in ToolId
// only so a stale saved value cannot fail to type-check; nothing resolves it,
// so `ToolComponent` is undefined and no overlay opens.
const tools: Omit<
  Record<ToolId, React.LazyExoticComponent<React.ComponentType<{ onClose: () => void }>>>,
  "settings" | "market-intelligence"
> = {
  "trade-journal": lazy(() => import("../tools/TradeJournal/TradeJournalTool")),
};

const COMPACT_TRADE_BREAKPOINT = 768;

function isCompactTradeViewport(): boolean {
  if (typeof window === "undefined") return false;
  return window.innerWidth < COMPACT_TRADE_BREAKPOINT;
}

function useCompactTradeWorkspace(): boolean {
  const [isCompact, setIsCompact] = useState(isCompactTradeViewport);

  useEffect(() => {
    function handleResize() {
      setIsCompact(isCompactTradeViewport());
    }

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  return isCompact;
}

type CompactTradeWidgetId = "chart" | "watchlist" | "orderpad" | "positions" | "indexstrip";

const COMPACT_TRADE_WIDGETS: Array<{
  id: CompactTradeWidgetId;
  label: string;
  Icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
}> = [
  { id: "chart", label: "Chart", Icon: CandlestickChart },
  { id: "watchlist", label: "Watchlist", Icon: Star },
  { id: "orderpad", label: "Order Pad", Icon: FileEdit },
  { id: "positions", label: "Positions", Icon: Table2 },
  { id: "indexstrip", label: "Indices", Icon: TrendingUp },
];

function TradeCompactWorkspace({
  onOpenWidgetPicker,
  onOpenPresetPicker,
}: {
  onOpenWidgetPicker: () => void;
  onOpenPresetPicker: () => void;
}) {
  const [activeWidgetId, setActiveWidgetId] = useState<CompactTradeWidgetId>("chart");
  const tabRefs = useRef<Partial<Record<CompactTradeWidgetId, HTMLButtonElement | null>>>({});
  const activeWidget = COMPACT_TRADE_WIDGETS.find((widget) => widget.id === activeWidgetId) ?? COMPACT_TRADE_WIDGETS[0];
  const ActiveWidgetPanel = widgetComponents[activeWidget.id];
  const panelProps = {} as IDockviewPanelProps;

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    let nextIndex: number | undefined;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % COMPACT_TRADE_WIDGETS.length;
    if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + COMPACT_TRADE_WIDGETS.length) % COMPACT_TRADE_WIDGETS.length;
    }
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = COMPACT_TRADE_WIDGETS.length - 1;
    if (nextIndex === undefined) return;

    event.preventDefault();
    const nextId = COMPACT_TRADE_WIDGETS[nextIndex].id;
    setActiveWidgetId(nextId);
    tabRefs.current[nextId]?.focus();
  }

  return (
    <section
      aria-label="Compact trade workspace"
      className="flex h-full min-h-0 flex-col overflow-hidden bg-surface-base"
      data-testid="trade-compact-workspace"
      data-tour-target="workspace"
    >
      <div className="shrink-0 border-b border-border-default bg-surface-elevated/90">
        <div
          role="tablist"
          aria-label="Trade workspace panels"
          className="flex min-w-0 items-center gap-1 overflow-x-auto px-2 py-2"
        >
          {COMPACT_TRADE_WIDGETS.map(({ id, label, Icon }, index) => {
            const isActive = activeWidgetId === id;
            return (
              <button
                key={id}
                ref={(element) => { tabRefs.current[id] = element; }}
                id={`trade-compact-tab-${id}`}
                type="button"
                role="tab"
                aria-selected={isActive}
                aria-controls={`trade-compact-panel-${id}`}
                tabIndex={isActive ? 0 : -1}
                onClick={() => setActiveWidgetId(id)}
                onKeyDown={(event) => handleTabKeyDown(event, index)}
                className={[
                  "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border px-3 text-xs font-medium transition-colors",
                  isActive
                    ? "border-profit/40 bg-profit/15 text-profit shadow-[0_0_18px_rgba(34,197,94,0.12)]"
                    : "border-border-default bg-surface-card text-text-secondary hover:border-profit/25 hover:text-text-primary",
                ].join(" ")}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden />
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div
        id={`trade-compact-panel-${activeWidget.id}`}
        role="tabpanel"
        aria-labelledby={`trade-compact-tab-${activeWidget.id}`}
        className="min-h-0 flex-1 overflow-hidden"
      >
        {ActiveWidgetPanel ? (
          <ActiveWidgetPanel {...panelProps} />
        ) : (
          <div role="status" className="flex h-full items-center justify-center text-xs text-text-muted">
            {activeWidget.label} is unavailable.
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center justify-between gap-2 border-t border-border-default bg-surface-elevated/90 px-3 py-2">
        <span className="min-w-0 truncate text-xs text-text-muted">
          Compact workspace
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 border-border-default px-2.5 text-xs text-text-secondary hover:text-text-primary"
            onClick={onOpenWidgetPicker}
          >
            <LayoutGrid className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            Add
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-8 bg-profit px-2.5 text-xs text-black hover:bg-profit/90"
            onClick={onOpenPresetPicker}
          >
            <Layers className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            Templates
          </Button>
        </div>
      </div>
    </section>
  );
}

export default function TerminalRoute() {
  const navigate = useNavigate();
  const [activeTool, setActiveTool] = useState<ToolId | null>(null);
  const [panelCount, setPanelCount] = useState<number | null>(null);
  const isCompactWorkspace = useCompactTradeWorkspace();
  // d1/d2/d4 — subscriptions created inside onDockviewReady; cleaned up on unmount.
  const readyDisposablesRef = useRef<Array<{ dispose(): void }>>([]);
  // d3 — auto-save subscription managed by its own useEffect.
  const saveDisposableRef = useRef<{ dispose(): void } | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const mountedDockviewApiRef = useRef<DockviewApi | null>(null);
  // rAF handle for coalesced ARIA injection.
  const ariaRafRef = useRef<number | undefined>(undefined);

  // ---------------------------------------------------------------------------
  // Resizable panels — layout persistence via localStorage
  // ---------------------------------------------------------------------------
  // Horizontal layout: [dockview, right-panel]. The v2 key ignores older
  // persisted layouts that included the retired internal trade sidebar.
  const { defaultLayout: hLayout, onLayoutChanged: onHLayoutChanged } = useDefaultLayout({
    id: "trade-h-layout-v2",
    storage: localStorage,
  });
  // Vertical layout: [main, bottom-panel]
  const { defaultLayout: vLayout, onLayoutChanged: onVLayoutChanged } = useDefaultLayout({
    id: "trade-v-layout",
    storage: localStorage,
  });

  // Imperative refs for programmatic collapse/expand (future toolbar buttons).
  const bottomPanelRef = usePanelRef();
  const rightPanelRef = usePanelRef();

  const level = useSkillLevel("trade");
  const skillContent = useSkillContent();
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

  // Escape handling — useGlobalKeys is mounted ONCE, in AppLayout (destructive
  // trading hotkeys must never register twice). AppLayout forwards Escape as a
  // flinttrade:escape event; this route closes its local overlays in response.
  useEffect(() => {
    function onEscapeSignal() {
      if (activeTool) { setActiveTool(null); return; }
      if (presetPickerOpen) { setPresetPickerOpen(false); return; }
      if (widgetPickerOpen) { setWidgetPickerOpen(false); return; }
    }
    window.addEventListener("flinttrade:escape", onEscapeSignal);
    return () => window.removeEventListener("flinttrade:escape", onEscapeSignal);
  }, [activeTool, presetPickerOpen, widgetPickerOpen, setPresetPickerOpen, setWidgetPickerOpen]);

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
      mountedDockviewApiRef.current = event.api;
      setDockviewApi(event.api);

      // Track panel count for the empty-state overlay.
      setPanelCount(event.api.panels.length);
      const d1 = event.api.onDidAddPanel(() => setPanelCount(event.api.panels.length));
      const d2 = event.api.onDidRemovePanel(() => setPanelCount(event.api.panels.length));
      readyDisposablesRef.current.push(d1, d2);

      // Dispatch active-widget context for AITutorPill whenever a panel gains focus.
      // AITutorPill subscribes via window.addEventListener("flinttrade:active-widget").
      const d3aw = event.api.onDidActivePanelChange((panel) => {
        window.dispatchEvent(
          new CustomEvent("flinttrade:active-widget", { detail: panel?.id ?? null }),
        );
      });
      readyDisposablesRef.current.push(d3aw);

      // Re-apply ARIA attributes after every Dockview layout mutation so that
      // newly added/removed tabs and panels stay annotated.
      // rAF coalescing prevents redundant DOM queries on every drag frame.
      const d4 = event.api.onDidLayoutChange(() => {
        if (ariaRafRef.current !== undefined) cancelAnimationFrame(ariaRafRef.current);
        ariaRafRef.current = requestAnimationFrame(applyDockviewAria);
      });
      readyDisposablesRef.current.push(d4);
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
        // Beginner: 5 core widgets (indexstrip, chart, watchlist, orderpad, positions)
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

  // Cleanup d1/d2/d4 (onReady subscriptions) on unmount.
  useEffect(() => {
    return () => {
      readyDisposablesRef.current.forEach((d) => d.dispose());
      readyDisposablesRef.current = [];
      if (ariaRafRef.current !== undefined) cancelAnimationFrame(ariaRafRef.current);
      const mountedApi = mountedDockviewApiRef.current;
      if (mountedApi && useLayoutStore.getState().dockviewApi === mountedApi) {
        setDockviewApi(null);
      }
      mountedDockviewApiRef.current = null;
    };
  }, [setDockviewApi]);

  // Auto-save layout on changes (debounced 500ms to avoid thrashing on rapid panel ops).
  // d3 is managed independently of the onReady disposables so its cleanup
  // does not accidentally dispose d1/d2/d4.
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
    saveDisposableRef.current = d3;
    return () => {
      saveDisposableRef.current?.dispose();
      saveDisposableRef.current = null;
      clearTimeout(saveTimerRef.current);
    };
  }, []);

  // Listen for the custom event dispatched by DailyWelcome's "Open Trade Review" link,
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

  // Command palette widget actions dispatch this event; keep it here so widgets
  // can be opened without requiring the modal picker to already be visible.
  useEffect(() => {
    function onAddWidget(e: Event) {
      const detail = (e as CustomEvent<{
        widgetId?: string;
        props?: Record<string, unknown>;
        title?: string;
      }>).detail;
      const widgetId = detail?.widgetId;
      if (!widgetId || !(widgetId in widgetComponents)) return;

      const api = useLayoutStore.getState().dockviewApi;
      if (!api) return;

      const meta = widgetCatalog.find((widget) => widget.id === widgetId);
      const panelOptions: Parameters<typeof api.addPanel>[0] = {
        id: `${widgetId}-${Date.now()}`,
        component: widgetId,
        title: detail.title ?? meta?.name ?? widgetId,
      };

      if (detail.props) {
        panelOptions.params = detail.props;
      }

      api.addPanel(panelOptions);
    }

    window.addEventListener("flinttrade:addWidget", onAddWidget);
    return () => window.removeEventListener("flinttrade:addWidget", onAddWidget);
  }, []);

  // activeTool is never "settings" (navigate handles it), so the cast is safe.
  const ToolComponent = activeTool
    ? (tools as Record<string, React.LazyExoticComponent<React.ComponentType<{ onClose: () => void }>>>)[activeTool]
    : null;

  return (
    <CinematicLayout mode="focused">
    <div className="relative h-full flex flex-col text-text-primary overflow-hidden select-none">
      <h1 className="sr-only">Trade Workspace</h1>
      {/* Route-level hint banner — dismissible, respects helpPrefs.inlineHints */}
      <RouteBanner
        hintId="trade-shortcuts"
        text="Press Ctrl+K to open the command palette. Use X to exit all positions and C to cancel all orders."
      />
      {/* Main content: Dockview canvas OR full-page tool */}
      {activeTool && ToolComponent ? (
        <div className="flex-1 overflow-auto">
          <Suspense
            fallback={
              <div role="status" className="flex items-center justify-center h-full text-text-secondary text-sm">
                <span className="sr-only">Loading tool...</span>
                <span aria-hidden="true">Loading tool...</span>
              </div>
            }
          >
            <ToolComponent onClose={() => setActiveTool(null)} />
          </Suspense>
        </div>
      ) : (
        isCompactWorkspace ? (
          <div className="flex-1 min-h-0">
            <TradeCompactWorkspace
              onOpenWidgetPicker={() => setWidgetPickerOpen(true)}
              onOpenPresetPicker={() => setPresetPickerOpen(true)}
            />
          </div>
        ) : (
        /* ------------------------------------------------------------------ *
         * Resizable panel shell — vertical outer split + horizontal inner split
         * Bottom panel is collapsed by default (collapsedSize={0}).
         * Dockview MUST sit inside overflow-hidden to prevent sash drift.
         * ------------------------------------------------------------------ */
        <Group
          orientation="vertical"
          className="flex-1 min-h-0"
          defaultLayout={vLayout}
          onLayoutChanged={onVLayoutChanged}
        >
          {/* ---- Main row: dockview + right panel ---- */}
          <Panel id="trade-main" defaultSize={75} minSize={40}>
            <Group
              orientation="horizontal"
              className="h-full"
              defaultLayout={hLayout}
              onLayoutChanged={onHLayoutChanged}
            >
              {/* Center: Dockview canvas */}
              <Panel id="trade-dockview">
                {/* overflow-hidden is mandatory — Dockview measures its parent
                    to compute sash positions. Without it, height calculations break. */}
                <div
                  className="h-full w-full overflow-hidden relative"
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
              </Panel>

              <Separator
                id="trade-sep-right"
                className="w-1 cursor-col-resize bg-border-default hover:bg-primary/50 active:bg-primary/70 transition-colors shrink-0"
              />

              {/* Right panel: Order Pad (collapsed by default — open via widget picker) */}
              <Panel
                id="trade-right"
                panelRef={rightPanelRef}
                defaultSize={0}
                minSize={0}
                maxSize={30}
                collapsible
                collapsedSize={0}
              >
                <div
                  data-testid="trade-right-panel-shell"
                  className="box-border h-full w-full min-w-0 overflow-x-hidden overflow-y-auto bg-surface-card border-l border-border-default p-3"
                >
                  <SectionHeader title="Order Pad" as="h3" className="mb-2" />
                  <p className="text-xs text-text-muted">
                    Add the Order Pad widget from the widget picker.
                  </p>
                </div>
              </Panel>
            </Group>
          </Panel>

          {/* ---- Horizontal separator above bottom panel ---- */}
          <Separator
            id="trade-sep-bottom"
            className="h-1 cursor-row-resize bg-border-default hover:bg-primary/50 active:bg-primary/70 transition-colors shrink-0"
          />

          {/* ---- Bottom panel: Alerts / Trade Log ---- */}
          <Panel
            id="trade-bottom"
            panelRef={bottomPanelRef}
            defaultSize={0}
            minSize={8}
            collapsible
            collapsedSize={0}
          >
            <TradeBottomPanel />
          </Panel>
        </Group>
        )
      )}

      {/* Widget picker dialog — filtered to skill-appropriate widgets */}
      <WidgetPicker
        isOpen={widgetPickerOpen}
        onClose={() => setWidgetPickerOpen(false)}
        allowedIds={skillContent.availableWidgets}
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

      {/* Explicit Layer 5 control, shown once account MTM reaches the warning level */}
      <KillSwitchPill />

    </div>
    </CinematicLayout>
  );
}
