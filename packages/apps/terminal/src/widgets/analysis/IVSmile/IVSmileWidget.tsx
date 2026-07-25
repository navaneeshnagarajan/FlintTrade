/**
 * IVSmileWidget — canonical implied-volatility curve surface for the terminal.
 *
 * Two presentations of ONE fetch, chosen by the Dockview panel parameter
 * `params.view`:
 *   • "smile" (default) — the Plotly call/put IV curves, multi-expiry overlay,
 *     hover readout and ATM reference line.
 *   • "skew"            — the presentation of the retired IVSkew widget: the
 *     shared `FlintBandedLineChart` primitive with a solid CE line, a dashed PE
 *     line and an ATM dot per expiry. The vertical gap between the two lines at
 *     a strike IS the put-minus-call skew there; the 25Δ figure in the header
 *     is the same difference taken at the 25-delta wings.
 *
 * CHART LIBRARIES (deliberate, not an oversight): the smile view stays on
 * Plotly, the skew view stays on the design-system SVG primitive. The skew
 * view's tests pin `data-flint-chart="banded-line"` and the absence of
 * hand-rolled local SVG, which is how the shared primitive keeps its callers;
 * rewriting the skew view onto Plotly would have retired those invariants for
 * nothing. Plotly earns its place on the smile view for the per-point hover
 * template and paper-referenced ATM annotation the primitive does not model.
 *
 * DATA HONESTY (absorbed from IVSkew, which had the stricter posture):
 *   - Four-state provenance badge: Live / Sample data / Loading / Unavailable.
 *   - Fail-closed live gate — a connected payload is promoted to "Live" ONLY on
 *     an explicit `is_sample_data: false`. A connected response that is missing
 *     the flag, or that carries `is_sample_data: true`, renders as Unavailable;
 *     it is never drawn as live IV.
 *   - Deterministic sample curves are limited to the disconnected Explore
 *     state, where they render behind a FeatureTeaser under a "Sample data"
 *     badge.
 *   - No refresh control. Both views auto-refresh every 30 s during market
 *     hours; a button that cannot refetch a disabled or disconnected query is
 *     a deceptive affordance, which is why IVSkew removed its own.
 *
 * SCALE: every payload goes through `mapIVSmileToSkew`, whose percent-vs-decimal
 * detection is what stops a legacy percentage-points response rendering at 100×.
 *
 * EXPIRY: the widget resolves the nearest FUTURE expiry itself (shared
 * `selectFutureExpiry`) and lets the operator override it by typing up to three
 * comma-separated expiries. It never sends an empty expiry list, because the
 * backend fills that in with a hard-coded label (`analysis_routes.py`), which
 * would render a stale contract's curve as if it were the current one.
 */

import { useState, useMemo, useEffect, useCallback, memo } from "react";
import { Activity, AlertCircle, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import type { IDockviewPanelProps } from "dockview-react";
import { FlintBandedLineChart } from "@flinttrade/design-system";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIVSmile } from "./useIVSmile";
import { SAMPLE_IV_SMILE_DATA } from "./sampleData";
import { mapIVSmileToSkew } from "./ivSkewTransform";
import type { NormalisedIVData, NormalisedIVPoint } from "./ivSkewTransform";
import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { getExpiry } from "@/services/api";
import { selectFutureExpiry } from "@/lib/optionSymbols";
import { SYMBOLS as OPTION_SYMBOLS } from "@/widgets/analysis/OptionChain/types";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { cn } from "@/lib/utils";
import type { Data, Layout } from "plotly.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Index underlyings offered here. The exchange is NOT kept in a local map —
 * it is resolved from the canonical option-chain symbol table, so NFO/BFO
 * routing cannot drift away from the option chain's.
 */
const SYMBOL_CHOICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

/** Colour palette: up to 3 expiry curves. */
const CURVE_COLORS = ["#6366f1", "#f59e0b", "#22c55e"] as const;

type OptionTypeFilter = "Both" | "CE" | "PE";
type XAxisMode = "Strike" | "Moneyness";

/** Presentation of the curves. `skew` is the retired IVSkew widget's view. */
type ViewMode = "smile" | "skew";

const VIEW_MODES: readonly ViewMode[] = ["smile", "skew"];

const VIEW_LABELS: Record<ViewMode, string> = { smile: "Smile", skew: "Skew" };

function isViewMode(value: unknown): value is ViewMode {
  return typeof value === "string" && (VIEW_MODES as readonly string[]).includes(value);
}

/** Resolves the Dockview `params.view` panel parameter, defaulting to smile. */
function resolveViewMode(value: unknown): ViewMode {
  return isViewMode(value) ? value : "smile";
}

/**
 * Live provenance is accepted only when the backend explicitly attests
 * `is_sample_data: false`. Missing or malformed flags fail closed.
 */
function carriesExplicitLiveFlag(payload: unknown): boolean {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as { is_sample_data?: unknown }).is_sample_data === false
  );
}

// ---------------------------------------------------------------------------
// Skew view — chart adapter (from the retired IVSkew widget)
// ---------------------------------------------------------------------------

interface ChartPoint { x: number; iv: number }

interface CurveOverlay {
  label: string;
  color: string;
  cePoints: ChartPoint[];
  pePoints: ChartPoint[];
  atmX: number;
  atmIV: number;
}

function buildOverlays(data: NormalisedIVData, xMode: XAxisMode): CurveOverlay[] {
  return data.curves.slice(0, 3).map((curve, idx) => {
    const xOf = (p: NormalisedIVPoint) => xMode === "Moneyness" ? p.moneyness : p.strike;
    const cePoints = curve.points
      .filter((p) => p.call_iv > 0)
      .map((p) => ({ x: xOf(p), iv: p.call_iv * 100 }));
    const pePoints = curve.points
      .filter((p) => p.put_iv > 0)
      .map((p) => ({ x: xOf(p), iv: p.put_iv * 100 }));
    const atmX = xMode === "Moneyness" ? 1.0 : curve.atm_strike;
    return {
      label: curve.expiry,
      color: CURVE_COLORS[idx % CURVE_COLORS.length],
      cePoints,
      pePoints,
      atmX,
      atmIV: curve.atm_iv * 100,
    };
  });
}

function buildIVSkewChart(
  overlays: CurveOverlay[],
  xMode: XAxisMode,
  optionType: OptionTypeFilter,
) {
  const showCE = optionType !== "PE";
  const showPE = optionType !== "CE";
  const visible = overlays.flatMap((o) => [
    ...(showCE ? o.cePoints : []),
    ...(showPE ? o.pePoints : []),
  ]);
  const allX = visible.map((p) => p.x);
  const allY = visible.map((p) => p.iv);
  const minX = allX.length > 0 ? Math.min(...allX) : 0;
  const maxX = allX.length > 0 ? Math.max(...allX) : 1;
  const minY = Math.min(0, ...(allY.length > 0 ? allY : [0]));
  const maxY = Math.max(...(allY.length > 0 ? allY : [1])) * 1.08;
  const safeMaxY = maxY > minY ? maxY : minY + 1;
  const firstOverlay = overlays[0];

  const series = overlays.flatMap((overlay) => [
    ...(showCE ? [{
      id: `${overlay.label}-ce`,
      label: `${overlay.label} CE`,
      color: overlay.color,
      strokeWidth: 1.5,
      points: overlay.cePoints.map((point) => ({
        x: point.x,
        y: point.iv,
        label: `${overlay.label} CE ${point.iv.toFixed(1)}%`,
      })),
    }] : []),
    ...(showPE ? [{
      id: `${overlay.label}-pe`,
      label: `${overlay.label} PE`,
      color: overlay.color,
      dash: "4,2",
      strokeWidth: 1.5,
      points: overlay.pePoints.map((point) => ({
        x: point.x,
        y: point.iv,
        label: `${overlay.label} PE ${point.iv.toFixed(1)}%`,
      })),
    }] : []),
  ]);
  // ATM dot per curve — the anchor the whole skew is read against.
  const markers = overlays.map((overlay) => ({
    id: `${overlay.label}-atm`,
    label: `${overlay.label} ATM ${overlay.atmIV.toFixed(1)}%`,
    x: overlay.atmX,
    y: overlay.atmIV,
    color: overlay.color,
    radius: 3,
  }));
  const yStep = Math.ceil((safeMaxY - minY) / 4) || 1;
  const yTicks: number[] = [];
  for (let value = Math.ceil(minY / yStep) * yStep; value <= safeMaxY; value += yStep) {
    yTicks.push(value);
  }

  return {
    series,
    markers,
    xDomain: [minX, maxX > minX ? maxX : minX + 1] as const,
    yDomain: [minY, safeMaxY] as const,
    yTicks,
    referenceLines: firstOverlay
      ? [{ axis: "x" as const, value: firstOverlay.atmX, color: "#6366f1", dash: "3,2" }]
      : [],
    xAxisLabel: xMode === "Moneyness" ? "Moneyness" : "Strike",
  };
}

// ---------------------------------------------------------------------------
// Skew view — legend (expiry colours + the CE solid / PE dashed convention)
// ---------------------------------------------------------------------------

interface LegendProps {
  overlays: { label: string; color: string }[];
  optionType: OptionTypeFilter;
}

function ChartLegend({ overlays, optionType }: LegendProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-1 text-xxs text-text-muted">
      {overlays.map((o) => (
        <span key={o.label} className="flex items-center gap-1">
          <span className="inline-block w-3 h-px" style={{ backgroundColor: o.color, height: 2 }} />
          {o.label}
        </span>
      ))}
      {optionType !== "PE" && (
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 border-t border-[#888]" aria-hidden="true" style={{ borderTopWidth: 1.5 }} />
          CE
        </span>
      )}
      {optionType !== "CE" && (
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 border-t border-dashed border-[#888]" aria-hidden="true" style={{ borderTopWidth: 1.5 }} />
          PE
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel params
// ---------------------------------------------------------------------------

interface IVSmilePanelParams {
  /** Initial view — how the retired `ivskew` id selects its old presentation. */
  view?: string;
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function IVSmileWidget(props: IDockviewPanelProps) {
  const panelParams = props.params as IVSmilePanelParams | undefined;
  const panelView = panelParams?.view;

  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [view, setView] = useState<ViewMode>(() => resolveViewMode(panelView));
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiriesInput, setExpiriesInput] = useState("");
  const [optionType, setOptionType] = useState<OptionTypeFilter>("Both");
  const [xMode, setXMode] = useState<XAxisMode>("Strike");
  const [autoExpiry, setAutoExpiry] = useState<string | null>(null);
  const [expiryLoading, setExpiryLoading] = useState(false);
  const [expiryUnavailable, setExpiryUnavailable] = useState(false);

  const exchange = useMemo(
    () => OPTION_SYMBOLS.find((s) => s.label === symbol)?.exchange ?? "NFO",
    [symbol],
  );

  const typedExpiries = useMemo(
    () =>
      expiriesInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .slice(0, 3),
    [expiriesInput],
  );

  // Resolve the nearest future expiry ourselves. Sending none would hand the
  // choice to the backend's hard-coded default label.
  useEffect(() => {
    setAutoExpiry(null);
    setExpiryUnavailable(false);
    if (!isConnected) {
      setExpiryLoading(false);
      return;
    }

    let cancelled = false;
    setExpiryLoading(true);
    void getExpiry(symbol, exchange, "options")
      .then((response) => {
        if (cancelled) return;
        const expiries = Array.isArray(response) ? response : response.expiry ?? [];
        const selected = selectFutureExpiry(expiries);
        setAutoExpiry(selected);
        setExpiryUnavailable(selected === null);
      })
      .catch(() => {
        if (!cancelled) setExpiryUnavailable(true);
      })
      .finally(() => {
        if (!cancelled) setExpiryLoading(false);
      });
    return () => { cancelled = true; };
  }, [exchange, isConnected, symbol]);

  // A typed expiry always wins over the auto-selected one.
  const expiryDates = useMemo(
    () => (typedExpiries.length > 0 ? typedExpiries : autoExpiry ? [autoExpiry] : []),
    [autoExpiry, typedExpiries],
  );

  const { data: liveData, isLoading, isError, error } = useIVSmile(
    symbol,
    exchange,
    expiryDates.length > 0 ? expiryDates : undefined,
    isConnected,
  );

  // Fail closed: only an explicit `is_sample_data: false` is live provenance.
  const livePayload = isConnected && !isError && carriesExplicitLiveFlag(liveData)
    ? liveData
    : null;

  const normalised = useMemo(
    () => mapIVSmileToSkew(isConnected ? livePayload : SAMPLE_IV_SMILE_DATA),
    [isConnected, livePayload],
  );

  const isLive = isConnected && normalised != null && normalised.curves.length > 0;
  const isSample = !isConnected;
  const loading = isConnected && (expiryLoading || isLoading);

  const firstCurve = normalised?.curves[0];
  const atmIV = firstCurve?.atm_iv ?? null;
  const skew25d = firstCurve?.skew_25delta ?? null;

  useEffect(() => {
    track("trade", view === "skew" ? "widget_view_iv_skew" : "widget_view_iv_smile");
  }, [track, view]);

  // Persist the chosen view into the panel params so a saved layout reopens in
  // the same presentation (this is also how the retired `ivskew` id survives).
  const handleViewChange = useCallback((next: ViewMode) => {
    if (next === view) return;
    setView(next);
    props.api.updateParameters({ ...(panelParams ?? {}), view: next });
  }, [panelParams, props.api, view]);

  // ---- Skew view geometry -------------------------------------------------
  const overlays = useMemo(
    () => (normalised ? buildOverlays(normalised, xMode) : []),
    [normalised, xMode],
  );
  const skewChart = useMemo(
    () => buildIVSkewChart(overlays, xMode, optionType),
    [optionType, overlays, xMode],
  );

  // ---- Smile view geometry ------------------------------------------------
  const { plotData, plotLayout } = useMemo<{
    plotData: Data[];
    plotLayout: Partial<Layout>;
  }>(() => {
    if (!normalised?.curves.length) return { plotData: [], plotLayout: {} };

    const traces: Data[] = [];
    const firstAtmStrike = normalised.curves[0].atm_strike;

    normalised.curves.slice(0, 3).forEach((curve, idx) => {
      const color = CURVE_COLORS[idx % CURVE_COLORS.length];
      const xVals = curve.points.map((p) =>
        xMode === "Moneyness" ? p.moneyness : p.strike,
      );

      if (optionType === "CE" || optionType === "Both") {
        traces.push({
          type: "scatter",
          mode: "lines+markers",
          name: `${curve.expiry} CE`,
          x: xVals,
          y: curve.points.map((p) => p.call_iv * 100),
          line: { color, width: 1.5, dash: "solid" },
          marker: { size: 3 },
          hovertemplate: `${curve.expiry} CE<br>${xMode}: %{x}<br>IV: %{y:.1f}%<extra></extra>`,
        } as Data);
      }

      if (optionType === "PE" || optionType === "Both") {
        traces.push({
          type: "scatter",
          mode: "lines+markers",
          name: `${curve.expiry} PE`,
          x: xVals,
          y: curve.points.map((p) => p.put_iv * 100),
          line: { color, width: 1.5, dash: "dash" },
          marker: { size: 3 },
          hovertemplate: `${curve.expiry} PE<br>${xMode}: %{x}<br>IV: %{y:.1f}%<extra></extra>`,
        } as Data);
      }
    });

    const atmX = xMode === "Moneyness" ? 1.0 : firstAtmStrike;

    const plotLayout: Partial<Layout> = {
      xaxis: {
        title: { text: xMode },
        tickformat: xMode === "Moneyness" ? ".3f" : ",.0f",
      },
      yaxis: { title: { text: "IV (%)" }, ticksuffix: "%" },
      margin: { t: 20, r: 10, b: 45, l: 55 },
      shapes: [
        {
          type: "line",
          x0: atmX,
          x1: atmX,
          y0: 0,
          y1: 1,
          yref: "paper" as const,
          line: { color: "#6366f1", width: 1, dash: "dash" },
        },
      ],
      annotations: [
        {
          x: atmX,
          y: 1,
          yref: "paper" as const,
          text: `ATM ${firstAtmStrike}`,
          showarrow: false,
          font: { size: 9, color: "#6366f1" },
          yanchor: "top",
        },
      ],
    };

    return { plotData: traces, plotLayout };
  }, [normalised, optionType, xMode]);

  const emptyMessage = expiryUnavailable
    ? "No future expiry is available for this symbol"
    : liveData || isError
      ? "No IV data available for the selected parameters"
      : "Select symbol to view IV smile curves";

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="IV Smile widget"
    >
      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        <Activity size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">
          {view === "skew" ? "IV Skew" : "IV Smile"}
        </span>

        {/* Provenance badge — live requires explicit provenance AND usable curves. */}
        {isLive ? (
          <span
            className="inline-flex items-center rounded border border-profit/40 bg-profit/10 px-1.5 py-0.5 text-[10px] font-medium text-profit"
            role="status"
            aria-label="Showing the live IV smile from the connected broker"
            title="Live IV curves from the connected broker's IV-smile feed."
          >
            Live
          </span>
        ) : isSample ? (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample IV curves while disconnected"
            title="Disconnected Explore state; values are deterministic sample data."
          >
            Sample data
          </span>
        ) : loading ? (
          <span
            className="inline-flex items-center rounded border border-border-default bg-surface-hover px-1.5 py-0.5 text-[10px] font-medium text-text-muted"
            role="status"
          >
            Loading
          </span>
        ) : (
          <span
            className="inline-flex items-center rounded border border-loss/40 bg-loss/10 px-1.5 py-0.5 text-[10px] font-medium text-loss"
            role="status"
            aria-label="Live IV curves unavailable"
          >
            Unavailable
          </span>
        )}

        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="h-7 w-32 text-xs bg-surface-hover border-border-default" aria-label="Select symbol">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default">
            {SYMBOL_CHOICES.map((s) => (
              <SelectItem key={s} value={s} className="text-xs text-text-primary focus:bg-surface-hover">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="px-1.5 py-0.5 text-xs text-text-muted bg-surface-base border border-border-default rounded">
          {exchange}
        </span>
        <Input
          value={expiriesInput}
          onChange={(e) => setExpiriesInput(e.target.value)}
          placeholder={autoExpiry ? `${autoExpiry} (auto)` : "Expiries (comma-sep)"}
          aria-label="Expiries (comma-separated, overrides the auto-selected expiry)"
          className="flex-1 min-w-36 h-7 text-xs"
        />

        {/* View toggle */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {VIEW_MODES.map((m) => (
            <button
              key={m}
              onClick={() => handleViewChange(m)}
              className={cn(
                "px-2 py-0.5 text-xs font-medium transition-colors",
                m === view
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
              aria-pressed={m === view}
            >
              {VIEW_LABELS[m]}
            </button>
          ))}
        </div>

        {/* Option type toggle */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {(["CE", "PE", "Both"] as OptionTypeFilter[]).map((t) => (
            <button
              key={t}
              onClick={() => setOptionType(t)}
              className={cn(
                "px-2 py-0.5 text-xs font-medium transition-colors",
                t === optionType
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
              aria-pressed={t === optionType}
            >
              {t}
            </button>
          ))}
        </div>

        {/* X-axis toggle */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {(["Strike", "Moneyness"] as XAxisMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setXMode(m)}
              className={cn(
                "px-2 py-0.5 text-xs font-medium transition-colors",
                m === xMode
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
              aria-pressed={m === xMode}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* Metrics header */}
      {(atmIV != null || skew25d != null) && (
        <div
          className="flex-none flex items-center gap-4 px-3 py-1 bg-surface-base border-b border-border-subtle text-xs"
          aria-label="IV curve metrics"
        >
          {atmIV != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted uppercase tracking-wide">ATM IV</span>
              <span className="font-mono tabular-nums font-semibold text-text-primary">
                {(atmIV * 100).toFixed(1)}%
              </span>
            </div>
          )}
          {skew25d != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted uppercase tracking-wide">25Δ Skew</span>
              <span
                className={cn(
                  "font-mono tabular-nums font-semibold flex items-center gap-0.5",
                  skew25d > 0 ? "text-loss" : skew25d < 0 ? "text-profit" : "text-text-secondary",
                )}
                aria-label={`25 delta skew: ${(skew25d * 100).toFixed(2)} percent`}
              >
                {skew25d > 0 ? <TrendingDown size={10} /> : <TrendingUp size={10} />}
                {skew25d > 0 ? "+" : ""}{(skew25d * 100).toFixed(2)}%
              </span>
              <span className="text-text-muted text-xxs">
                {skew25d > 0 ? "(put premium)" : "(call premium)"}
              </span>
            </div>
          )}
          <div className="flex-1" />
          <span className="text-xxs text-text-muted">{symbol}</span>
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{(error as Error)?.message ?? "Failed to load IV smile data"}</span>
        </div>
      )}

      {/* Loading — only when connected, in flight, and nothing live to keep up */}
      {loading && !isLive && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={16} className="animate-spin" />
          Loading IV smile...
        </div>
      )}

      {/* Connected but nothing trustworthy to draw */}
      {isConnected && !loading && !isLive && (
        <div className="flex-1 flex items-center justify-center px-4 text-center text-text-muted text-sm" role="status">
          {emptyMessage}
        </div>
      )}

      {/* Chart */}
      {normalised && (isLive || isSample) && (() => {
        const chartContent = view === "skew" ? (
          <>
            <div className="flex-1 min-h-0 overflow-hidden px-1 pt-1">
              <FlintBandedLineChart
                ariaLabel="IV Skew chart"
                bands={[]}
                series={skewChart.series}
                markers={skewChart.markers}
                xDomain={skewChart.xDomain}
                yDomain={skewChart.yDomain}
                yTicks={skewChart.yTicks}
                yFormatter={(value) => `${value.toFixed(0)}%`}
                xAxisLabel={skewChart.xAxisLabel}
                referenceLines={skewChart.referenceLines}
                width={320}
                height={160}
              />
            </div>
            <ChartLegend overlays={overlays} optionType={optionType} />
          </>
        ) : (
          <div className="flex-1 min-h-0">
            <PlotlyChart data={plotData} layout={plotLayout} />
          </div>
        );
        return isConnected ? (
          chartContent
        ) : (
          <FeatureTeaser
            status="preview"
            featureName="IV Smile"
            version={APP_VERSION_TAG}
          >
            {chartContent}
          </FeatureTeaser>
        );
      })()}
    </div>
  );
}

export default memo(IVSmileWidget);
