/**
 * GreeksHeatmapWidget — "Greeks Matrix": ONE option-greeks dataset rendered
 * under two projections, chosen by the Dockview panel parameter
 * `params.projection`:
 *   • "grid"    (default) — the 2-D heat table: rows are expiries (near → far),
 *     columns are strikes (low → high), cell colour encodes the metric.
 *   • "surface" — the presentation of the retired GreeksSurface widget: a CSS
 *     3-D bar projection (perspective + rotateX/rotateY, no WebGL and no chart
 *     library) with rotate/reset controls and axis labels rendered OUTSIDE the
 *     3-D transform so they stay readable at any angle.
 *
 * The metric is orthogonal to the projection (`params.metric`): IV, delta,
 * gamma, theta or vega. Both projections read the same `ExpiryRow[]` from
 * `greeksHeatmapTransform`, so the two are genuinely one dataset seen twice —
 * which is what made the two widgets a merge rather than a deletion.
 *
 * STRIKES ARE REAL (absorbed decision): the retired surface snapped every row
 * onto synthetic ±5% moneyness buckets and rendered a rounded strike, losing
 * the quoted strikes. The merged widget keeps the heatmap's INTERSECTION
 * alignment — the strike set quoted across every expiry on screen — under both
 * projections.
 *
 * DATA HONESTY: greeks are NOT in the OpenAlgo option-chain feed, so when a
 * broker is connected the widget fetches the live IV smile (`getFtIVSmile`) once
 * per expiry and derives the aligned matrix client-side via the shared
 * Black–Scholes module (`@/lib/optionsMath`, through `greeksHeatmapTransform`),
 * showing a "Live" badge.
 *   - Four-state provenance badge: Live / Sample data / Loading / Unavailable.
 *   - Fail-closed live gate — a connected payload is promoted to "Live" ONLY on
 *     an explicit `is_sample_data: false`. The retired surface threaded that
 *     same flag through its derivation but rendered the result as a "Demo data"
 *     surface; the merged widget threads it into the gate instead and reports
 *     Unavailable, because drawing fabricated backend IVs as a surface inside a
 *     connected terminal is the weaker of the two postures.
 *   - Deterministic sample data is restricted to the disconnected Explore
 *     state, where it renders behind a FeatureTeaser under a "Sample data"
 *     badge. Connected empty/error reads are surfaced as unavailable and never
 *     replaced with sample figures.
 *   - No refresh control. The query auto-refreshes every 30 s while connected;
 *     the retired surface's refresh button also rendered while DISCONNECTED,
 *     where its query is disabled and the click cannot refetch anything — a
 *     deceptive affordance this widget had already removed.
 */

import { useState, useMemo, useEffect, useCallback, memo } from "react";
import { Grid3x3, AlertCircle, RotateCcw, ChevronUp, ChevronDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import type { IDockviewPanelProps } from "dockview";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { FeatureTeaser } from "@/components/teasers";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { getExpiry } from "@/services/api";
import { getFtIVSmile } from "@/services/ftApi.analysis";
import type { IVSmileData } from "@/types/api";
import { SYMBOLS as OPTION_SYMBOLS } from "@/widgets/analysis/OptionChain/types";
import {
  approxGreeks,
  buildGreeksHeatmap,
  classifyMoneyness,
  ivPercent,
} from "./greeksHeatmapTransform";
import type { ExpiryRow, HeatCell } from "./greeksHeatmapTransform";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Selectable metric. `iv` came from the retired GreeksSurface widget. */
type MetricKey = "iv" | "delta" | "gamma" | "theta" | "vega";

/** Presentation. `surface` is the retired GreeksSurface widget's view. */
type Projection = "grid" | "surface";

const METRICS: readonly MetricKey[] = ["iv", "delta", "gamma", "theta", "vega"];
const PROJECTIONS: readonly Projection[] = ["grid", "surface"];

const METRIC_LABELS: Record<MetricKey, string> = {
  iv:    "IV %",
  delta: "Delta",
  gamma: "Gamma",
  theta: "Theta",
  vega:  "Vega",
};

const PROJECTION_LABELS: Record<Projection, string> = {
  grid:    "Grid",
  surface: "Surface",
};

function isMetric(value: unknown): value is MetricKey {
  return typeof value === "string" && (METRICS as readonly string[]).includes(value);
}

function isProjection(value: unknown): value is Projection {
  return typeof value === "string" && (PROJECTIONS as readonly string[]).includes(value);
}

/** Resolves `params.metric`, defaulting to delta (this widget's own default). */
function resolveMetric(value: unknown): MetricKey {
  return isMetric(value) ? value : "delta";
}

/** Resolves `params.projection`, defaulting to the 2-D grid. */
function resolveProjection(value: unknown): Projection {
  return isProjection(value) ? value : "grid";
}

/**
 * Live provenance is accepted only when the backend explicitly attests
 * `is_sample_data: false`. Missing or malformed flags fail closed.
 *
 * @param payload A single IV-smile response.
 * @returns True only for an explicit `is_sample_data: false`.
 */
function carriesExplicitLiveFlag(payload: unknown): boolean {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as { is_sample_data?: unknown }).is_sample_data === false
  );
}

// ---------------------------------------------------------------------------
// Sample data — 3 expiries × 9 strikes
//
// The IV surface is fabricated (a deterministic smile + put skew per expiry),
// but the greeks come from `approxGreeks` — the SAME shared Black–Scholes path
// (`@/lib/optionsMath`) the live matrix uses. Sample and live rows are therefore
// two readings of one implementation, not two unrelated formulas.
// ---------------------------------------------------------------------------

const SAMPLE_STRIKES = [21500, 21600, 21700, 21800, 21900, 22000, 22100, 22200, 22300];
const ATM_STRIKE = 22000;
/** Smile curvature: extra IV per unit squared moneyness. */
const SAMPLE_SMILE_CURVE = 12;
/** Put skew: extra IV on the downside wing, per unit moneyness. */
const SAMPLE_PUT_SKEW = 0.6;

function makeSampleRow(expiry: string, label: string, dte: number, atmIv: number): ExpiryRow {
  const cells: HeatCell[] = SAMPLE_STRIKES.map((strike) => {
    const mv = (strike - ATM_STRIKE) / ATM_STRIKE;
    // Deterministic smile (no Math.random) so the matrix is testable.
    const iv = atmIv + SAMPLE_SMILE_CURVE * mv * mv + (mv < 0 ? SAMPLE_PUT_SKEW * -mv : 0);
    return {
      strike,
      moneyness: classifyMoneyness(strike, ATM_STRIKE),
      iv: ivPercent(iv),
      ...approxGreeks(strike, ATM_STRIKE, iv, dte),
    };
  });
  return { expiry, label, dte, cells };
}

export const SAMPLE_GREEKS_HEATMAP_DATA: ExpiryRow[] = [
  makeSampleRow("2026-04-17", "17 Apr", 8,  0.16),
  makeSampleRow("2026-04-24", "24 Apr", 15, 0.145),
  makeSampleRow("2026-05-29", "29 May", 50, 0.13),
];

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Index underlyings offered here. The exchange is NOT kept in a local map — it
 * is resolved from the canonical option-chain symbol table, so NFO/BFO routing
 * cannot drift away from the option chain's (the retired surface carried its own
 * SYMBOL_EXCHANGE copy, which could).
 */
export const SYMBOL_CHOICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

/** Default perspective angles for the surface projection (degrees). */
const DEFAULT_ROT_X = 52;
const DEFAULT_ROT_Y = -18;

/**
 * The honest term-structure caveat, shown to the operator (not just to the next
 * maintainer) whenever the live matrix is on screen. See the query below.
 */
const TERM_STRUCTURE_CAVEAT =
  "Every expiry reads the same IV snapshot — greeks by time, not a true term structure.";

// ---------------------------------------------------------------------------
// Colour scale: 0→1 → blue (low) → green → yellow → red (high)
//
// One ramp for both projections. The retired surface had drifted to
// `35 + norm * 15` lightness against this one's `32 + norm * 18`; a single
// function is what stops them drifting again.
// ---------------------------------------------------------------------------

function normToHsl(norm: number): string {
  const hue = Math.round(240 - norm * 240);
  return `hsl(${hue},70%,${32 + norm * 18}%)`;
}

const COLOUR_RAMP_CSS =
  "linear-gradient(to right,hsl(240,70%,32%),hsl(120,70%,40%),hsl(60,70%,44%),hsl(0,70%,40%))";

function getCellValue(cell: HeatCell, metric: MetricKey): number {
  switch (metric) {
    case "iv":    return cell.iv;
    case "delta": return cell.delta;
    case "gamma": return cell.gamma;
    case "theta": return Math.abs(cell.theta); // display magnitude
    case "vega":  return cell.vega;
  }
}

function formatCell(val: number, metric: MetricKey): string {
  switch (metric) {
    case "iv":    return `${val.toFixed(1)}%`;
    case "delta": return val.toFixed(2);
    case "gamma": return val.toFixed(4);
    case "theta": return `−${val.toFixed(2)}`;
    case "vega":  return val.toFixed(3);
  }
}

/** Min/max of the selected metric across every cell, for the colour scale. */
function metricRange(rows: ExpiryRow[], metric: MetricKey): { minVal: number; maxVal: number } {
  let min = Infinity;
  let max = -Infinity;
  for (const row of rows) {
    for (const cell of row.cells) {
      const v = getCellValue(cell, metric);
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  return { minVal: min, maxVal: max };
}

// ---------------------------------------------------------------------------
// Tooltip — shared by both projections
// ---------------------------------------------------------------------------

interface TooltipState {
  cell: HeatCell;
  expiry: string;
  dte: number;
  x: number;
  y: number;
}

function CellTooltip({ tip }: { tip: TooltipState }) {
  return (
    <div
      className="fixed z-50 pointer-events-none bg-surface-card border border-border-default rounded px-2.5 py-2 shadow-lg text-xs min-w-44"
      style={{ left: tip.x + 14, top: tip.y - 8 }}
      role="tooltip"
    >
      <div className="font-semibold text-text-primary mb-1">
        {tip.cell.strike} · {tip.cell.moneyness} · {tip.expiry} ({tip.dte}d)
      </div>
      <div className="space-y-0.5 text-text-secondary">
        <div className="flex justify-between gap-4">
          <span>IV</span>
          <span className="font-mono text-text-primary">{tip.cell.iv.toFixed(1)}%</span>
        </div>
        {(["delta", "gamma", "theta", "vega"] as const).map((g) => (
          <div key={g} className="flex justify-between gap-4">
            <span className="capitalize">{g}</span>
            <span className="font-mono text-text-primary">
              {g === "theta" ? `−${Math.abs(tip.cell.theta).toFixed(2)}` : tip.cell[g].toFixed(g === "gamma" ? 4 : 3)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Pointer handlers shared by the grid and surface cells. */
function useCellTooltip() {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const handleEnter = useCallback(
    (e: React.MouseEvent, cell: HeatCell, expiry: string, dte: number) => {
      setTooltip({ cell, expiry, dte, x: e.clientX, y: e.clientY });
    },
    [],
  );

  const handleMove = useCallback((e: React.MouseEvent) => {
    setTooltip((prev) => prev ? { ...prev, x: e.clientX, y: e.clientY } : prev);
  }, []);

  const handleLeave = useCallback(() => setTooltip(null), []);

  return { tooltip, handleEnter, handleMove, handleLeave };
}

// ---------------------------------------------------------------------------
// Grid projection — 2-D heat table
// ---------------------------------------------------------------------------

interface ProjectionProps {
  rows: ExpiryRow[];
  metric: MetricKey;
  minVal: number;
  maxVal: number;
}

function HeatGrid({ rows, metric, minVal, maxVal }: ProjectionProps) {
  const { tooltip, handleEnter, handleMove, handleLeave } = useCellTooltip();
  const range = maxVal - minVal || 1;
  const strikes = rows[0]?.cells.map((c) => c.strike) ?? [];

  return (
    <>
      <div
        className="overflow-auto"
        role="grid"
        aria-label={`${METRIC_LABELS[metric]} heat grid`}
      >
        <table className="text-xs border-collapse">
          {/* Column headers — strikes */}
          <thead>
            <tr>
              <th className="text-left px-2 py-1 text-xxs text-text-muted font-medium uppercase tracking-wide sticky left-0 bg-surface-card z-10 min-w-16">
                Expiry
              </th>
              {strikes.map((s) => (
                <th
                  key={s}
                  className="px-1 py-1 text-xxs text-text-muted font-medium text-center min-w-14 whitespace-nowrap"
                  scope="col"
                >
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.expiry} role="row">
                {/* Row header — expiry */}
                <td
                  className="px-2 py-1.5 text-xxs text-text-secondary font-medium whitespace-nowrap sticky left-0 bg-surface-card z-10 border-r border-border-subtle"
                  role="rowheader"
                >
                  <div className="font-semibold">{row.label}</div>
                  <div className="text-text-muted">{row.dte}d</div>
                </td>
                {/* Cells */}
                {row.cells.map((cell) => {
                  const val = getCellValue(cell, metric);
                  const norm = (val - minVal) / range;
                  const bg = normToHsl(norm);
                  const isATM = cell.moneyness === "ATM";
                  return (
                    <td
                      key={cell.strike}
                      role="gridcell"
                      aria-label={`${row.label} ${cell.strike} ${METRIC_LABELS[metric]}: ${formatCell(val, metric)}`}
                      className={cn(
                        "text-center py-2 px-1 cursor-default transition-opacity hover:opacity-80 relative",
                        isATM && "ring-1 ring-inset ring-white/20",
                      )}
                      style={{ background: bg }}
                      onMouseEnter={(e) => handleEnter(e, cell, row.label, row.dte)}
                      onMouseMove={handleMove}
                      onMouseLeave={handleLeave}
                    >
                      <span className="font-mono tabular-nums text-white/90 text-xxs font-medium drop-shadow-sm">
                        {formatCell(val, metric)}
                      </span>
                      {isATM && (
                        <span className="absolute top-0.5 right-0.5 text-xxs leading-none text-white/60">
                          ▲
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {tooltip && <CellTooltip tip={tooltip} />}
    </>
  );
}

// ---------------------------------------------------------------------------
// Surface projection — CSS-3D bars (no WebGL, no chart library)
// ---------------------------------------------------------------------------

interface SurfaceProps extends ProjectionProps {
  rotX: number;
  rotY: number;
}

/** Cell footprint in px for the isometric tiles. */
const CELL_W = 46;
const CELL_H = 32;
/** Tallest bar in px at the top of the metric range. */
const BAR_MAX = 60;

function SurfaceGrid({ rows, metric, minVal, maxVal, rotX, rotY }: SurfaceProps) {
  const { tooltip, handleEnter, handleMove, handleLeave } = useCellTooltip();
  const range = maxVal - minVal || 1;

  const colCount = rows[0]?.cells.length ?? 0;
  const canvasW = colCount * CELL_W;
  const canvasH = rows.length * CELL_H;

  return (
    <>
      {/* 3-D perspective container */}
      <div
        className="relative select-none"
        style={{
          width: canvasW,
          height: canvasH,
          transform: `perspective(900px) rotateX(${rotX}deg) rotateY(${rotY}deg)`,
          transformStyle: "preserve-3d",
          transformOrigin: "center center",
        }}
        aria-label="Greeks surface 3D grid"
      >
        {rows.map((row, rowIdx) =>
          row.cells.map((cell, colIdx) => {
            const val = getCellValue(cell, metric);
            const norm = (val - minVal) / range;
            const barHeight = Math.max(4, Math.round(norm * BAR_MAX));
            const bg = normToHsl(norm);
            const isATM = cell.moneyness === "ATM";

            return (
              <div
                key={`${row.expiry}-${cell.strike}`}
                className="absolute flex flex-col items-center justify-end cursor-default"
                style={{
                  left: colIdx * CELL_W,
                  top: rowIdx * CELL_H,
                  width: CELL_W - 2,
                  height: CELL_H - 2,
                }}
                onMouseEnter={(e) => handleEnter(e, cell, row.label, row.dte)}
                onMouseMove={handleMove}
                onMouseLeave={handleLeave}
                role="gridcell"
                aria-label={`${row.label} ${cell.strike} ${METRIC_LABELS[metric]}: ${formatCell(val, metric)}`}
              >
                {/* Bar — height encodes the metric value */}
                <div
                  className="w-full rounded-t-sm transition-all duration-300"
                  style={{
                    height: barHeight,
                    background: bg,
                    boxShadow: isATM ? `0 0 6px 1px ${bg}` : undefined,
                    opacity: 0.88,
                    border: isATM ? "1px solid rgba(255,255,255,0.3)" : undefined,
                  }}
                />
                {/* Base floor tile */}
                <div
                  className="w-full border border-border-subtle"
                  style={{
                    height: 3,
                    background: "var(--color-surface-hover)",
                    opacity: 0.6,
                  }}
                />
              </div>
            );
          }),
        )}
      </div>

      {/* Tooltip rendered outside the 3-D container so it is never clipped */}
      {tooltip && <CellTooltip tip={tooltip} />}
    </>
  );
}

// ---------------------------------------------------------------------------
// Axis labels — rendered OUTSIDE the 3-D transform so they stay readable
// ---------------------------------------------------------------------------

function AxisLabels({ rows }: { rows: ExpiryRow[] }) {
  const strikeCells = rows[0]?.cells ?? [];
  return (
    <div className="flex items-start gap-6 px-3 pb-1 flex-wrap">
      <div>
        <span className="text-xxs text-text-muted uppercase tracking-wide">Strike →</span>
        <div className="flex gap-0.5 mt-0.5 flex-wrap">
          {strikeCells.map((cell) => (
            <span
              key={cell.strike}
              className={cn(
                "text-xxs font-mono px-1 rounded",
                cell.moneyness === "ATM"
                  ? "bg-accent/15 text-accent font-semibold"
                  : "text-text-muted",
              )}
            >
              {cell.strike}
            </span>
          ))}
        </div>
      </div>
      <div>
        <span className="text-xxs text-text-muted uppercase tracking-wide">Expiry →</span>
        <div className="flex gap-1 mt-0.5">
          {rows.map((row) => (
            <span key={row.expiry} className="text-xxs text-text-secondary font-mono">
              {row.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Colour legend bar
// ---------------------------------------------------------------------------

function ColourBar({ metric, minVal, maxVal }: { metric: MetricKey; minVal: number; maxVal: number }) {
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <span className="text-xxs text-text-muted">{METRIC_LABELS[metric]}</span>
      <div
        className="h-2 w-24 rounded flex-none"
        style={{ background: COLOUR_RAMP_CSS }}
        aria-label="Colour scale low to high"
      />
      <span className="text-xxs font-mono text-text-muted">
        {formatCell(minVal, metric)} – {formatCell(maxVal, metric)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel params
// ---------------------------------------------------------------------------

interface GreeksMatrixPanelParams {
  /** Initial projection — how the retired `greekssurface` id selects 3-D. */
  projection?: string;
  /** Initial metric — the retired `greekssurface` id opened on IV. */
  metric?: string;
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function GreeksHeatmapWidget(props: IDockviewPanelProps) {
  const panelParams = props.params as GreeksMatrixPanelParams | undefined;

  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [symbol, setSymbol] = useState("NIFTY");
  const [metric, setMetric] = useState<MetricKey>(() => resolveMetric(panelParams?.metric));
  const [projection, setProjection] = useState<Projection>(
    () => resolveProjection(panelParams?.projection),
  );
  const [rotX, setRotX] = useState(DEFAULT_ROT_X);
  const [rotY, setRotY] = useState(DEFAULT_ROT_Y);

  useEffect(() => {
    track(
      "trade",
      projection === "surface" ? "widget_view_greeks_surface" : "widget_view_greeks_heatmap",
    );
  }, [track, projection]);

  // Resolve the option-chain exchange (NFO/BFO/…) for the selected underlying.
  const symDef = useMemo(
    () => OPTION_SYMBOLS.find((s) => s.label === symbol) ?? { label: symbol, exchange: "NFO" },
    [symbol],
  );

  // Live greeks matrix — fetch the IV smile for the nearest expiries (the
  // single-expiry endpoint is called once per expiry, so each carries a real
  // days-to-expiry and thus non-degenerate time-decay greeks) and derive the
  // aligned greek grid client-side. Only runs once a broker is connected.
  //
  // NB (honest approximation): OpenAlgo's option-chain feed takes no expiry, so
  // every per-expiry request reads the SAME (nearest) IV snapshot. The rows
  // therefore share one IV surface and differ only by time-decay (dte) — this
  // is a greeks-by-time view, not a true per-expiry IV term structure.
  const { data: liveRows, isError, error, isPending } = useQuery({
    queryKey: ["greeks-matrix", symbol, symDef.exchange],
    queryFn: async () => {
      const expResp = await getExpiry(symDef.label, symDef.exchange, "options");
      const expiries = (expResp?.expiry ?? []).slice(0, 3);
      if (expiries.length === 0) return null;
      const smiles = await Promise.all(
        expiries.map((expiry) => getFtIVSmile(symDef.label, symDef.exchange, [expiry])),
      );
      // Fail closed on the provenance flag: one unattested or sample-flagged
      // response condemns the whole matrix, because the rows are merged.
      if (!smiles.every(carriesExplicitLiveFlag)) return null;
      const curves = smiles.flatMap((s) => s?.curves ?? []);
      const merged: IVSmileData = {
        underlying: symbol,
        spot_price: smiles.find((s) => s?.spot_price)?.spot_price ?? 0,
        curves,
        is_sample_data: false,
      };
      return buildGreeksHeatmap(merged);
    },
    enabled: isConnected,
    staleTime: 30_000,
    refetchInterval: isConnected ? 30_000 : false,
    retry: false,
  });

  const isLive = isConnected && !isError && liveRows != null && liveRows.length > 0;
  const isSample = !isConnected;
  const data: ExpiryRow[] = isLive && liveRows
    ? liveRows
    : isSample
      ? SAMPLE_GREEKS_HEATMAP_DATA
      : [];

  const { minVal, maxVal } = useMemo(() => metricRange(data, metric), [data, metric]);

  // Persist the chosen projection/metric into the panel params so a saved
  // layout reopens in the same view (this is also how the retired
  // `greekssurface` id keeps its 3-D IV presentation).
  const handleProjectionChange = useCallback((next: Projection) => {
    if (next === projection) return;
    setProjection(next);
    props.api.updateParameters({ ...(panelParams ?? {}), projection: next });
  }, [panelParams, projection, props.api]);

  const handleMetricChange = useCallback((next: MetricKey) => {
    if (next === metric) return;
    setMetric(next);
    props.api.updateParameters({ ...(panelParams ?? {}), metric: next });
  }, [metric, panelParams, props.api]);

  const handleResetView = useCallback(() => {
    setRotX(DEFAULT_ROT_X);
    setRotY(DEFAULT_ROT_Y);
  }, []);

  const body = data.length > 0 ? (
    <div className="h-full flex flex-col min-h-0 overflow-hidden">
      {/* Legend */}
      <ColourBar metric={metric} minVal={minVal} maxVal={maxVal} />

      {/* ATM indicator legend + the honest term-structure caveat */}
      <div className="flex-none flex items-center gap-2 px-2 pb-1 flex-wrap">
        <span className="text-xxs text-text-muted">▲ = ATM strike</span>
        <span className="text-xxs text-text-muted">· Rows: near → far expiry · Cols: low → high strike · CE greeks</span>
        {isLive && (
          <span className="text-xxs text-warning" title={TERM_STRUCTURE_CAVEAT}>
            · {TERM_STRUCTURE_CAVEAT}
          </span>
        )}
      </div>

      {/* Projection */}
      {projection === "grid" ? (
        <div className="flex-1 min-h-0 overflow-auto">
          <HeatGrid rows={data} metric={metric} minVal={minVal} maxVal={maxVal} />
        </div>
      ) : (
        <>
          <div className="flex-1 min-h-0 flex items-start justify-center pt-4 px-4 pb-8 overflow-auto">
            <SurfaceGrid
              rows={data}
              metric={metric}
              minVal={minVal}
              maxVal={maxVal}
              rotX={rotX}
              rotY={rotY}
            />
          </div>
          <AxisLabels rows={data} />
        </>
      )}
    </div>
  ) : null;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Greeks Matrix widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Grid3x3 size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Greeks Matrix</span>
        {/* Data-source badge never labels a connected failed/empty read as sample. */}
        {isLive ? (
          <span
            className="px-1.5 py-0.5 text-xxs bg-profit/10 text-profit border border-profit/30 rounded"
            role="status"
            aria-label="Showing live Greeks derived from the connected broker's IV smile"
            title="Live Greeks Black–Scholes-derived from the connected broker's IV smile."
          >
            Live
          </span>
        ) : isSample ? (
          <span
            className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            role="status"
            aria-label="Showing sample Greeks while disconnected"
            title="Disconnected Explore state; values are deterministic sample data."
          >
            Sample data
          </span>
        ) : isPending ? (
          <span
            className="px-1.5 py-0.5 text-xxs bg-surface-hover text-text-muted border border-border-default rounded"
            role="status"
          >
            Loading
          </span>
        ) : (
          <span
            className="px-1.5 py-0.5 text-xxs bg-loss/10 text-loss border border-loss/30 rounded"
            role="status"
            aria-label="Live Greeks unavailable"
          >
            Unavailable
          </span>
        )}
        <div className="flex-1" />
      </div>

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-elevated border-b border-border-subtle flex-wrap">
        {/* Symbol */}
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="h-6 w-32 text-xs bg-surface-hover border-border-default" aria-label="Select symbol">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default">
            {SYMBOL_CHOICES.map((s) => (
              <SelectItem key={s} value={s} className="text-xs text-text-primary focus:bg-surface-hover">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Projection toggle */}
        <div
          className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden"
          role="group"
          aria-label="Select projection"
        >
          {PROJECTIONS.map((p) => (
            <button
              key={p}
              onClick={() => handleProjectionChange(p)}
              aria-pressed={p === projection}
              className={cn(
                "px-2.5 py-0.5 text-xs font-medium transition-colors",
                p === projection
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
            >
              {PROJECTION_LABELS[p]}
            </button>
          ))}
        </div>

        {/* Metric toggle */}
        <div
          className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden"
          role="group"
          aria-label="Select metric"
        >
          {METRICS.map((m) => (
            <button
              key={m}
              onClick={() => handleMetricChange(m)}
              aria-pressed={m === metric}
              className={cn(
                "px-2.5 py-0.5 text-xs font-medium transition-colors",
                m === metric
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
            >
              {METRIC_LABELS[m]}
            </button>
          ))}
        </div>

        {/* Rotation controls — only meaningful under the 3-D projection */}
        {projection === "surface" && (
          <div className="flex items-center gap-1">
            <div className="flex flex-col">
              <button
                onClick={() => setRotX((v) => Math.min(80, v + 5))}
                className="p-0.5 text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
                title="Rotate up"
                aria-label="Rotate view up"
              >
                <ChevronUp size={12} />
              </button>
              <button
                onClick={() => setRotX((v) => Math.max(10, v - 5))}
                className="p-0.5 text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
                title="Rotate down"
                aria-label="Rotate view down"
              >
                <ChevronDown size={12} />
              </button>
            </div>
            <div className="flex gap-0.5">
              <button
                onClick={() => setRotY((v) => v - 5)}
                className="px-1.5 py-0.5 text-xxs text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
                title="Rotate left"
                aria-label="Rotate view left"
              >
                ←
              </button>
              <button
                onClick={() => setRotY((v) => v + 5)}
                className="px-1.5 py-0.5 text-xxs text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
                title="Rotate right"
                aria-label="Rotate view right"
              >
                →
              </button>
            </div>
            <button
              onClick={handleResetView}
              className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
              title="Reset view"
              aria-label="Reset 3D view"
            >
              <RotateCcw size={11} />
            </button>
          </div>
        )}
      </div>

      {/* Error banner — the failure reason, not just the Unavailable badge. */}
      {isConnected && isError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} aria-hidden="true" />
          <span>{(error as Error)?.message ?? "Failed to load Greeks matrix data"}</span>
        </div>
      )}

      {body ? (
        <div className="flex-1 min-h-0">
          {isConnected ? body : (
            <FeatureTeaser
              status="preview"
              featureName="Greeks Matrix"
              version={APP_VERSION_TAG}
            >
              {body}
            </FeatureTeaser>
          )}
        </div>
      ) : (
        <div className="flex-1 min-h-0 grid place-items-center px-4 text-center" role="status">
          <span className="text-xs text-text-muted">
            {isPending ? "Loading live Greeks…" : "Live Greeks are unavailable for this symbol."}
          </span>
        </div>
      )}

      {/* Footer */}
      <div className="flex-none px-2 py-1 bg-surface-card border-t border-border-subtle">
        <span className="text-xxs text-text-muted">{symbol} · {data.length} expiries · {data[0]?.cells.length ?? 0} strikes</span>
      </div>
    </div>
  );
}

export default memo(GreeksHeatmapWidget);
