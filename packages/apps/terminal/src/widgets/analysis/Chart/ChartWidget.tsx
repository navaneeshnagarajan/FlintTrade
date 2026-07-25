import { useState, useEffect, useRef, useCallback, memo, type PointerEvent as ReactPointerEvent } from "react";
import type { IDockviewPanelProps } from "dockview-react";
import {
  FLINT_CHART_VIEW_STATE_STORAGE_KEY,
  FLINT_CHART_DISPLAY_SETTINGS_STORAGE_KEY,
  FLINT_CHART_INDICATOR_SETTINGS_STORAGE_KEY,
  FLINT_CHART_TWO_CLICK_TOOLS,
  FLINT_CHART_THREE_CLICK_TOOLS,
  FlintChartDrawStatus,
  FlintChartDrawingInspector,
  FlintChartDrawingList,
  FlintChartDrawingToolbar,
  FlintChartIntervalPills,
  FlintChartLegend,
  advanceFlintChartDrawingDraft,
  applyFlintCandlestickTheme,
  createFlintChartDisplaySettingsOptions,
  createFlintChartDrawingsStorageKey,
  encodeFlintChartDisplaySettings,
  encodeFlintChartDrawings,
  encodeFlintChartIndicatorSettings,
  encodeFlintChartViewState,
  getFlintChartActiveIndicatorCount,
  createFlintChartIndicatorPaneControls,
  getFlintChartDrawingStyle,
  getFlintChartKeyboardAction,
  getFlintChartSelectedDrawing,
  getFlintChartWorkspaceLayout,
  moveFlintChartDrawingByDelta,
  moveFlintChartDrawingHandleByDelta,
  parseFlintChartDisplaySettings,
  parseFlintChartDrawings,
  parseFlintChartIndicatorSettings,
  parseFlintChartViewState,
  removeFlintChartDrawingById,
  removeFlintChartUnlockedDrawings,
  resizeFlintChartIndicatorPaneStretchFactors,
  updateFlintChartDrawingStateById,
  updateFlintChartDrawingStyle,
  updateFlintChartDrawingsHidden,
  updateFlintChartDrawingsLocked,
} from "@flinttrade/design-system";
import type {
  FlintChartDrawingHandleId,
  FlintChartDrawingMoveDelta,
  FlintChartDrawingStyleInput,
  FlintChartIndicatorColor,
  FlintChartIndicatorKey,
  FlintChartIndicatorLineStyle,
  FlintChartIndicatorPaneSize,
  FlintChartIndicatorPaneStretchFactors,
  FlintChartIndicatorPaneControl,
  FlintChartLegendState as LegendState,
  FlintChartOhlcvBar as OhlcvBar,
  FlintChartVisibleLogicalRange,
} from "@flinttrade/design-system";
import {
  FLINT_CHART_INDICATOR_PANE_SIZE_LABELS,
  FLINT_CHART_INDICATOR_PANE_SIZE_OPTIONS,
  FLINT_CHART_INDICATOR_PANE_SIZE_SHORT_LABELS,
  FLINT_CHART_INDICATOR_PANE_STRETCH_FACTORS,
} from "@flinttrade/design-system";
import { useAtomValue } from "jotai";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import { readOhlcvCache, writeOhlcvCache } from "@/lib/chartCache";
import { isMarketHours } from "@/lib/market";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useDataScope } from "@/hooks/useDataScope";
import type { LogicalRange, Time } from "lightweight-charts";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import {
  Search,
  X,
  TrendingUp,
  TrendingDown,
  BarChart2,
  Trash2,
  History,
  Settings2,
  SlidersHorizontal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { searchSymbol, getHistory, getQuotes, getIntervals } from "@/services/api";

// Local modules
import { IndicatorSettingsModal } from "./IndicatorSettingsModal";
import { useChartInit } from "./useChartInit";
import { useDrawingTools } from "./useDrawingTools";
import { useIndicators } from "./useIndicators";
import { useChartReplay } from "./useChartReplay";
import { useOIOverlay } from "./useOIOverlay";
import { ReplayBar } from "./ReplayBar";
import type {
  SymbolSearchResult,
  IntervalOption,
  DrawToolType,
  DrawingPoint,
  Drawing,
  IndicatorState,
  IndicatorPeriods,
  IndicatorSeriesRefs,
} from "./types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_SYMBOL = "NIFTY";
const DEFAULT_EXCHANGE = "NSE_INDEX";

const STATIC_INTERVALS: IntervalOption[] = [
  { label: "1m",  value: "1m"  },
  { label: "3m",  value: "3m"  },
  { label: "5m",  value: "5m"  },
  { label: "15m", value: "15m" },
  { label: "30m", value: "30m" },
  { label: "1h",  value: "1h"  },
  { label: "4h",  value: "4h"  },
  { label: "1D",  value: "1D"  },
  { label: "1W",  value: "1W"  },
];

const LOOKBACK_DAYS: Record<string, number> = {
  "1m": 3, "3m": 7, "5m": 10, "15m": 20, "30m": 30,
  "1h": 60, "4h": 120, "1D": 365, "1W": 730,
};

function loadSavedChartView() {
  return parseFlintChartViewState(localStorage.getItem(FLINT_CHART_VIEW_STATE_STORAGE_KEY));
}

/**
 * Scope a chart storage key to a single Dockview panel.
 *
 * Indicator and display settings are per chart panel, not per workspace: a
 * layout can hold several charts (the Multi Chart preset lays out four) and
 * each must keep its own indicator set, periods, colours, pane sizing and
 * display toggles. Keying by panel id rather than symbol+exchange (the scheme
 * drawings correctly use) is deliberate — a drawing is anchored to one
 * instrument's price series, whereas an indicator set belongs to the chart:
 *   - a 1m/5m/15m/1D stack of the SAME instrument still gets four independent
 *     configurations, which symbol keying could not express;
 *   - changing a chart's symbol no longer swaps the indicator setup underneath
 *     the trader.
 * Dockview serialises panel ids into the persisted layout, so a panel-scoped
 * key survives a reload exactly as the layout itself does.
 *
 * Charts rendered outside a Dockview panel (no panel id) keep writing the
 * legacy workspace-wide key.
 */
function createFlintChartPanelStorageKey(baseKey: string, panelId: string | null): string {
  if (!panelId) return baseKey;
  return `${baseKey}:panel:${encodeURIComponent(panelId)}`;
}

/**
 * Read a panel-scoped settings payload, falling back to the workspace-wide key.
 *
 * The fallback is the migration path: a panel that has never been configured
 * inherits whatever the pre-panel-scoping (or standalone) chart saved, so
 * existing setups survive and a freshly added chart opens with familiar
 * settings instead of bare defaults.
 */
function readPanelScopedSetting(baseKey: string, panelId: string | null): string | null {
  if (!panelId) return localStorage.getItem(baseKey);
  return (
    localStorage.getItem(createFlintChartPanelStorageKey(baseKey, panelId)) ??
    localStorage.getItem(baseKey)
  );
}

function loadSavedIndicatorSettings(panelId: string | null) {
  return parseFlintChartIndicatorSettings(
    readPanelScopedSetting(FLINT_CHART_INDICATOR_SETTINGS_STORAGE_KEY, panelId),
  );
}

function loadSavedDisplaySettings(panelId: string | null) {
  return parseFlintChartDisplaySettings(
    readPanelScopedSetting(FLINT_CHART_DISPLAY_SETTINGS_STORAGE_KEY, panelId),
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getStartDate(interval: string): string {
  const d = new Date();
  d.setDate(d.getDate() - (LOOKBACK_DAYS[interval] ?? 30));
  return formatDate(d);
}

function formatPrice(v: number | null | undefined): string {
  if (v == null) return "--";
  return Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatChange(v: number | null): string {
  if (v == null) return "--";
  return `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}`;
}

function formatChangePct(v: number | null): string {
  if (v == null) return "--";
  return `${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface SymbolSearchProps { onSelect: (item: SymbolSearchResult) => void }

function SymbolSearch({ onSelect }: SymbolSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!query.trim() || query.length < 2) { setResults([]); setOpen(false); return; }
    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const raw = await searchSymbol(query.trim());
        const list = Array.isArray(raw) ? raw : ((raw as { data?: SymbolSearchResult[] })?.data ?? []);
        setResults(list.slice(0, 12));
        setOpen(list.length > 0);
        setActiveIdx(-1);
      } catch { setResults([]); setOpen(false); }
      finally { setLoading(false); }
    }, 300);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [query]);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (dropRef.current && !dropRef.current.contains(e.target as Node) &&
          inputRef.current && !inputRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActiveIdx((i) => Math.min(i + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter" && activeIdx >= 0) { e.preventDefault(); pick(results[activeIdx]); }
    else if (e.key === "Escape") { setOpen(false); }
  }

  function pick(item: SymbolSearchResult) { setQuery(""); setOpen(false); setResults([]); onSelect(item); }
  function clear() { setQuery(""); setOpen(false); setResults([]); inputRef.current?.focus(); }

  return (
    <div className="relative flex items-center">
      <div className="flex items-center gap-1 h-8 bg-surface-card border border-border-default rounded-md px-2 py-1 w-40 focus-within:border-accent transition-colors">
        <Search size={12} className="text-text-muted shrink-0" />
        <Input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Search symbol..."
          className="bg-transparent text-sm text-text-primary placeholder-text-muted border-0 shadow-none p-0 h-auto w-full font-sans focus-visible:ring-0"
          spellCheck={false}
        />
        {loading && <span className="text-text-muted text-xs shrink-0 animate-pulse">...</span>}
        {query && !loading && (
          <Button variant="ghost" size="icon" onClick={clear} className="h-auto w-auto p-0 text-text-muted hover:text-text-primary transition-colors">
            <X size={11} />
          </Button>
        )}
      </div>
      {open && results.length > 0 && (
        <div ref={dropRef} className="absolute top-full left-0 mt-1 z-50 w-72 bg-surface-card border border-border-default rounded shadow-2xl overflow-hidden">
          {results.map((item, idx) => (
            <Button
              key={`${item.symbol}-${item.exchange}-${idx}`}
              variant="ghost"
              onClick={() => pick(item)}
              className={`w-full flex items-center justify-between px-3 py-2 h-auto text-left transition-colors rounded-none ${idx === activeIdx ? "bg-border-default text-text-primary" : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"}`}
            >
              <span className="flex flex-col gap-0.5">
                <span className="text-xs font-mono font-semibold text-text-primary">{item.symbol}</span>
                {item.name && <span className="text-xs text-text-muted truncate max-w-40">{item.name}</span>}
              </span>
              <span className="flex flex-col items-end gap-0.5">
                <span className="text-xs font-mono text-accent">{item.exchange}</span>
                {item.instrument_type && <span className="text-xxs text-text-muted uppercase">{item.instrument_type}</span>}
              </span>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

interface TextInputOverlayProps { onConfirm: (text: string) => void; onCancel: () => void }

function TextInputOverlay({ onConfirm, onCancel }: TextInputOverlayProps) {
  const [val, setVal] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); }, []);
  return (
    <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 bg-surface-card border border-border-default rounded px-3 py-2 shadow-2xl">
      <Input
        ref={ref}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && val.trim()) onConfirm(val.trim());
          if (e.key === "Escape") onCancel();
        }}
        placeholder="Enter annotation text..."
        className="bg-transparent text-xs font-mono text-text-primary border-0 shadow-none p-0 h-auto w-48 placeholder-text-muted focus-visible:ring-0"
      />
      <Button onClick={() => val.trim() && onConfirm(val.trim())} size="sm" className="text-xs bg-accent text-white px-2 py-0.5 h-auto rounded">Place</Button>
      <Button variant="ghost" size="icon" onClick={onCancel} className="h-auto w-auto text-xs text-text-muted hover:text-loss px-1"><X size={11} /></Button>
    </div>
  );
}

function PeriodInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <Input
      type="number" min={2} max={500} value={value}
      className="w-11 h-6 text-xs font-mono text-center px-1 py-0 ml-auto bg-surface-card border-border-default rounded"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
      onChange={(e) => { const v = parseInt(e.target.value, 10); if (!isNaN(v) && v >= 2 && v <= 500) onChange(v); }}
    />
  );
}

interface IndicatorPaneResizeOverlayProps {
  panes: readonly FlintChartIndicatorPaneControl[];
  onResizeStart: (scaleId: string, event: ReactPointerEvent<HTMLDivElement>) => void;
  onResizeNudge: (scaleId: string, deltaPixels: number) => void;
}

function IndicatorPaneResizeOverlay({
  panes,
  onResizeStart,
  onResizeNudge,
}: IndicatorPaneResizeOverlayProps) {
  if (panes.length === 0) return null;

  const totalStretchFactor = 4 + panes.reduce((sum, pane) => sum + pane.stretchFactor, 0);
  let accumulatedStretchFactor = 4;
  const handles = panes.map((pane) => {
    const topPercent = (accumulatedStretchFactor / totalStretchFactor) * 100;
    accumulatedStretchFactor += pane.stretchFactor;
    return { pane, topPercent };
  });

  return (
    <div
      aria-label="Indicator pane resize controls"
      className="pointer-events-none absolute inset-0 z-20"
    >
      {handles.map(({ pane, topPercent }) => (
        <div
          key={pane.scaleId}
          role="separator"
          aria-label={`Resize ${pane.label} pane`}
          aria-orientation="horizontal"
          aria-valuemin={0.5}
          aria-valuemax={2.5}
          aria-valuenow={pane.stretchFactor}
          tabIndex={0}
          title={`Drag to resize ${pane.label} pane`}
          className="group pointer-events-auto absolute left-2 right-2 h-5 -translate-y-1/2 cursor-row-resize outline-none"
          style={{ top: `${topPercent}%` }}
          onPointerDown={(event) => onResizeStart(pane.scaleId, event)}
          onKeyDown={(event) => {
            if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
            event.preventDefault();
            const step = event.shiftKey ? 40 : 20;
            onResizeNudge(pane.scaleId, event.key === "ArrowUp" ? -step : step);
          }}
        >
          <span className="absolute left-0 right-0 top-1/2 h-px -translate-y-1/2 rounded bg-accent/30 opacity-30 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
          <span className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-accent/30 bg-surface-card/95 px-1.5 py-0.5 text-[10px] font-mono leading-none text-accent opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            {pane.label} {pane.stretchFactor.toFixed(2)}x
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

// Per-panel parameters a layout/preset can pin onto a chart panel (e.g. the
// options-scalper preset pins each of its four charts to a specific instrument).
interface ChartPanelParams {
  symbol?: string;
  exchange?: string;
  interval?: string;
}

function ChartWidget(props: Partial<IDockviewPanelProps> = {}) {
  const track = useTrackBehavior();
  const dataScope = useDataScope();
  useEffect(() => { track("trade", "widgetsUsed"); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const [workspaceWidth, setWorkspaceWidth] = useState(0);

  // When a preset/layout pins a symbol onto this panel, seed from it and treat
  // the chart as "pinned": it must NOT write to (or read back) the single global
  // chart-view key, so multiple pinned charts in one workspace never clobber each
  // other or the user's default chart. Unpinned charts behave exactly as before.
  const pinnedParams = props.params as ChartPanelParams | undefined;
  const isPinned = Boolean(pinnedParams?.symbol);

  // Dockview panel identity — the scope for this chart's indicator and display
  // settings. Null when the chart is rendered outside a panel (tests, embeds),
  // in which case the legacy workspace-wide keys are used unchanged.
  const panelId = props.api?.id ?? null;
  const indicatorSettingsStorageKey = createFlintChartPanelStorageKey(
    FLINT_CHART_INDICATOR_SETTINGS_STORAGE_KEY,
    panelId,
  );
  const displaySettingsStorageKey = createFlintChartPanelStorageKey(
    FLINT_CHART_DISPLAY_SETTINGS_STORAGE_KEY,
    panelId,
  );

  const [initialChartView] = useState(() => (isPinned ? null : loadSavedChartView()));
  const [symbol, setSymbol] = useState(() => pinnedParams?.symbol ?? initialChartView?.symbol ?? DEFAULT_SYMBOL);
  const [exchange, setExchange] = useState(() => pinnedParams?.exchange ?? initialChartView?.exchange ?? DEFAULT_EXCHANGE);
  const [interval, setInterval] = useState(() => pinnedParams?.interval ?? initialChartView?.interval ?? "5m");
  const [intervals, setIntervals] = useState<IntervalOption[]>(STATIC_INTERVALS);
  const [visibleLogicalRange, setVisibleLogicalRange] = useState<FlintChartVisibleLogicalRange | null>(
    () => initialChartView?.visibleLogicalRange ?? null,
  );

  const [ltp, setLtp] = useState<number | null>(null);
  const [change, setChange] = useState<number | null>(null);
  const [changePct, setChangePct] = useState<number | null>(null);
  const [legend, setLegend] = useState<LegendState | null>(null);

  const [drawMode, setDrawMode] = useState<DrawToolType | null>(null);

  // Drawing persistence is keyed by symbol+exchange and versioned by the core
  // chart storage contract. The parser still accepts the old raw-array format.
  const drawingsStorageKey = createFlintChartDrawingsStorageKey({ symbol, exchange });
  const [drawings, setDrawings] = useState<Drawing[]>(() => {
    const initialSymbol = pinnedParams?.symbol ?? initialChartView?.symbol ?? DEFAULT_SYMBOL;
    const initialExchange = pinnedParams?.exchange ?? initialChartView?.exchange ?? DEFAULT_EXCHANGE;
    const initialKey = createFlintChartDrawingsStorageKey({
      symbol: initialSymbol,
      exchange: initialExchange,
    });
    return parseFlintChartDrawings<Time>(localStorage.getItem(initialKey));
  });
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [pendingPoint, setPendingPoint] = useState<DrawingPoint | null>(null);
  const [pendingPoints, setPendingPoints] = useState<DrawingPoint[]>([]);
  const [awaitingText, setAwaitingText] = useState<DrawingPoint | null>(null);
  const visibleLogicalRangeRef = useRef<FlintChartVisibleLogicalRange | null>(
    initialChartView?.visibleLogicalRange ?? null,
  );

  useEffect(() => {
    const node = workspaceRef.current;
    if (!node) return;

    const updateWidth = (width?: number) => {
      const nextWidth = width ?? node.getBoundingClientRect().width;
      if (Number.isFinite(nextWidth)) {
        setWorkspaceWidth((current) =>
          Math.abs(current - nextWidth) < 1 ? current : nextWidth,
        );
      }
    };

    updateWidth();

    if (typeof ResizeObserver === "undefined") {
      const handleResize = () => updateWidth();
      window.addEventListener("resize", handleResize);
      return () => window.removeEventListener("resize", handleResize);
    }

    const observer = new ResizeObserver(([entry]) => {
      updateWidth(entry?.contentRect.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const [initialIndicatorSettings] = useState(() => loadSavedIndicatorSettings(panelId));
  const [chartDisplaySettings, setChartDisplaySettings] = useState(() => loadSavedDisplaySettings(panelId));
  const [indicators, setIndicators] = useState<IndicatorState>(() => ({ ...initialIndicatorSettings.indicators }));
  const [periods, setPeriods] = useState<IndicatorPeriods>(() => ({ ...initialIndicatorSettings.periods }));
  const [indicatorColors, setIndicatorColors] = useState<Record<FlintChartIndicatorKey, FlintChartIndicatorColor>>(
    () => ({ ...initialIndicatorSettings.colors }),
  );
  const [indicatorLineStyles, setIndicatorLineStyles] = useState<Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle>>(
    () => ({ ...initialIndicatorSettings.lineStyles }),
  );
  const [indicatorPaneSizes, setIndicatorPaneSizes] = useState<Record<string, FlintChartIndicatorPaneSize>>(
    () => ({ ...initialIndicatorSettings.paneSizes }),
  );
  const [indicatorPaneStretchFactors, setIndicatorPaneStretchFactors] = useState<FlintChartIndicatorPaneStretchFactors>(
    () => ({ ...initialIndicatorSettings.paneStretchFactors }),
  );

  // Persist drawings to localStorage whenever they change.
  useEffect(() => {
    try {
      localStorage.setItem(drawingsStorageKey, encodeFlintChartDrawings(drawings));
    } catch { /* localStorage quota exceeded — ignore */ }
  }, [drawings, drawingsStorageKey]);

  // Reload drawings from localStorage when symbol/exchange changes.
  useEffect(() => {
    setDrawings(parseFlintChartDrawings<Time>(localStorage.getItem(drawingsStorageKey)));
    setSelectedDrawingId(null);
    setPendingPoint(null);
    setPendingPoints([]);
    setAwaitingText(null);
  // drawingsStorageKey encodes symbol+exchange — run only when the key changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawingsStorageKey]);

  useEffect(() => {
    setSelectedDrawingId((current) =>
      getFlintChartSelectedDrawing(drawings, current) ? current : null,
    );
  }, [drawings]);

  useEffect(() => {
    // A pinned (preset-driven) chart must not persist its symbol as the single
    // global default — that would let one panel in a multi-chart layout clobber
    // the user's default chart and every other pinned chart.
    if (isPinned) return;
    try {
      localStorage.setItem(
        FLINT_CHART_VIEW_STATE_STORAGE_KEY,
        encodeFlintChartViewState({
          symbol,
          exchange,
          interval,
          ...(visibleLogicalRange ? { visibleLogicalRange } : {}),
        }),
      );
    } catch { /* localStorage quota exceeded — ignore */ }
  }, [symbol, exchange, interval, visibleLogicalRange, isPinned]);

  useEffect(() => {
    try {
      localStorage.setItem(
        indicatorSettingsStorageKey,
        encodeFlintChartIndicatorSettings({
          indicators,
          periods,
          colors: indicatorColors,
          lineStyles: indicatorLineStyles,
          paneSizes: indicatorPaneSizes,
          paneStretchFactors: indicatorPaneStretchFactors,
        }),
      );
    } catch { /* localStorage quota exceeded — ignore */ }
  }, [indicatorColors, indicatorLineStyles, indicatorPaneSizes, indicatorPaneStretchFactors, indicators, indicatorSettingsStorageKey, periods]);

  useEffect(() => {
    try {
      localStorage.setItem(
        displaySettingsStorageKey,
        encodeFlintChartDisplaySettings(chartDisplaySettings),
      );
    } catch { /* localStorage quota exceeded — ignore */ }
  }, [chartDisplaySettings, displaySettingsStorageKey]);

  const barsRef = useRef<OhlcvBar[]>([]);
  const timesRef = useRef<Time[]>([]);
  // Stable ref so the OHLCV async closure can read replay state without being
  // a dep of the effect (which would cause unnecessary re-fetches)
  const isReplayingRef = useRef(false);

  // Initialise chart (once)
  const { containerRef, chartRef, candleRef, volumeRef, markersPluginRef, indRef } =
    useChartInit(setLegend);

  useEffect(() => {
    visibleLogicalRangeRef.current = visibleLogicalRange;
  }, [visibleLogicalRange]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const timeScale = chart.timeScale();
    const handleVisibleLogicalRangeChange = (range: LogicalRange | null) => {
      if (!range || !Number.isFinite(range.from) || !Number.isFinite(range.to) || range.to <= range.from) {
        return;
      }
      setVisibleLogicalRange((prev) => {
        if (
          prev &&
          Math.abs(prev.from - range.from) < 0.001 &&
          Math.abs(prev.to - range.to) < 0.001
        ) {
          return prev;
        }
        return { from: range.from, to: range.to };
      });
    };
    timeScale.subscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange);
    return () => timeScale.unsubscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange);
  }, [chartRef]);

  // Apply theme from CSS vars whenever the active theme changes
  const chartTheme = useLightweightChartTheme();
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;
    applyFlintCandlestickTheme(
      chart,
      candle,
      chartTheme,
      createFlintChartDisplaySettingsOptions(chartDisplaySettings),
    );
  }, [chartDisplaySettings, chartTheme, chartRef, candleRef]);

  const handleDrawingCreated = useCallback((drawingId: string) => {
    setSelectedDrawingId(drawingId);
    setDrawMode(null);
    setPendingPoint(null);
    setPendingPoints([]);
    setAwaitingText(null);
  }, []);

  const handleCanvasDrawingHit = useCallback((drawingId: string | null) => {
    setSelectedDrawingId(drawingId);
    setDrawMode(null);
    setPendingPoint(null);
    setPendingPoints([]);
    setAwaitingText(null);
  }, []);

  const handleCanvasDrawingMove = useCallback((drawingId: string, delta: FlintChartDrawingMoveDelta) => {
    setSelectedDrawingId(drawingId);
    setDrawings((prev) => moveFlintChartDrawingByDelta(prev, drawingId, delta));
  }, []);

  const handleCanvasDrawingHandleMove = useCallback((
    drawingId: string,
    handle: FlintChartDrawingHandleId,
    delta: FlintChartDrawingMoveDelta,
  ) => {
    setSelectedDrawingId(drawingId);
    setDrawings((prev) => moveFlintChartDrawingHandleByDelta(prev, drawingId, handle, delta));
  }, []);

  // Drawing tools
  const { toggleDrawMode, undoLastDrawing } = useDrawingTools({
    containerRef, chartRef, candleRef, markersPluginRef,
    drawMode, setDrawMode,
    drawings, setDrawings,
    selectedDrawingId,
    onDrawingCreated: handleDrawingCreated,
    onDrawingHit: handleCanvasDrawingHit,
    onDrawingMove: handleCanvasDrawingMove,
    onDrawingHandleMove: handleCanvasDrawingHandleMove,
    pendingPoint, setPendingPoint,
    pendingPoints, setPendingPoints,
    setAwaitingText,
  });

  const cancelDrawingInteraction = useCallback(() => {
    setDrawMode(null);
    setPendingPoint(null);
    setPendingPoints([]);
    setAwaitingText(null);
  }, []);

  const handleSelectDrawing = useCallback((drawingId: string) => {
    setSelectedDrawingId(drawingId);
    setDrawMode(null);
    setPendingPoint(null);
    setPendingPoints([]);
    setAwaitingText(null);
  }, []);

  const deleteDrawingById = useCallback((drawingId: string) => {
    setDrawings((prev) => {
      const next = removeFlintChartDrawingById(prev, drawingId);
      if (next !== prev) {
        setSelectedDrawingId((current) => current === drawingId ? null : current);
      }
      return next;
    });
    setPendingPoint(null);
    setPendingPoints([]);
    setAwaitingText(null);
  }, []);

  const handleDrawingStyleChange = useCallback((style: FlintChartDrawingStyleInput) => {
    if (!selectedDrawingId) return;
    setDrawings((prev) => updateFlintChartDrawingStyle(prev, selectedDrawingId, style));
  }, [selectedDrawingId]);

  const handleSelectedDrawingHiddenChange = useCallback((drawingId: string, hidden: boolean) => {
    setSelectedDrawingId(drawingId);
    setDrawings((prev) => updateFlintChartDrawingStateById(prev, drawingId, { hidden }));
  }, []);

  const handleSelectedDrawingLockedChange = useCallback((drawingId: string, locked: boolean) => {
    setSelectedDrawingId(drawingId);
    setDrawings((prev) => updateFlintChartDrawingStateById(prev, drawingId, { locked }));
  }, []);

  const deleteSelectedDrawing = useCallback(() => {
    if (!getFlintChartSelectedDrawing(drawings, selectedDrawingId)) return false;
    deleteDrawingById(selectedDrawingId as string);
    return true;
  }, [deleteDrawingById, drawings, selectedDrawingId]);

  const handleUndoLastDrawing = useCallback(() => {
    undoLastDrawing();
    setSelectedDrawingId(null);
    setPendingPoint(null);
    setPendingPoints([]);
  }, [undoLastDrawing]);

  const handleClearAllDrawings = useCallback(() => {
    setDrawings((prev) => removeFlintChartUnlockedDrawings(prev));
    setSelectedDrawingId(null);
    setPendingPoint(null);
    setPendingPoints([]);
  }, []);

  const drawingsHidden = drawings.length > 0 && drawings.every((drawing) => drawing.hidden === true);
  const drawingsLocked = drawings.length > 0 && drawings.every((drawing) => drawing.locked === true);

  const handleToggleAllDrawingsHidden = useCallback(() => {
    setDrawings((prev) => {
      if (prev.length === 0) return prev;
      const nextHidden = !prev.every((drawing) => drawing.hidden === true);
      return updateFlintChartDrawingsHidden(prev, nextHidden);
    });
  }, []);

  const handleToggleAllDrawingsLocked = useCallback(() => {
    setDrawings((prev) => {
      if (prev.length === 0) return prev;
      const nextLocked = !prev.every((drawing) => drawing.locked === true);
      return updateFlintChartDrawingsLocked(prev, nextLocked);
    });
  }, []);

  const handleChartKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    const action = getFlintChartKeyboardAction(event.nativeEvent);
    if (!action) return;
    event.preventDefault();

    if (action.kind === "set-tool") {
      if (action.tool === "cursor") {
        cancelDrawingInteraction();
        return;
      }
      toggleDrawMode(action.tool as DrawToolType);
      return;
    }

    if (action.kind === "cancel-drawing") {
      cancelDrawingInteraction();
      return;
    }

    if (action.kind === "undo-drawing") {
      handleUndoLastDrawing();
      return;
    }

    if (action.kind === "delete-last-drawing") {
      if (!deleteSelectedDrawing()) {
        handleUndoLastDrawing();
      }
      setPendingPoint(null);
      setPendingPoints([]);
      return;
    }

    if (action.kind === "clear-all-drawings") {
      handleClearAllDrawings();
    }
  }, [cancelDrawingInteraction, deleteSelectedDrawing, handleClearAllDrawings, handleUndoLastDrawing, toggleDrawMode]);

  const refreshIndicatorsRef = useRef<(() => void) | null>(null);

  // Indicator series lifecycle
  const { refresh: refreshIndicators } = useIndicators({
    chartRef, candleRef, volumeRef, indRef,
    barsRef, timesRef,
    indicators, periods,
    indicatorColors,
    indicatorLineStyles,
    indicatorPaneSizes,
    indicatorPaneStretchFactors,
  });

  useEffect(() => {
    refreshIndicatorsRef.current = refreshIndicators;
  }, [refreshIndicators]);

  // OI overlay — histogram on separate "oi" price scale, driven by indicators.showOI
  useOIOverlay({ chartRef, symbol, exchange, isVisible: indicators.showOI });

  // Task A: Chart replay — barsRef.current is populated by the OHLCV effect below
  const {
    isReplaying,
    isPlaying,
    replayIndex,
    replaySpeed,
    totalBars: replayTotalBars,
    play: replayPlay,
    pause: replayPause,
    reset: replayReset,
    seek: replaySeek,
    exitReplay,
    enterReplay,
    setSpeed: replaySetSpeed,
  } = useChartReplay(chartRef, candleRef, barsRef);

  // Keep the ref in sync so the OHLCV closure can gate chart writes during replay
  useEffect(() => { isReplayingRef.current = isReplaying; }, [isReplaying]);

  // When replay exits, restore the full bar set onto the chart
  useEffect(() => {
    if (!isReplaying && candleRef.current && volumeRef.current && barsRef.current.length > 0) {
      const bars = barsRef.current;
      const times = timesRef.current;
      const candles = bars.map((b, i) => ({
        time: times[i], open: b.open, high: b.high, low: b.low, close: b.close,
      }));
      const volumes = bars.map((b, i) => ({
        time: times[i], value: b.volume || 0,
        color: b.close >= b.open ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
      }));
      try {
        candleRef.current.setData(candles);
        volumeRef.current.setData(volumes);
        refreshIndicatorsRef.current?.();
        chartRef.current?.timeScale().fitContent();
      } catch { /* ignore */ }
    }
  // Only run when isReplaying transitions to false
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReplaying]);

  // Load available intervals from API once
  useEffect(() => {
    getIntervals()
      .then((raw) => {
        if (!raw) return;
        let list: IntervalOption[] = [];
        if (Array.isArray(raw)) {
          list = raw.map((v) => typeof v === "string" ? { label: v, value: v } : (v as IntervalOption));
        } else if ((raw as { intervals?: string[] }).intervals && Array.isArray((raw as { intervals: string[] }).intervals)) {
          list = (raw as { intervals: string[] }).intervals.map((v) =>
            typeof v === "string" ? { label: v, value: v } : { label: String(v), value: String(v) },
          );
        }
        if (list.length > 0) {
          const apiValues = new Set(list.map((x) => x.value));
          const filtered = STATIC_INTERVALS.filter((x) => apiValues.has(x.value));
          if (filtered.length > 0) setIntervals(filtered);
        }
      })
      .catch(() => { /* use static fallback */ });
  }, []);

  // Fetch OHLCV data with localStorage cache
  useEffect(() => {
    const candle = candleRef.current;
    const volume = volumeRef.current;
    if (!candle || !volume) return;
    // Capture non-null references so the async closure and applyBars can use them safely
    const candleSeries = candle;
    const volumeSeries = volume;
    let cancelled = false;

    // A symbol, interval, mode, account, host, or API-key change creates a new
    // data identity. Remove the previous identity synchronously so an empty or
    // failed response cannot leave stale candles displayed under the new one.
    if (isReplayingRef.current) {
      exitReplay();
      isReplayingRef.current = false;
    }
    barsRef.current = [];
    timesRef.current = [];
    setLegend(null);
    try {
      candleSeries.setData([]);
      volumeSeries.setData([]);
    } catch { /* chart may be disposing */ }
    refreshIndicatorsRef.current?.();

    function applyBars(data: OhlcvBar[]) {
      if (cancelled) return;
      const times: Time[] = data.map((b) => b.timestamp as unknown as Time);
      barsRef.current = data;
      timesRef.current = times;
      // Task A: Don't touch the chart series while replay is active — the replay
      // hook owns the series in that mode. The barsRef update above is still needed
      // so that when replay exits it can restore all bars.
      if (isReplayingRef.current) return;
      const candles = data.map((b, i) => ({
        time: times[i], open: b.open, high: b.high, low: b.low, close: b.close,
      }));
      const volumes = data.map((b, i) => ({
        time: times[i], value: b.volume || 0,
        color: b.close >= b.open ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
      }));
      candleSeries.setData(candles);
      volumeSeries.setData(volumes);
      const timeScale = chartRef.current?.timeScale();
      const savedRange = visibleLogicalRangeRef.current;
      if (savedRange) {
        timeScale?.setVisibleLogicalRange(savedRange);
      } else {
        timeScale?.fitContent();
      }
      refreshIndicatorsRef.current?.();
    }

    (async () => {
      const FIVE_MIN = 5 * 60 * 1000;

      // Show cached data immediately while fetching
      const cached = readOhlcvCache(localStorage, dataScope, symbol, exchange, interval);
      if (cached && cached.data.length > 0) {
        applyBars(cached.data);
        // Skip network request if cache is fresh and market is closed
        if (Date.now() - cached.timestamp < FIVE_MIN && !isMarketHours()) {
          return;
        }
      }

      try {
        const endDate = formatDate(new Date());
        const startDate = getStartDate(interval);
        const data = await getHistory(symbol, exchange, interval, startDate, endDate);
        if (cancelled || !Array.isArray(data) || data.length === 0) return;

        writeOhlcvCache(localStorage, dataScope, symbol, exchange, interval, data as OhlcvBar[]);

        applyBars(data as OhlcvBar[]);
      } catch { /* API unavailable — cached data already shown */ }
    })();

    return () => { cancelled = true; };
  }, [symbol, exchange, interval, dataScope, candleRef, volumeRef, chartRef, exitReplay]);

  // Fetch quote (LTP / change)
  useEffect(() => {
    let cancelled = false;
    setLtp(null);
    setChange(null);
    setChangePct(null);
    (async () => {
      try {
        const q = await getQuotes(symbol, exchange);
        if (cancelled || !q) return;
        const ltpVal = q.ltp ?? null;
        const prevClose = (q as unknown as { prev_close?: number }).prev_close ?? q.close ?? null;
        const chg = ltpVal != null && prevClose != null ? ltpVal - prevClose : null;
        const chgPct = chg != null && prevClose ? (chg / prevClose) * 100 : null;
        if (!cancelled) { setLtp(ltpVal); setChange(chg); setChangePct(chgPct); }
      } catch { /* quote unavailable */ }
    })();
    return () => { cancelled = true; };
  }, [symbol, exchange, dataScope]);

  // Event handlers
  const handleSymbolSelect = useCallback((item: SymbolSearchResult) => {
    setSymbol(item.symbol);
    setExchange(item.exchange);
    visibleLogicalRangeRef.current = null;
    setVisibleLogicalRange(null);
    setLtp(null); setChange(null); setChangePct(null); setLegend(null);
    setDrawings([]); setSelectedDrawingId(null); setPendingPoint(null);
    const chart = chartRef.current;
    if (chart) {
      const ind = indRef.current;
      (Object.keys(ind) as (keyof IndicatorSeriesRefs)[]).forEach((k) => {
        if (ind[k]) { try { chart.removeSeries(ind[k]!); } catch { /* ignore */ } ind[k] = null; }
      });
    }
  }, [chartRef, indRef]);

  const handleIntervalChange = useCallback((v: string) => {
    visibleLogicalRangeRef.current = null;
    setVisibleLogicalRange(null);
    setInterval(v);
  }, []);

  // Standard terminal UX: a watchlist row click (or any widget that writes
  // selectedSymbolAtom) drives the default chart. A pinned chart — one whose
  // Dockview panel params carry an explicit symbol — keeps its instrument and
  // ignores the selection, so multi-chart preset layouts are never clobbered.
  // The current symbol/exchange are deliberately NOT in the deps: the effect
  // reacts only to selection changes, so a symbol picked locally through the
  // chart's own search sticks until the next watchlist click.
  const selectedInstrument = useAtomValue(selectedSymbolAtom);
  useEffect(() => {
    if (isPinned || !selectedInstrument) return;
    if (selectedInstrument.symbol === symbol && selectedInstrument.exchange === exchange) return;
    handleSymbolSelect({
      symbol: selectedInstrument.symbol,
      exchange: selectedInstrument.exchange,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedInstrument, isPinned, handleSymbolSelect]);

  const handleTextConfirm = useCallback((text: string) => {
    if (!awaitingText) return;
    const creation = advanceFlintChartDrawingDraft<Time>({
      tool: drawMode === "callout" ? "callout" : "text",
      point: awaitingText,
      label: text,
    });
    if (!creation.drawing) return;
    setDrawings((prev) => [...prev, creation.drawing as Drawing]);
    setSelectedDrawingId(creation.drawing.id);
    setDrawMode(null);
    setAwaitingText(null);
  }, [awaitingText, drawMode]);

  const handleTextCancel = useCallback(() => { setAwaitingText(null); }, []);

  const toggleIndicator = useCallback((key: keyof IndicatorState, value: boolean) => {
    setIndicators((prev) => ({ ...prev, [key]: value }));
  }, []);

  const setIndicatorPaneSize = useCallback((scaleId: string, size: FlintChartIndicatorPaneSize) => {
    setIndicatorPaneSizes((prev) => ({ ...prev, [scaleId]: size }));
    setIndicatorPaneStretchFactors((prev) => ({
      ...prev,
      [scaleId]: FLINT_CHART_INDICATOR_PANE_STRETCH_FACTORS[size],
    }));
  }, []);

  // Indicator settings modal
  const [indicatorModalOpen, setIndicatorModalOpen] = useState(false);

  const handleIndicatorApply = useCallback(
    (
      newIndicators: IndicatorState,
      newPeriods: IndicatorPeriods,
      newColors: Record<FlintChartIndicatorKey, FlintChartIndicatorColor>,
      newLineStyles: Record<FlintChartIndicatorKey, FlintChartIndicatorLineStyle>,
    ) => {
      setIndicators(newIndicators);
      setPeriods(newPeriods);
      setIndicatorColors(newColors);
      setIndicatorLineStyles(newLineStyles);
    },
    [],
  );

  // Derived display values
  const isPositive = change == null ? null : change >= 0;
  const changeColor = change == null ? "text-text-secondary" : isPositive ? "text-profit" : "text-loss";
  const activeIndicatorCount = getFlintChartActiveIndicatorCount(indicators);
  const activePaneControls = createFlintChartIndicatorPaneControls(
    indicators,
    indicatorPaneSizes,
    indicatorPaneStretchFactors,
  );
  const drawingCount = drawings.length;
  const selectedDrawing = getFlintChartSelectedDrawing(drawings, selectedDrawingId);
  const selectedDrawingStyle = selectedDrawing ? getFlintChartDrawingStyle(selectedDrawing) : null;
  const workspaceLayout = getFlintChartWorkspaceLayout(workspaceWidth);

  const updateIndicatorPaneStretchFactor = useCallback((
    scaleId: string,
    startStretchFactor: number,
    deltaPixels: number,
  ) => {
    setIndicatorPaneStretchFactors((prev) =>
      resizeFlintChartIndicatorPaneStretchFactors({
        paneStretchFactors: prev,
        scaleId,
        startStretchFactor,
        deltaPixels,
      }),
    );
  }, []);

  const handleIndicatorPaneResizeStart = useCallback((
    scaleId: string,
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    const pane = activePaneControls.find((candidate) => candidate.scaleId === scaleId);
    if (!pane) return;
    event.preventDefault();
    event.stopPropagation();

    const startY = event.clientY;
    const startStretchFactor = pane.stretchFactor;
    const handlePointerMove = (moveEvent: PointerEvent) => {
      updateIndicatorPaneStretchFactor(
        scaleId,
        startStretchFactor,
        moveEvent.clientY - startY,
      );
    };
    const handlePointerUp = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
  }, [activePaneControls, updateIndicatorPaneStretchFactor]);

  const handleIndicatorPaneResizeNudge = useCallback((scaleId: string, deltaPixels: number) => {
    const pane = activePaneControls.find((candidate) => candidate.scaleId === scaleId);
    if (!pane) return;
    updateIndicatorPaneStretchFactor(scaleId, pane.stretchFactor, deltaPixels);
  }, [activePaneControls, updateIndicatorPaneStretchFactor]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      ref={workspaceRef}
      className="flex flex-col h-full w-full bg-surface-base overflow-hidden focus:outline-none focus:ring-1 focus:ring-accent/30"
      data-tour-target="chart"
      data-chart-layout={workspaceLayout.compact ? "compact" : "standard"}
      tabIndex={0}
      onKeyDown={handleChartKeyDown}
      aria-label="Interactive chart workspace"
    >

      {/* Header */}
      <div className="flex flex-col gap-1 px-2 py-1 bg-surface-base border-b border-border-default shrink-0">
        <div className="flex items-center gap-2 min-w-0 overflow-hidden">
          <SymbolSearch onSelect={handleSymbolSelect} />
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-sm font-heading font-semibold text-text-primary leading-none whitespace-nowrap">{symbol}</span>
            <span className="text-xs text-text-muted whitespace-nowrap">{exchange}</span>
            {dataScope === "explore:mock" && (
              <span className="rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-xxs text-warning" role="status">
                Sample history
              </span>
            )}
            {ltp != null && <span className="text-lg font-mono font-bold text-text-primary leading-none whitespace-nowrap">{formatPrice(ltp)}</span>}
            {change != null && (
              <span className={`flex items-center gap-0.5 text-xs font-mono whitespace-nowrap ${changeColor}`}>
                {isPositive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                {formatChange(change)} ({formatChangePct(changePct)})
              </span>
            )}
          </div>
        </div>
        <div className="flex min-w-0 items-center gap-2 overflow-x-auto overflow-y-hidden pb-0.5">
          {legend && <FlintChartLegend legend={legend} />}
          <FlintChartIntervalPills
            intervals={intervals}
            active={interval}
            onSelect={handleIntervalChange}
            className="shrink-0"
          />
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-1 px-2 py-0.5 bg-surface-base border-b border-border-default shrink-0 flex-wrap min-h-7">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-xs font-sans gap-1 text-text-secondary hover:text-text-primary">
              <BarChart2 size={11} />
              Indicators
              {activeIndicatorCount > 0 && (
                <span className="ml-0.5 bg-accent text-white rounded-full min-w-[18px] h-[18px] flex items-center justify-center text-xxs leading-none">{activeIndicatorCount}</span>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="max-h-[var(--radix-dropdown-menu-content-available-height)] w-56 overflow-y-auto overscroll-contain bg-surface-card border-border-default text-text-primary">
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">Overlays</DropdownMenuLabel>
            <DropdownMenuCheckboxItem checked={indicators.showEMA20} onCheckedChange={(v) => toggleIndicator("showEMA20", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 inline-block shrink-0" />EMA
              <PeriodInput value={periods.ema1} onChange={(v) => setPeriods((p) => ({ ...p, ema1: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showEMA50} onCheckedChange={(v) => toggleIndicator("showEMA50", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-500 inline-block shrink-0" />EMA
              <PeriodInput value={periods.ema2} onChange={(v) => setPeriods((p) => ({ ...p, ema2: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showSMA} onCheckedChange={(v) => toggleIndicator("showSMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-cyan-500 inline-block shrink-0" />SMA
              <PeriodInput value={periods.sma} onChange={(v) => setPeriods((p) => ({ ...p, sma: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showWMA} onCheckedChange={(v) => toggleIndicator("showWMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-lime-500 inline-block shrink-0" />WMA
              <PeriodInput value={periods.wma} onChange={(v) => setPeriods((p) => ({ ...p, wma: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showBB} onCheckedChange={(v) => toggleIndicator("showBB", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />BB
              <PeriodInput value={periods.bbPeriod} onChange={(v) => setPeriods((p) => ({ ...p, bbPeriod: v }))} />
              <PeriodInput value={periods.bbMult} onChange={(v) => setPeriods((p) => ({ ...p, bbMult: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showSupertrend} onCheckedChange={(v) => toggleIndicator("showSupertrend", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-profit inline-block shrink-0" />Supertrend
              <PeriodInput value={periods.stPeriod} onChange={(v) => setPeriods((p) => ({ ...p, stPeriod: v }))} />
              <PeriodInput value={periods.stFactor} onChange={(v) => setPeriods((p) => ({ ...p, stFactor: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showVWAP} onCheckedChange={(v) => toggleIndicator("showVWAP", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-fuchsia-400 inline-block shrink-0" />VWAP
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showIchimoku} onCheckedChange={(v) => toggleIndicator("showIchimoku", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-profit inline-block shrink-0" />Ichimoku Cloud
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showPivot} onCheckedChange={(v) => toggleIndicator("showPivot", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />Pivot Points
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showDEMA} onCheckedChange={(v) => toggleIndicator("showDEMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />DEMA
              <PeriodInput value={periods.dema} onChange={(v) => setPeriods((p) => ({ ...p, dema: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showHullMA} onCheckedChange={(v) => toggleIndicator("showHullMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-purple-500 inline-block shrink-0" />Hull MA
              <PeriodInput value={periods.hull} onChange={(v) => setPeriods((p) => ({ ...p, hull: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showParabolicSAR} onCheckedChange={(v) => toggleIndicator("showParabolicSAR", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-yellow-400 inline-block shrink-0" />Parabolic SAR
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showKeltner} onCheckedChange={(v) => toggleIndicator("showKeltner", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />Keltner
              <PeriodInput value={periods.keltner} onChange={(v) => setPeriods((p) => ({ ...p, keltner: v }))} />
              <PeriodInput value={periods.keltnerMult} onChange={(v) => setPeriods((p) => ({ ...p, keltnerMult: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showVWMA} onCheckedChange={(v) => toggleIndicator("showVWMA", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-teal-400 inline-block shrink-0" />VWMA
              <PeriodInput value={periods.vwma} onChange={(v) => setPeriods((p) => ({ ...p, vwma: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator className="bg-border-default" />
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">Volume</DropdownMenuLabel>
            <DropdownMenuCheckboxItem checked={indicators.showVolume} onCheckedChange={(v) => toggleIndicator("showVolume", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-slate-500 inline-block shrink-0" />Volume
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showOBV} onCheckedChange={(v) => toggleIndicator("showOBV", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-slate-400 inline-block shrink-0" />OBV
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showOI} onCheckedChange={(v) => toggleIndicator("showOI", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-indigo-500 inline-block shrink-0" />OI Overlay
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator className="bg-border-default" />
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">Oscillators</DropdownMenuLabel>
            <DropdownMenuCheckboxItem checked={indicators.showRSI} onCheckedChange={(v) => toggleIndicator("showRSI", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-purple-500 inline-block shrink-0" />RSI
              <PeriodInput value={periods.rsi} onChange={(v) => setPeriods((p) => ({ ...p, rsi: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showMACD} onCheckedChange={(v) => toggleIndicator("showMACD", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 inline-block shrink-0" />MACD (12, 26, 9)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showStoch} onCheckedChange={(v) => toggleIndicator("showStoch", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-500 inline-block shrink-0" />Stochastic (14, 3, 3)
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showATR} onCheckedChange={(v) => toggleIndicator("showATR", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-orange-400 inline-block shrink-0" />ATR
              <PeriodInput value={periods.atr} onChange={(v) => setPeriods((p) => ({ ...p, atr: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showADX} onCheckedChange={(v) => toggleIndicator("showADX", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400 inline-block shrink-0" />ADX
              <PeriodInput value={periods.adx} onChange={(v) => setPeriods((p) => ({ ...p, adx: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showWilliamsR} onCheckedChange={(v) => toggleIndicator("showWilliamsR", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-pink-400 inline-block shrink-0" />Williams %R
              <PeriodInput value={periods.wr} onChange={(v) => setPeriods((p) => ({ ...p, wr: v }))} />
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked={indicators.showCCI} onCheckedChange={(v) => toggleIndicator("showCCI", v)} className="text-xs gap-2">
              <span className="w-2 h-2 rounded-full bg-sky-400 inline-block shrink-0" />CCI
              <PeriodInput value={periods.cci} onChange={(v) => setPeriods((p) => ({ ...p, cci: v }))} />
            </DropdownMenuCheckboxItem>
            {activePaneControls.length > 0 && (
              <>
                <DropdownMenuSeparator className="bg-border-default" />
                <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">Pane size</DropdownMenuLabel>
                <div className="space-y-1 px-2 pb-1" role="group" aria-label="Indicator pane size controls">
                  {activePaneControls.map((pane) => (
                    <div key={pane.scaleId} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-xs text-text-secondary">{pane.label}</span>
                      <div className="grid grid-cols-3 rounded border border-border-default bg-surface-base p-0.5" role="group" aria-label={`${pane.label} pane size`}>
                        {FLINT_CHART_INDICATOR_PANE_SIZE_OPTIONS.map((size) => {
                          const active = pane.size === size;
                          return (
                            <button
                              key={size}
                              type="button"
                              aria-label={`Set ${pane.label} pane to ${FLINT_CHART_INDICATOR_PANE_SIZE_LABELS[size]}`}
                              aria-pressed={active}
                              title={FLINT_CHART_INDICATOR_PANE_SIZE_LABELS[size]}
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                setIndicatorPaneSize(pane.scaleId, size);
                              }}
                              className={`h-5 w-6 rounded text-[10px] font-semibold leading-none transition-colors ${
                                active
                                  ? "bg-accent text-white"
                                  : "text-text-muted hover:bg-surface-hover hover:text-text-primary"
                              }`}
                            >
                              {FLINT_CHART_INDICATOR_PANE_SIZE_SHORT_LABELS[size]}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              title="Chart display settings"
              className="flex items-center justify-center w-6 h-6 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
              aria-label="Open chart display settings"
            >
              <SlidersHorizontal size={12} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-44 bg-surface-card border-border-default text-text-primary">
            <DropdownMenuLabel className="text-xs text-text-muted uppercase tracking-wider px-2 py-1">Chart display</DropdownMenuLabel>
            <DropdownMenuCheckboxItem
              checked={chartDisplaySettings.gridVisible}
              onCheckedChange={(checked) => setChartDisplaySettings((prev) => ({ ...prev, gridVisible: checked === true }))}
              onSelect={(event) => event.preventDefault()}
              className="text-xs gap-2"
            >
              Grid
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={chartDisplaySettings.crosshairVisible}
              onCheckedChange={(checked) => setChartDisplaySettings((prev) => ({ ...prev, crosshairVisible: checked === true }))}
              onSelect={(event) => event.preventDefault()}
              className="text-xs gap-2"
            >
              Crosshair
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={chartDisplaySettings.wheelZoom}
              onCheckedChange={(checked) => setChartDisplaySettings((prev) => ({ ...prev, wheelZoom: checked === true }))}
              onSelect={(event) => event.preventDefault()}
              className="text-xs gap-2"
            >
              Wheel zoom
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem
              checked={chartDisplaySettings.dragScroll}
              onCheckedChange={(checked) => setChartDisplaySettings((prev) => ({ ...prev, dragScroll: checked === true }))}
              onSelect={(event) => event.preventDefault()}
              className="text-xs gap-2"
            >
              Drag scroll
            </DropdownMenuCheckboxItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Indicator settings modal trigger */}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIndicatorModalOpen(true)}
          title="Indicator settings"
          className="flex items-center justify-center w-6 h-6 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
          aria-label="Open indicator settings"
        >
          <Settings2 size={12} />
        </Button>

        {/* Task A: Replay toggle */}
        <Button
          variant="ghost"
          onClick={isReplaying ? exitReplay : enterReplay}
          title={isReplaying ? "Exit replay mode" : "Replay loaded OHLCV bars"}
          disabled={barsRef.current.length === 0}
          className={`flex items-center gap-1 px-2 py-1 h-auto rounded text-xs transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
            isReplaying
              ? "bg-accent/15 text-accent border border-accent/40"
              : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
          }`}
        >
          <History size={11} />
          <span>Replay</span>
        </Button>

        <div className="w-px h-4 bg-border-default mx-0.5" />

        {/* Drawing count + undo/clear in the header */}
        {drawingCount > 0 && (
          <>
            <Button variant="ghost" onClick={handleUndoLastDrawing} title="Undo last drawing" className="flex items-center gap-1 px-2 py-1 h-auto rounded text-xs text-text-secondary hover:text-loss hover:bg-surface-hover transition-colors">
              <X size={10} /><span>Undo</span>
            </Button>
            {drawingCount > 1 && (
              <Button variant="ghost" onClick={handleClearAllDrawings} title="Clear all drawings" className="flex items-center gap-1 px-2 py-1 h-auto rounded text-xs text-text-secondary hover:text-loss hover:bg-surface-hover transition-colors">
                <Trash2 size={10} /><span>Clear</span>
              </Button>
            )}
          </>
        )}

        <FlintChartDrawStatus<DrawToolType>
          drawMode={drawMode}
          drawingCount={drawingCount}
          pendingPoint={pendingPoint}
          pendingPoints={pendingPoints}
          awaitingText={awaitingText}
          twoClickTools={FLINT_CHART_TWO_CLICK_TOOLS}
          threeClickTools={FLINT_CHART_THREE_CLICK_TOOLS}
          className="ml-1"
        />

        {selectedDrawing && selectedDrawingStyle && (
          <FlintChartDrawingInspector<Time>
            drawing={selectedDrawing}
            value={selectedDrawingStyle}
            onStyleChange={handleDrawingStyleChange}
            onToggleHidden={handleSelectedDrawingHiddenChange}
            onToggleLocked={handleSelectedDrawingLockedChange}
            onDeleteDrawing={deleteDrawingById}
            className="ml-auto"
          />
        )}

        <FlintChartDrawingList<Time>
          drawings={drawings}
          selectedDrawingId={selectedDrawingId}
          onSelectDrawing={handleSelectDrawing}
          onDeleteDrawing={deleteDrawingById}
          className={selectedDrawing ? "max-w-full flex-1" : "ml-auto max-w-full flex-1"}
        />
      </div>

      {/* Chart area — DrawingToolbar on left, canvas on right */}
      <div
        className={`flex flex-1 min-h-0 overflow-hidden ${
          workspaceLayout.compact ? "flex-col" : "flex-row"
        }`}
      >
        <FlintChartDrawingToolbar<DrawToolType>
          drawMode={drawMode}
          onToggle={toggleDrawMode}
          onClearAll={handleClearAllDrawings}
          onHideAll={handleToggleAllDrawingsHidden}
          onLockAll={handleToggleAllDrawingsLocked}
          drawingsHidden={drawingsHidden}
          drawingsLocked={drawingsLocked}
          orientation={workspaceLayout.toolbarOrientation}
        />
        <div className="relative flex-1 min-w-0">
          <div
            ref={containerRef}
            className="w-full h-full"
            style={{ cursor: drawMode !== null ? "crosshair" : "default" }}
          />
          <IndicatorPaneResizeOverlay
            panes={activePaneControls}
            onResizeStart={handleIndicatorPaneResizeStart}
            onResizeNudge={handleIndicatorPaneResizeNudge}
          />
          {awaitingText !== null && (
            <TextInputOverlay onConfirm={handleTextConfirm} onCancel={handleTextCancel} />
          )}
        </div>
      </div>

      {/* Task A: Replay control bar — only shown while replay mode is active */}
      {isReplaying && (
        <ReplayBar
          isPlaying={isPlaying}
          replayIndex={replayIndex}
          totalBars={replayTotalBars}
          replaySpeed={replaySpeed}
          onPlay={replayPlay}
          onPause={replayPause}
          onReset={replayReset}
          onSeek={replaySeek}
          onSetSpeed={replaySetSpeed}
          onExitReplay={exitReplay}
        />
      )}

      {/* Indicator settings modal */}
      <IndicatorSettingsModal
        open={indicatorModalOpen}
        onClose={() => setIndicatorModalOpen(false)}
        indicators={indicators}
        periods={periods}
        colors={indicatorColors}
        lineStyles={indicatorLineStyles}
        onApply={handleIndicatorApply}
      />
    </div>
  );
}

export default memo(ChartWidget);
