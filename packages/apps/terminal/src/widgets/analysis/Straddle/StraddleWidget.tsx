/**
 * StraddleWidget — ATM straddle price tracker and implied-move range.
 *
 * Two presentations of ONE fetch, chosen by the workspace panel parameter
 * `params.view`:
 *   - `straddle`    (default) — straddle price over time on a Lightweight
 *                    Charts line, with Spot and Synthetic Future overlays.
 *   - `impliedmove` — the σ-band expected range absorbed from the retired
 *                    ImpliedMove widget (merge 2.15).
 *
 * WHY THE MERGE (read before splitting them again): the implied-move view
 * needs exactly four numbers — spot, ATM strike, ATM CE premium, ATM PE
 * premium — and this widget already computes all four live from
 * `getOptionChain` + `getQuotes`. The retired widget was static only because
 * nobody connected the two; no backend endpoint was ever required. Both views
 * are rendered from the same `useMemo` derivation, so switching view adds no
 * request.
 *
 * The retired widget also shipped a real defect that this merge removes by
 * deletion: it indexed a 2-entry sample array with a 5-entry symbol dropdown,
 * so FINNIFTY silently displayed NIFTY's figures under a FINNIFTY label. Every
 * number here is derived from the selected symbol's own live chain, so a
 * symbol/figure mismatch is no longer representable.
 *
 * Features:
 *   - Symbol selector (NIFTY / BANKNIFTY / FINNIFTY) + Expiry selector
 *   - ATM strike auto-detected from spot LTP
 *   - Three headline values: Straddle Price (CE LTP + PE LTP), CE Price, PE Price
 *   - TradingView Lightweight Charts v5 line chart of straddle price over time
 *   - Overlay toggles: Straddle / Spot / Synthetic Future
 *   - Implied move = ATM CE + ATM PE, with ±1σ (≈68%) and ±2σ (≈95%) bands
 *   - Auto-refresh: 3s market hours, 30s off-market
 *   - P&L display when a straddle position is detected in positions data
 */

import { useState, useEffect, useCallback, useRef, useMemo, memo } from "react";
import type { WidgetProps } from "@/types/widgets";
import type { ISeriesApi, LineData, Time } from "lightweight-charts";
import { createFlintLineChart } from "@flinttrade/design-system";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightLineRuntime } from "@/lib/lightweightChartRuntime";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import {
  RefreshCw,
  ChevronDown,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Activity,
  MoveHorizontal,
} from "lucide-react";
import {
  getExpiry,
  getOptionChain,
  getQuotes,
  getPositionbook,
} from "@/services/api";
import type { Quote, Position } from "@/types/api";
import { isMarketHours } from "@/lib/market";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SymbolDef {
  label: string;
  exchange: string;
  spotSymbol: string;
  spotExchange: string;
}

interface RawOptionRow {
  strike_price?: number;
  strike?: number;
  ltp?: number;
  last_price?: number;
}

interface RawOptionChainEntry {
  strike?: number;
  ce?: RawOptionRow | null;
  pe?: RawOptionRow | null;
}

interface RawOptionChain {
  chain?: RawOptionChainEntry[];
  calls?: RawOptionRow[];
  puts?: RawOptionRow[];
  atm_strike?: number;
}

type OverlayName = "Straddle" | "Spot" | "SynFut";

interface ChartPoint {
  time: Time;
  value: number;
}

interface StraddleChartProps {
  dataPoints: ChartPoint[];
  spotPoints: ChartPoint[];
  synfutPoints: ChartPoint[];
  activeOverlays: OverlayName[];
  height?: number;
}

interface StraddleChartFillProps {
  straddlePoints: ChartPoint[];
  spotPoints: ChartPoint[];
  synfutPoints: ChartPoint[];
  activeOverlays: OverlayName[];
}

/**
 * Presentation of the ATM straddle data. `impliedmove` is the retired
 * ImpliedMove widget's view.
 */
type ViewMode = "straddle" | "impliedmove";

const VIEW_MODES: readonly ViewMode[] = ["straddle", "impliedmove"];

const VIEW_LABELS: Record<ViewMode, string> = {
  straddle: "Straddle",
  impliedmove: "Implied Move",
};

function isViewMode(value: unknown): value is ViewMode {
  return typeof value === "string" && (VIEW_MODES as readonly string[]).includes(value);
}

/** Resolves the workspace `params.view` panel parameter, defaulting to straddle. */
function resolveViewMode(value: unknown): ViewMode {
  return isViewMode(value) ? value : "straddle";
}

interface StraddlePanelParams extends Record<string, unknown> {
  /** Initial view — how the retired `impliedmove` id selects its old presentation. */
  view?: string;
}

/**
 * Expected-range figures derived from the live ATM straddle.
 *
 * Log-normal approximation, as carried over from the retired widget:
 *   Implied move = ATM CE premium + ATM PE premium
 *   ±1σ ≈ 68%  → spot ± 1× implied move
 *   ±2σ ≈ 95%  → spot ± 2× implied move
 */
export interface ImpliedMoveData {
  spot: number;
  atmStrike: number;
  cePremium: number;
  pePremium: number;
  impliedMove: number;
  upperBound: number;
  lowerBound: number;
  upper2Sigma: number;
  lower2Sigma: number;
  impliedMovePct: number;
}

export interface ImpliedMoveInputs {
  spot: number | null | undefined;
  atmStrike: number | null | undefined;
  cePremium: number | null | undefined;
  pePremium: number | null | undefined;
}

/**
 * Derives the implied-move bands from live ATM straddle inputs.
 *
 * Fails closed: any missing, non-finite or non-positive input returns `null`,
 * and the view then discloses that no live figures are available rather than
 * substituting a sample. There is deliberately no sample fallback — the
 * retired widget's constant tables were the source of its mislabelling bug.
 */
export function computeImpliedMove({
  spot,
  atmStrike,
  cePremium,
  pePremium,
}: ImpliedMoveInputs): ImpliedMoveData | null {
  const spotVal = Number(spot ?? 0);
  const atmVal = Number(atmStrike ?? 0);
  const ceVal = Number(cePremium ?? 0);
  const peVal = Number(pePremium ?? 0);

  if (![spotVal, atmVal, ceVal, peVal].every((v) => Number.isFinite(v) && v > 0)) {
    return null;
  }

  const impliedMove = ceVal + peVal;

  return {
    spot: spotVal,
    atmStrike: atmVal,
    cePremium: ceVal,
    pePremium: peVal,
    impliedMove,
    upperBound: spotVal + impliedMove,
    lowerBound: spotVal - impliedMove,
    upper2Sigma: spotVal + impliedMove * 2,
    lower2Sigma: spotVal - impliedMove * 2,
    impliedMovePct: (impliedMove / spotVal) * 100,
  };
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS: SymbolDef[] = [
  { label: "NIFTY",     exchange: "NFO", spotSymbol: "NIFTY",     spotExchange: "NSE_INDEX" },
  { label: "BANKNIFTY", exchange: "NFO", spotSymbol: "BANKNIFTY", spotExchange: "NSE_INDEX" },
  { label: "FINNIFTY",  exchange: "NFO", spotSymbol: "FINNIFTY",  spotExchange: "NSE_INDEX" },
];

const OVERLAYS: OverlayName[] = ["Straddle", "Spot", "SynFut"];

const CHART_COLORS = {
  straddle: "#3b82f6",
  spot:     "#eab308",
  synfut:   "#a78bfa",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const NUM  = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const NUM0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
/** Band/level formatter carried over from the retired ImpliedMove widget. */
const NUM1 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });

function fmtPrice(v: number | null | undefined): string {
  if (v == null || v === 0) return "—";
  return NUM.format(v);
}

function fmtLevel(v: number): string {
  return NUM1.format(v);
}

function fmtExpiry(raw: string): string {
  if (!raw) return raw;
  try {
    const d = new Date(raw);
    if (isNaN(d.getTime())) return raw;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  } catch {
    return raw;
  }
}

function toChartTime(date: Date): Time {
  return Math.floor(date.getTime() / 1000) as unknown as Time;
}

function appendPoint(arr: ChartPoint[], point: ChartPoint): void {
  if (arr.length > 0 && arr[arr.length - 1].time === point.time) {
    arr[arr.length - 1] = point;
  } else {
    arr.push(point);
  }
}

function optionLegWithStrike(row: RawOptionRow | null | undefined, strike: unknown): RawOptionRow | null {
  if (!row) return null;
  const strikeValue = Number(row.strike_price ?? row.strike ?? strike);
  if (!Number.isFinite(strikeValue) || strikeValue <= 0) return null;
  return { ...row, strike: strikeValue, strike_price: strikeValue };
}

function chainCalls(chain: RawOptionChain): RawOptionRow[] {
  if (chain.chain?.length) {
    return chain.chain.flatMap((entry) => {
      const row = optionLegWithStrike(entry.ce, entry.strike);
      return row ? [row] : [];
    });
  }
  return chain.calls ?? [];
}

function chainPuts(chain: RawOptionChain): RawOptionRow[] {
  if (chain.chain?.length) {
    return chain.chain.flatMap((entry) => {
      const row = optionLegWithStrike(entry.pe, entry.strike);
      return row ? [row] : [];
    });
  }
  return chain.puts ?? [];
}

function findAtm(chain: RawOptionChain, spotLtp: number): number | null {
  if (!chain) return null;
  if (chain.atm_strike) return Number(chain.atm_strike);
  if (!spotLtp) return null;

  const strikes = Array.from(new Set([
    ...chainCalls(chain).map((c) => Number(c.strike_price ?? c.strike)),
    ...chainPuts(chain).map((p) => Number(p.strike_price ?? p.strike)),
  ])).filter(Boolean).sort((a, b) => a - b);

  if (strikes.length === 0) return null;

  return strikes.reduce((prev, cur) =>
    Math.abs(cur - spotLtp) < Math.abs(prev - spotLtp) ? cur : prev,
    strikes[0]
  );
}

function findOption(arr: RawOptionRow[], strike: number): RawOptionRow | null {
  return arr.find((o) => Number(o.strike_price ?? o.strike) === Number(strike)) ?? null;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface SelectorProps {
  value: string;
  options: string[];
  onChange: (val: string) => void;
  className?: string;
}

function Selector({ value, options, onChange, className = "" }: SelectorProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onOut(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onOut);
    return () => document.removeEventListener("mousedown", onOut);
  }, []);

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors"
      >
        {value}
        <ChevronDown size={10} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full">
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${
                opt === value ? "text-accent" : "text-text-primary"
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

interface PriceHeadlineProps {
  straddlePrice: number | null;
  cePrice: number | null;
  pePrice: number | null;
}

function PriceHeadline({ straddlePrice, cePrice, pePrice }: PriceHeadlineProps) {
  return (
    <div className="flex items-stretch gap-px bg-border-default">
      <div className="flex-1 bg-surface-card px-3 py-2 flex flex-col items-center justify-center gap-0.5">
        <span className="text-xxs text-text-muted uppercase tracking-wider">Straddle</span>
        <span className="font-mono tabular-nums text-xl font-bold text-text-primary leading-none">
          {straddlePrice != null ? fmtPrice(straddlePrice) : "—"}
        </span>
        <span className="text-xxs text-text-muted font-normal">CE + PE</span>
      </div>

      <div className="flex-1 bg-surface-card px-3 py-2 flex flex-col items-center justify-center gap-0.5">
        <span className="text-xxs text-text-muted uppercase tracking-wider">CE</span>
        <span className="font-mono tabular-nums text-base font-semibold text-loss leading-none">
          {cePrice != null ? fmtPrice(cePrice) : "—"}
        </span>
        <span className="text-xxs text-loss/60">Call</span>
      </div>

      <div className="flex-1 bg-surface-card px-3 py-2 flex flex-col items-center justify-center gap-0.5">
        <span className="text-xxs text-text-muted uppercase tracking-wider">PE</span>
        <span className="font-mono tabular-nums text-base font-semibold text-profit leading-none">
          {pePrice != null ? fmtPrice(pePrice) : "—"}
        </span>
        <span className="text-xxs text-profit/60">Put</span>
      </div>
    </div>
  );
}

// Internal chart component (isolated lifecycle)
function StraddleChart({
  dataPoints,
  spotPoints,
  synfutPoints,
  activeOverlays,
  height = 180,
}: StraddleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const straddleRef  = useRef<ISeriesApi<"Line"> | null>(null);
  const spotRef      = useRef<ISeriesApi<"Line"> | null>(null);
  const synfutRef    = useRef<ISeriesApi<"Line"> | null>(null);
  const chartTheme   = useLightweightChartTheme();

  useEffect(() => {
    if (!containerRef.current) return;

    const flintChart = createFlintLineChart(
      lightweightLineRuntime,
      containerRef.current,
      chartTheme,
      {
        ariaLabel: "ATM straddle price chart",
        height,
        layout: { fontSize: 10 },
        timeScale: { ticksVisible: true },
        defaultSeriesOptions: {
          priceLineVisible: false,
          lastValueVisible: true,
        },
        series: [
          {
            id: "straddle",
            options: {
              color: CHART_COLORS.straddle,
              lineWidth: 2,
            },
          },
          {
            id: "spot",
            options: {
              color: CHART_COLORS.spot,
              lineWidth: 1,
              lineStyle: 2,
              visible: false,
            },
          },
          {
            id: "synfut",
            options: {
              color: CHART_COLORS.synfut,
              lineWidth: 1,
              lineStyle: 2,
              visible: false,
            },
          },
        ],
      },
    );

    straddleRef.current = flintChart.seriesById.straddle ?? null;
    spotRef.current = flintChart.seriesById.spot ?? null;
    synfutRef.current = flintChart.seriesById.synfut ?? null;

    return () => {
      flintChart.remove();
      straddleRef.current = null;
      spotRef.current = null;
      synfutRef.current = null;
    };
   
  }, [height, chartTheme]);

  useEffect(() => {
    if (!straddleRef.current) return;
    if (dataPoints.length > 0) {
      straddleRef.current.setData(dataPoints as LineData[]);
    }
  }, [dataPoints]);

  useEffect(() => {
    if (!spotRef.current) return;
    if (spotPoints.length > 0) {
      spotRef.current.setData(spotPoints as LineData[]);
    }
  }, [spotPoints]);

  useEffect(() => {
    if (!synfutRef.current) return;
    if (synfutPoints.length > 0) {
      synfutRef.current.setData(synfutPoints as LineData[]);
    }
  }, [synfutPoints]);

  useEffect(() => {
    if (!straddleRef.current || !spotRef.current || !synfutRef.current) return;
    straddleRef.current.applyOptions({ visible: activeOverlays.includes("Straddle") });
    spotRef.current.applyOptions({    visible: activeOverlays.includes("Spot") });
    synfutRef.current.applyOptions({  visible: activeOverlays.includes("SynFut") });
  }, [activeOverlays]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}

/** Shared in-flight body — both views wait on the same fetch. */
function LoadingBody() {
  return (
    <div className="h-full flex items-center justify-center text-text-muted text-xs gap-2">
      <RefreshCw size={13} className="animate-spin" />
      Loading straddle…
    </div>
  );
}

// ---------------------------------------------------------------------------
// Implied-move view (absorbed from the retired ImpliedMove widget)
// ---------------------------------------------------------------------------

/** Nested 1σ / 2σ zones with the live spot marker. */
function RangeBar({ data }: { data: ImpliedMoveData }) {
  const { spot, lowerBound, upperBound, lower2Sigma, upper2Sigma } = data;

  // Positions as percentages within the 2σ range
  const totalRange = upper2Sigma - lower2Sigma;
  const pos = (v: number) =>
    Math.min(100, Math.max(0, ((v - lower2Sigma) / totalRange) * 100));

  const spotPct = pos(spot);
  const lb1Pct = pos(lowerBound);
  const ub1Pct = pos(upperBound);

  return (
    <div className="space-y-2" aria-label="Implied move range bar">
      {/* Range bar */}
      <div className="relative h-8 rounded bg-surface-hover overflow-visible mx-1">
        {/* 2σ zone (full width = bg) */}
        <div className="absolute inset-0 bg-accent/5 rounded" />

        {/* 1σ zone */}
        <div
          className="absolute inset-y-0 bg-accent/15 rounded"
          style={{ left: `${lb1Pct}%`, right: `${100 - ub1Pct}%` }}
        />

        {/* 1σ bound lines */}
        <div className="absolute inset-y-0 w-px bg-accent/50" style={{ left: `${lb1Pct}%` }} />
        <div className="absolute inset-y-0 w-px bg-accent/50" style={{ left: `${ub1Pct}%` }} />

        {/* Spot marker */}
        <div
          className="absolute top-1 bottom-1 w-0.5 bg-text-primary rounded-full shadow"
          style={{ left: `${spotPct}%`, transform: "translateX(-50%)" }}
        />

        {/* Spot label */}
        <div
          className="absolute -top-5 text-xxs font-mono text-text-primary whitespace-nowrap"
          style={{ left: `${spotPct}%`, transform: "translateX(-50%)" }}
        >
          {fmtLevel(spot)}
        </div>
      </div>

      {/* Bound labels row */}
      <div className="flex justify-between text-xxs font-mono tabular-nums">
        <div className="text-left">
          <div className="text-loss font-semibold">{fmtLevel(lower2Sigma)}</div>
          <div className="text-text-muted">−2σ (95%)</div>
        </div>
        <div className="text-center">
          <div className="text-text-secondary font-semibold">{fmtLevel(lowerBound)}</div>
          <div className="text-text-muted">−1σ (68%)</div>
        </div>
        <div className="text-center">
          <div className="text-text-secondary font-semibold">{fmtLevel(upperBound)}</div>
          <div className="text-text-muted">+1σ (68%)</div>
        </div>
        <div className="text-right">
          <div className="text-profit font-semibold">{fmtLevel(upper2Sigma)}</div>
          <div className="text-text-muted">+2σ (95%)</div>
        </div>
      </div>
    </div>
  );
}

function PremiumRow({ label, value, colour }: { label: string; value: number; colour: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-text-muted">{label}</span>
      <span className={`text-xs font-mono tabular-nums font-semibold ${colour}`}>
        ₹{fmtLevel(value)}
      </span>
    </div>
  );
}

interface ImpliedMovePanelProps {
  data: ImpliedMoveData | null;
  expiryLabel: string;
}

/**
 * The σ-band expected range. Renders figures only when the live chain has
 * produced a complete ATM straddle; otherwise it discloses the absence in the
 * same voice as the chart view's empty states. There is no sample fallback.
 */
function ImpliedMovePanel({ data, expiryLabel }: ImpliedMovePanelProps) {
  if (!data) {
    return (
      <div
        className="h-full flex flex-col items-center justify-center gap-2 px-4 text-center text-xs text-text-muted"
        aria-label="Implied move unavailable"
      >
        <MoveHorizontal size={20} className="text-accent/40" />
        <span
          className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          aria-label="No live option chain — implied move is unavailable"
          title="Implied move is computed from the live ATM straddle; no sample figures are ever shown."
        >
          No live data
        </span>
        <span>Implied move needs a live ATM straddle quote</span>
        <span className="text-text-muted/60">
          Connect a broker and select an expiry — every figure here is derived from the
          live chain, never sampled
        </span>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto px-3 py-3 space-y-4">

      {/* Key stat */}
      <div className="flex items-center justify-between bg-surface-card rounded-lg px-3 py-2.5 border border-border-default">
        <div>
          <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">
            Implied Move{expiryLabel ? ` (${expiryLabel})` : ""}
          </div>
          <div className="text-lg font-bold font-mono tabular-nums text-text-primary">
            ±₹{fmtLevel(data.impliedMove)}
          </div>
          <div className="text-xs text-text-muted font-mono">
            ±{data.impliedMovePct.toFixed(2)}% of spot
          </div>
        </div>
        <div className="text-right">
          <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">ATM Strike</div>
          <div className="text-base font-bold font-mono tabular-nums text-text-secondary">
            {fmtLevel(data.atmStrike)}
          </div>
          <div className="text-xxs text-text-muted">Spot {fmtLevel(data.spot)}</div>
        </div>
      </div>

      {/* Range visualisation */}
      <section aria-labelledby="im-range">
        <p id="im-range" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-3">
          Expected Range
        </p>
        <RangeBar data={data} />
      </section>

      {/* Premium breakdown */}
      <section
        aria-labelledby="im-premium"
        className="bg-surface-card rounded-lg border border-border-default px-3 py-2.5 space-y-1.5"
      >
        <p id="im-premium" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-2">
          ATM Straddle Premiums
        </p>
        <PremiumRow label="ATM CE Premium" value={data.cePremium} colour="text-profit" />
        <PremiumRow label="ATM PE Premium" value={data.pePremium} colour="text-loss" />
        <div className="border-t border-border-subtle pt-1.5">
          <PremiumRow label="Total (Implied Move)" value={data.impliedMove} colour="text-accent" />
        </div>
      </section>

      {/* Probability zones table */}
      <section aria-labelledby="im-zones">
        <p id="im-zones" className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1.5">
          Probability Zones
        </p>
        <table className="w-full text-xs" aria-label="Probability zones table">
          <thead>
            <tr className="border-b border-border-subtle">
              <th className="text-left py-1 text-xxs text-text-muted font-medium">Zone</th>
              <th className="text-center py-1 text-xxs text-text-muted font-medium">Lower</th>
              <th className="text-center py-1 text-xxs text-text-muted font-medium">Upper</th>
              <th className="text-right py-1 text-xxs text-text-muted font-medium">Prob.</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-border-subtle">
              <td className="py-1 text-text-secondary">1σ</td>
              <td className="py-1 text-center font-mono tabular-nums text-loss">{fmtLevel(data.lowerBound)}</td>
              <td className="py-1 text-center font-mono tabular-nums text-profit">{fmtLevel(data.upperBound)}</td>
              <td className="py-1 text-right font-mono text-text-primary">68%</td>
            </tr>
            <tr>
              <td className="py-1 text-text-secondary">2σ</td>
              <td className="py-1 text-center font-mono tabular-nums text-loss">{fmtLevel(data.lower2Sigma)}</td>
              <td className="py-1 text-center font-mono tabular-nums text-profit">{fmtLevel(data.upper2Sigma)}</td>
              <td className="py-1 text-right font-mono text-text-primary">95%</td>
            </tr>
          </tbody>
        </table>
      </section>

    </div>
  );
}

function StraddleChartFill({ straddlePoints, spotPoints, synfutPoints, activeOverlays }: StraddleChartFillProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(180);

  useEffect(() => {
    if (!wrapRef.current) return;
    if (typeof ResizeObserver === "undefined") {
      const measuredHeight = wrapRef.current.getBoundingClientRect().height;
      setHeight(Math.max(80, measuredHeight || 180));
      return;
    }

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setHeight(Math.max(80, entry.contentRect.height));
      }
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={wrapRef} className="w-full h-full">
      <StraddleChart
        dataPoints={straddlePoints}
        spotPoints={spotPoints}
        synfutPoints={synfutPoints}
        activeOverlays={activeOverlays}
        height={height}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function StraddleWidget(props: WidgetProps) {
  const panelParams = props.params as StraddlePanelParams | undefined;
  const panelView = panelParams?.view;

  const track = useTrackBehavior();
  const [view, setView] = useState<ViewMode>(() => resolveViewMode(panelView));
  const [activeSymbolIdx, setActiveSymbolIdx] = useState(0);
  const [expiries, setExpiries]               = useState<string[]>([]);
  const [selectedExpiry, setSelectedExpiry]   = useState<string | null>(null);
  const [activeOverlays, setActiveOverlays]   = useState<OverlayName[]>(["Straddle"]);

  const [chain, setChain]         = useState<RawOptionChain | null>(null);
  const [spot, setSpot]           = useState<Quote | null>(null);
  const [positions, setPositions] = useState<Position[] | null>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const straddlePointsRef = useRef<ChartPoint[]>([]);
  const spotPointsRef     = useRef<ChartPoint[]>([]);
  const synfutPointsRef   = useRef<ChartPoint[]>([]);
  const [chartVersion, setChartVersion] = useState(0);

  const symDef   = SYMBOLS[activeSymbolIdx];
  const exchange = symDef.exchange;

  // fetch expiries
  useEffect(() => {
    setExpiries([]);
    setSelectedExpiry(null);
    setChain(null);
    setError(null);
    straddlePointsRef.current = [];
    spotPointsRef.current     = [];
    synfutPointsRef.current   = [];

    let cancelled = false;
    (async () => {
      try {
        const data = await getExpiry(symDef.label, exchange);
        if (cancelled) return;
        const list = Array.isArray(data) ? data as string[] : ((data as { expiry?: string[] })?.expiry ?? []);
        setExpiries(list);
        if (list.length > 0) setSelectedExpiry(list[0]);
      } catch (e) {
        if (!cancelled) setError(`Expiry load failed: ${(e as Error).message}`);
      }
    })();

    return () => { cancelled = true; };
  }, [activeSymbolIdx, symDef.label, exchange]);

  // main data fetch
  const fetchData = useCallback(async () => {
    if (!selectedExpiry) return;
    setLoading(true);
    setError(null);

    try {
      const [chainRes, spotRes, posRes] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
        getPositionbook(),
      ]);

      let newChain: RawOptionChain | null = null;
      let newSpot: Quote | null  = null;

      if (chainRes.status === "fulfilled") {
        newChain = chainRes.value as unknown as RawOptionChain;
        setChain(newChain);
      } else {
        setError(`Chain error: ${(chainRes.reason as Error)?.message}`);
      }

      if (spotRes.status === "fulfilled") {
        newSpot = spotRes.value;
        setSpot(newSpot);
      }

      if (posRes.status === "fulfilled") {
        setPositions(posRes.value);
      }

      // Accumulate chart data points
      if (newChain && newSpot) {
        const spotLtp = Number(newSpot.ltp ?? 0);
        const atm = findAtm(newChain, spotLtp);
        if (atm != null) {
          const ce = findOption(chainCalls(newChain), atm);
          const pe = findOption(chainPuts(newChain), atm);
          const ceLtp = Number(ce?.ltp ?? ce?.last_price ?? 0);
          const peLtp = Number(pe?.ltp ?? pe?.last_price ?? 0);
          const straddleVal = ceLtp + peLtp;

          if (straddleVal > 0) {
            const t = toChartTime(new Date());

            appendPoint(straddlePointsRef.current, { time: t, value: straddleVal });

            if (spotLtp > 0) {
              appendPoint(spotPointsRef.current, { time: t, value: spotLtp });
            }

            const synfutVal = spotLtp + ceLtp - peLtp;
            if (synfutVal > 0) {
              appendPoint(synfutPointsRef.current, { time: t, value: synfutVal });
            }

            setChartVersion((v) => v + 1);
          }
        }
      }
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, [selectedExpiry, symDef, exchange]);

  // auto-refresh
  useEffect(() => {
    fetchData();
    const interval = isMarketHours() ? 3000 : 30000;
    const id = setInterval(fetchData, interval);
    return () => clearInterval(id);
  }, [fetchData]);

  // derived values
  const { atmStrike, ceLtp, peLtp, straddlePrice, pnl } = useMemo(() => {
    if (!chain || !spot) {
      return { atmStrike: null, ceLtp: null, peLtp: null, straddlePrice: null, pnl: null };
    }

    const spotLtp = Number(spot.ltp ?? 0);
    const atm     = findAtm(chain, spotLtp);
    if (atm == null) return { atmStrike: null, ceLtp: null, peLtp: null, straddlePrice: null, pnl: null };

    const ce = findOption(chainCalls(chain), atm);
    const pe = findOption(chainPuts(chain), atm);

    const ceLtpVal = Number(ce?.ltp ?? ce?.last_price ?? 0) || null;
    const peLtpVal = Number(pe?.ltp ?? pe?.last_price ?? 0) || null;
    const straddleVal = (ceLtpVal != null && peLtpVal != null) ? ceLtpVal + peLtpVal : null;

    let pnlVal: number | null = null;
    if (positions && Array.isArray(positions)) {
      const straddlePos = positions.filter((p) => {
        const sym = ((p as unknown as { symbol?: string; tradingsymbol?: string }).symbol ?? (p as unknown as { tradingsymbol?: string }).tradingsymbol ?? "").toUpperCase();
        return sym.includes(String(atm)) && (sym.endsWith("CE") || sym.endsWith("PE"));
      });
      if (straddlePos.length > 0) {
        pnlVal = straddlePos.reduce((s, p) => {
          return s + Number(p.pnl ?? 0);
        }, 0);
      }
    }

    return { atmStrike: atm, ceLtp: ceLtpVal, peLtp: peLtpVal, straddlePrice: straddleVal, pnl: pnlVal };
  }, [chain, spot, positions]);

  function toggleOverlay(name: OverlayName) {
    setActiveOverlays((prev) =>
      prev.includes(name) ? prev.filter((o) => o !== name) : [...prev, name]
    );
  }

  const expiryButtons = expiries.slice(0, 5);
  const spotLtp = spot?.ltp ?? null;
  const spotChange = spot?.ltp && spot.prev_close
    ? Number(spot.ltp) - Number(spot.prev_close)
    : null;
  const spotUp = spotChange == null ? null : spotChange >= 0;

  // Implied-move bands — the same four live values the headline already uses,
  // so the σ view costs no extra request.
  const impliedMove = useMemo(
    () => computeImpliedMove({ spot: spotLtp, atmStrike, cePremium: ceLtp, pePremium: peLtp }),
    [spotLtp, atmStrike, ceLtp, peLtp],
  );

  useEffect(() => {
    track("trade", view === "impliedmove" ? "widget_view_implied_move" : "widget_view_straddle");
  }, [track, view]);

  // Persist the chosen view into the panel params so a saved layout reopens in
  // the same presentation (and the retired `impliedmove` id keeps its view).
  const handleViewChange = useCallback((next: ViewMode) => {
    if (next === view) return;
    setView(next);
    props.api.updateParameters({ view: next });
  }, [props.api, view]);

  // Stable chart data arrays. The three memos below snapshot mutable refs that
  // the tick handler appends to in place; `chartVersion` is bumped whenever it
  // does. That counter is therefore the real dependency, and a ref read is
  // invisible to the dependency checker, hence the three directives.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
  const chartStraddlePoints = useMemo(() => [...straddlePointsRef.current], [chartVersion]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
  const chartSpotPoints     = useMemo(() => [...spotPointsRef.current],     [chartVersion]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
  const chartSynfutPoints   = useMemo(() => [...synfutPointsRef.current],   [chartVersion]);

  const hasChartData = chartStraddlePoints.length > 0;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none">

      {/* Header */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5 space-y-1.5">

        {/* Row 1 */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <Selector
            value={symDef.label}
            options={SYMBOLS.map((s) => s.label)}
            onChange={(val) => {
              const idx = SYMBOLS.findIndex((s) => s.label === val);
              setActiveSymbolIdx(idx);
            }}
          />

          <div className="flex items-center gap-1">
            {expiryButtons.length === 0 && !loading && (
              <span className="text-xs text-text-muted px-1">No expiries</span>
            )}
            {expiryButtons.map((exp) => (
              <button
                key={exp}
                onClick={() => setSelectedExpiry(exp)}
                className={`px-2 py-0.5 text-xs font-medium rounded border transition-colors ${
                  exp === selectedExpiry
                    ? "bg-accent/15 border-accent/60 text-accent"
                    : "bg-surface-hover border-border-default text-text-secondary hover:text-text-primary hover:border-accent/30"
                }`}
              >
                {fmtExpiry(exp)}
              </button>
            ))}
          </div>

          <div className="flex-1" />

          {/* View toggle — chart plane vs σ-band plane, one fetch behind both */}
          <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
            {VIEW_MODES.map((m) => (
              <button
                key={m}
                onClick={() => handleViewChange(m)}
                className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                  m === view
                    ? "bg-accent/15 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                }`}
                aria-pressed={m === view}
              >
                {VIEW_LABELS[m]}
              </button>
            ))}
          </div>

          {atmStrike != null && (
            <span className="px-2 py-0.5 text-xs font-mono tabular-nums font-semibold text-accent bg-accent/10 border border-accent/30 rounded">
              ATM {NUM0.format(atmStrike)}
            </span>
          )}

          <button
            onClick={fetchData}
            disabled={loading}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Row 2: spot + P&L */}
        <div className="flex items-center gap-3 flex-wrap">
          {spotLtp != null ? (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-text-muted uppercase tracking-wide">Spot</span>
              <span className="font-mono tabular-nums text-sm font-semibold text-text-primary">
                {NUM.format(spotLtp)}
              </span>
              {spotChange != null && (
                <span className={`flex items-center gap-0.5 text-xs font-mono tabular-nums ${spotUp ? "text-profit" : "text-loss"}`}>
                  {spotUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                  {spotChange >= 0 ? "+" : ""}{spotChange.toFixed(1)}
                </span>
              )}
            </div>
          ) : (
            <span className="text-xs text-text-muted">Spot: —</span>
          )}

          {pnl != null && (
            <div className={`flex items-center gap-1 ml-2 px-2 py-0.5 rounded border text-xs font-mono tabular-nums font-semibold ${
              pnl >= 0
                ? "text-profit bg-profit/10 border-profit/30"
                : "text-loss bg-loss/10 border-loss/30"
            }`}>
              P&L {pnl >= 0 ? "+" : ""}{NUM.format(pnl)}
            </div>
          )}

          {lastRefresh && (
            <div className="flex items-center gap-1 ml-auto text-xs text-text-muted">
              <Activity size={9} />
              {lastRefresh.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
              <span className="ml-1">{isMarketHours() ? "· 3s" : "· 30s"}</span>
            </div>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{error}</span>
        </div>
      )}

      {/* Headline prices */}
      <div className="flex-none">
        <PriceHeadline
          straddlePrice={straddlePrice}
          cePrice={ceLtp}
          pePrice={peLtp}
        />
      </div>

      {/* Overlay toggles — chart view only; the σ view has no series to toggle */}
      {view === "straddle" && (
      <div className="flex-none flex items-center gap-1 px-2 py-1 bg-surface-card border-b border-border-default">
        <span className="text-xs text-text-muted mr-1">Overlay</span>
        {OVERLAYS.map((name) => {
          const color = name === "Straddle" ? "#3b82f6" : name === "Spot" ? "#eab308" : "#a78bfa";
          const active = activeOverlays.includes(name);
          return (
            <button
              key={name}
              onClick={() => toggleOverlay(name)}
              className={`px-2 py-0.5 text-xs font-medium rounded border transition-colors ${
                active
                  ? "bg-surface-hover border-border-default text-text-primary"
                  : "border-transparent text-text-muted hover:text-text-secondary"
              }`}
            >
              {active && (
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full mr-1 align-middle"
                  style={{ background: color }}
                />
              )}
              {name}
            </button>
          );
        })}
      </div>
      )}

      {/* Body — chart plane or σ-band plane */}
      <div className="flex-1 overflow-hidden relative">
        {view === "impliedmove" ? (
          loading && !chain ? (
            <LoadingBody />
          ) : (
            <ImpliedMovePanel
              data={impliedMove}
              expiryLabel={selectedExpiry ? fmtExpiry(selectedExpiry) : ""}
            />
          )
        ) : !selectedExpiry && !loading ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs">
            Select an expiry to load straddle data
          </div>
        ) : loading && !chain ? (
          <LoadingBody />
        ) : !hasChartData ? (
          <div className="h-full flex flex-col items-center justify-center text-text-muted text-xs gap-2">
            <Activity size={20} className="text-accent/40" />
            <span>Live tracking will start on next tick</span>
            <span className="text-xs text-text-muted/60">
              Straddle price will accumulate here during market hours
            </span>
          </div>
        ) : (
          <StraddleChartFill
            straddlePoints={chartStraddlePoints}
            spotPoints={chartSpotPoints}
            synfutPoints={chartSynfutPoints}
            activeOverlays={activeOverlays}
          />
        )}
      </div>
    </div>
  );
}

export default memo(StraddleWidget);
