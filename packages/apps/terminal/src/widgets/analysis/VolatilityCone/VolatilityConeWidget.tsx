/**
 * VolatilityConeWidget — Historical volatility cone analysis.
 *
 * Features:
 *   - HV at 5 / 10 / 20 / 30 / 60 / 90 day lookback periods
 *   - Percentile bands: 10th, 25th, 50th (median), 75th, 90th — filled SVG areas
 *   - Current IV plotted as a dot at each lookback period
 *   - Helps identify if current IV is cheap or expensive vs history
 *   - Pure SVG rendering — no external chart library
 */

import { useState, useEffect, useMemo, memo } from "react";
import { Triangle, ChevronDown, Loader2 } from "lucide-react";
import { FlintBandedLineChart } from "@flinttrade/design-system";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getHistory } from "@/services/api";
import { getVolatilityCone } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ConePoint {
  period: number;       // days
  p10: number;          // 10th percentile HV
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  currentIV: number;    // spot IV at this lookback period
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const SAMPLE_CONE: ConePoint[] = [
  { period: 5,  p10: 8.2,  p25: 11.4, p50: 15.8, p75: 20.3, p90: 26.1, currentIV: 17.4 },
  { period: 10, p10: 9.1,  p25: 12.3, p50: 16.5, p75: 21.2, p90: 27.4, currentIV: 18.2 },
  { period: 20, p10: 10.5, p25: 13.8, p50: 17.9, p75: 22.8, p90: 29.2, currentIV: 19.1 },
  { period: 30, p10: 11.2, p25: 14.6, p50: 18.7, p75: 23.5, p90: 30.4, currentIV: 20.3 },
  { period: 60, p10: 12.8, p25: 16.1, p50: 20.4, p75: 25.9, p90: 33.1, currentIV: 21.8 },
  { period: 90, p10: 13.4, p25: 17.0, p50: 21.6, p75: 27.2, p90: 34.8, currentIV: 22.5 },
];

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

/** Cone lookback windows (trading days) — matches the backend default + SAMPLE_CONE. */
const LOOKBACK_PERIODS = [5, 10, 20, 30, 60, 90];

const EXCHANGES: Record<string, string> = {
  NIFTY: "NSE_INDEX",
  BANKNIFTY: "NSE_INDEX",
  FINNIFTY: "NSE_INDEX",
  MIDCPNIFTY: "NSE_INDEX",
  SENSEX: "BSE_INDEX",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ivStatus(iv: number, p25: number, p75: number): "cheap" | "fair" | "expensive" {
  if (iv < p25) return "cheap";
  if (iv > p75) return "expensive";
  return "fair";
}

const STATUS_COLOUR: Record<string, string> = {
  cheap: "text-profit",
  fair: "text-warning",
  expensive: "text-loss",
};

function buildConeChart(points: ConePoint[], metricLabel: string) {
  const allValues = points.flatMap((p) => [p.p10, p.p90, p.currentIV]);
  const minValue = Math.min(...allValues) * 0.9;
  const maxValue = Math.max(...allValues) * 1.1;
  const pointFor = (point: ConePoint, value: number, index: number) => ({
    x: index,
    y: value,
    label: `${point.period}d ${value.toFixed(1)}%`,
  });
  const lineFor = (key: keyof Pick<ConePoint, "p10" | "p25" | "p50" | "p75" | "p90">) => (
    points.map((point, index) => pointFor(point, point[key], index))
  );

  return {
    bands: [
      {
        id: "p75-p90",
        label: "Expensive percentile band",
        color: "rgba(239,68,68,0.12)",
        upper: lineFor("p90"),
        lower: lineFor("p75"),
      },
      {
        id: "p25-p75",
        label: "Normal percentile band",
        color: "rgba(99,102,241,0.12)",
        upper: lineFor("p75"),
        lower: lineFor("p25"),
      },
      {
        id: "p10-p25",
        label: "Cheap percentile band",
        color: "rgba(34,197,94,0.12)",
        upper: lineFor("p25"),
        lower: lineFor("p10"),
      },
    ],
    series: [
      { id: "p90", label: "90th percentile", color: "rgba(239,68,68,0.4)", dash: "3,2", strokeWidth: 1, points: lineFor("p90") },
      { id: "p75", label: "75th percentile", color: "rgba(239,68,68,0.25)", strokeWidth: 0.75, points: lineFor("p75") },
      { id: "p50", label: "Median", color: "rgba(99,102,241,0.5)", dash: "4,2", strokeWidth: 1.25, points: lineFor("p50") },
      { id: "p25", label: "25th percentile", color: "rgba(34,197,94,0.25)", strokeWidth: 0.75, points: lineFor("p25") },
      { id: "p10", label: "10th percentile", color: "rgba(34,197,94,0.4)", dash: "3,2", strokeWidth: 1, points: lineFor("p10") },
    ],
    markers: points.map((point, index) => {
      const status = ivStatus(point.currentIV, point.p25, point.p75);
      return {
        id: `iv-${point.period}`,
        label: `${point.period}d ${metricLabel}: ${point.currentIV.toFixed(1)}% (${status})`,
        x: index,
        y: point.currentIV,
        color: status === "cheap" ? "#22c55e" : status === "expensive" ? "#ef4444" : "#f59e0b",
      };
    }),
    xDomain: [0, Math.max(points.length - 1, 1)] as const,
    yDomain: [minValue, maxValue] as const,
    xTicks: points.map((_, index) => index),
    yTicks: [minValue, (minValue + maxValue) / 2, maxValue],
  };
}

// ---------------------------------------------------------------------------
// Symbol dropdown
// ---------------------------------------------------------------------------

interface SymbolDropdownProps {
  value: string;
  onChange: (v: string) => void;
}

function SymbolDropdown({ value, onChange }: SymbolDropdownProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors min-w-24"
      >
        <span className="flex-1 text-left">{value}</span>
        <ChevronDown size={10} className={`transition-transform flex-none ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full" role="listbox">
          {SYMBOLS.map((s) => (
            <button
              key={s}
              role="option"
              aria-selected={s === value}
              onClick={() => { onChange(s); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${
                s === value ? "text-accent" : "text-text-primary"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function VolatilityConeWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();
  const [symbol, setSymbol] = useState("NIFTY");
  const [liveCone, setLiveCone] = useState<ConePoint[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // When connected, build a REAL cone: daily-return series from history →
  // /v1/analytics/volcone (rolling-HV percentiles). The overlay is current
  // realised HV (honest — no live IV feed), so the marker is labelled "HV".
  // Disconnected / on error → the synthetic SAMPLE_CONE (badged), never a
  // fabricated "live" cone.
  useEffect(() => {
    if (!isConnected) {
      setLiveCone(null);
      setLoadError(null);
      return;
    }
    let cancelled = false;
    const exchange = EXCHANGES[symbol] ?? "NSE_INDEX";
    setIsLoading(true);
    setLoadError(null);

    const today = new Date();
    const endDate = today.toISOString().slice(0, 10);
    // ~220 calendar days ≈ 150 trading bars → enough returns for the 90d window.
    const startDate = new Date(today.getTime() - 220 * 24 * 60 * 60 * 1000)
      .toISOString()
      .slice(0, 10);

    getHistory(symbol, exchange, "D", startDate, endDate)
      .then((bars) => {
        const closes = (Array.isArray(bars) ? bars : [])
          .map((b) => Number(b.close))
          .filter((c) => Number.isFinite(c) && c > 0);
        if (closes.length < Math.max(...LOOKBACK_PERIODS) + 2) {
          throw new Error("Not enough history to build a cone");
        }
        const returns = closes.slice(1).map((c, i) => (c - closes[i]) / closes[i]);
        return getVolatilityCone(returns, LOOKBACK_PERIODS);
      })
      .then((rows) => {
        if (cancelled) return;
        const mapped: ConePoint[] = rows.map((r) => ({
          period: r.lookback,
          p10: r.p10 * 100,
          p25: r.p25 * 100,
          p50: r.p50 * 100,
          p75: r.p75 * 100,
          p90: r.p90 * 100,
          currentIV: r.current_hv * 100,
        }));
        setLiveCone(mapped.length ? mapped : null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLiveCone(null);
        setLoadError(err instanceof Error ? err.message : "Failed to load cone");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => { cancelled = true; };
  }, [symbol, isConnected]);

  const isLive = liveCone !== null;
  const coneData = liveCone ?? SAMPLE_CONE;
  // Live overlay is realised HV; the sample carries a synthetic IV.
  const metricLabel = isLive ? "HV" : "IV";
  const coneChart = useMemo(() => buildConeChart(coneData, metricLabel), [coneData, metricLabel]);

  const handleSymbolChange = (v: string) => {
    setSymbol(v);
    track("trade", "volcone_symbol_change");
  };

  const cheapCount = useMemo(
    () => coneData.filter((p) => ivStatus(p.currentIV, p.p25, p.p75) === "cheap").length,
    [coneData],
  );
  const expensiveCount = useMemo(
    () => coneData.filter((p) => ivStatus(p.currentIV, p.p25, p.p75) === "expensive").length,
    [coneData],
  );

  const overallStatus: "cheap" | "fair" | "expensive" =
    cheapCount >= 4 ? "cheap" : expensiveCount >= 4 ? "expensive" : "fair";

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Triangle size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Volatility Cone</span>
        {isLive ? (
          <span
            className="inline-flex items-center rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400"
            role="status"
            aria-label="Live: HV cone computed from real price history"
            title="Live — historical-volatility percentiles from real price history; the overlay is current realised HV."
          >
            Live
          </span>
        ) : (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample data; connect a broker for a live HV cone"
            title={
              loadError
                ? `Showing sample data — live cone unavailable: ${loadError}`
                : "Sample IV cone so the widget is usable in explore mode — connect a broker for a live HV cone from real price history."
            }
          >
            Sample data
          </span>
        )}
        {isLoading && <Loader2 size={12} className="animate-spin text-text-muted" aria-label="Loading" />}
        <div className="flex-1" />
        <SymbolDropdown value={symbol} onChange={handleSymbolChange} />
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 overflow-hidden px-2 pt-2">
        <FlintBandedLineChart
          ariaLabel="Volatility cone chart"
          bands={coneChart.bands}
          series={coneChart.series}
          markers={coneChart.markers}
          xDomain={coneChart.xDomain}
          yDomain={coneChart.yDomain}
          xTicks={coneChart.xTicks}
          yTicks={coneChart.yTicks}
          xFormatter={(value) => `${coneData[value]?.period ?? value}d`}
          yFormatter={(value) => `${value.toFixed(0)}%`}
          width={520}
          height={200}
        />
      </div>

      {/* Legend */}
      <div className="flex-none px-3 pb-1.5 flex items-center gap-3 flex-wrap text-xxs">
        <div className="flex items-center gap-1">
          <span className="inline-block w-6 h-px" style={{ background: "rgba(239,68,68,0.4)", borderTop: "1px dashed rgba(239,68,68,0.7)" }} />
          <span className="text-text-muted">90th pct</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-6 h-px bg-accent/50" />
          <span className="text-text-muted">Median</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-6 h-px" style={{ background: "rgba(34,197,94,0.4)", borderTop: "1px dashed rgba(34,197,94,0.7)" }} />
          <span className="text-text-muted">10th pct</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-warning" />
          <span className="text-text-muted">Current {metricLabel}</span>
        </div>
      </div>

      {/* Summary row */}
      <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1.5 flex items-center gap-4 flex-wrap text-xs">
        <div className="flex items-center gap-1.5">
          <span className="text-text-muted">{metricLabel} Regime:</span>
          <span className={`font-semibold capitalize ${STATUS_COLOUR[overallStatus]}`}>
            {overallStatus}
          </span>
        </div>
        {coneData.map((p) => (
          <div key={p.period} className="flex items-center gap-1">
            <span className="text-text-muted">{p.period}d</span>
            <span className={`font-mono tabular-nums ${STATUS_COLOUR[ivStatus(p.currentIV, p.p25, p.p75)]}`}>
              {p.currentIV.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default memo(VolatilityConeWidget);
