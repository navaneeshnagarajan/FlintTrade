/**
 * DrawdownView — ported from the P&L Dashboard tool's Drawdown tab (2.10).
 *
 * Daily realised P&L series from the tradebook (lib/pnl `realisedFromTrades`
 * per day — the shared FIFO pairing), a cumulative equity curve and a
 * percent-of-peak drawdown chart.
 *
 * NOTE on drawdown units: this view reports drawdown as a PERCENT of the
 * cumulative-P&L peak across trading days; the Live view's "Max DD" card is
 * an ABSOLUTE rupee figure within the current session. Those are different
 * measures over different windows, deliberately kept distinct — the labels on
 * both say which is which.
 *
 * Known limitation carried from the tool: the broker tradebook covers the
 * current session, so in Live mode this usually shows a single-day series;
 * multi-day depth comes from Practice/Explore data or brokers that return
 * history. The daily realised figure understates positions opened on a prior
 * day (no matching buy leg) — the same limitation lib/pnl documents.
 */

import { useEffect, useMemo, useRef } from "react";
import type { Time } from "lightweight-charts";
import { BarChart2 } from "lucide-react";
import { createFlintAreaChart } from "@flinttrade/design-system";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightAreaRuntime } from "@/lib/lightweightChartRuntime";
import { realisedFromTrades } from "@/lib/pnl";
import type { Trade } from "@/types/api";
import { formatCompactINR, pnlColor } from "./pnlMonitorShared";

// ---------------------------------------------------------------------------
// Derivations (ported verbatim from the tool — pinned by tests)
// ---------------------------------------------------------------------------

interface DailyPnl {
  date: string; // YYYY-MM-DD
  pnl: number;
}

function computeDailyPnl(trades: Trade[]): DailyPnl[] {
  // Group by date; realised P&L per day is the shared per-symbol FIFO pairing.
  const byDate: Record<string, Trade[]> = {};
  trades.forEach((t) => {
    const date = t.timestamp?.slice(0, 10) ?? "unknown";
    if (!byDate[date]) byDate[date] = [];
    byDate[date].push(t);
  });

  return Object.entries(byDate)
    .map(([date, dayTrades]) => ({ date, pnl: realisedFromTrades(dayTrades) }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function computeDrawdown(daily: DailyPnl[]): { drawdowns: { date: string; dd: number }[]; maxDrawdown: number } {
  let peak = 0;
  let cum = 0;
  let maxDrawdown = 0;
  const drawdowns = daily.map(({ date, pnl }) => {
    cum += pnl;
    if (cum > peak) peak = cum;
    const dd = peak > 0 ? ((cum - peak) / peak) * 100 : 0;
    if (dd < maxDrawdown) maxDrawdown = dd;
    return { date, dd };
  });
  return { drawdowns, maxDrawdown };
}

// ---------------------------------------------------------------------------
// Area chart fragment (ported from the tool)
// ---------------------------------------------------------------------------

function PnlAreaChart({
  ariaLabel,
  className,
  data,
  tone,
}: {
  ariaLabel: string;
  className: string;
  data: { date: string; value: number }[];
  tone: "profit" | "loss";
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const theme = useLightweightChartTheme();
  const lineColor = tone === "profit" ? "#34d399" : "#f87171";
  const topColor = tone === "profit" ? "rgba(52, 211, 153, 0.32)" : "rgba(248, 113, 113, 0.28)";
  const bottomColor = tone === "profit" ? "rgba(52, 211, 153, 0.04)" : "rgba(248, 113, 113, 0.04)";

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const flintChart = createFlintAreaChart(
      lightweightAreaRuntime,
      container,
      theme,
      {
        ariaLabel,
        height: container.clientHeight || 144,
        resize: "observer",
        rightPriceScale: { borderVisible: false },
        timeScale: { borderVisible: false },
        series: [
          {
            id: "pnl",
            options: {
              bottomColor,
              lastValueVisible: false,
              lineColor,
              lineWidth: 2,
              priceLineVisible: false,
              priceScaleId: "right",
              topColor,
            },
          },
        ],
      },
    );

    flintChart.seriesById.pnl.setData(
      data.map(({ date, value }) => ({
        time: date as unknown as Time,
        value,
      })),
    );

    return () => {
      flintChart.remove();
    };
  }, [ariaLabel, bottomColor, data, lineColor, theme, topColor]);

  return <div ref={containerRef} className={className} />;
}

// ---------------------------------------------------------------------------
// Drawdown view
// ---------------------------------------------------------------------------

export interface DrawdownViewProps {
  trades: Trade[];
}

export function DrawdownView({ trades }: DrawdownViewProps) {
  const daily = useMemo(() => computeDailyPnl(trades), [trades]);
  const { drawdowns, maxDrawdown } = useMemo(() => computeDrawdown(daily), [daily]);

  const cumulativeSeries = useMemo(() => {
    let cum = 0;
    return daily.map(({ date, pnl }) => { cum += pnl; return { date, cum }; });
  }, [daily]);
  const equityChartData = useMemo(
    () => cumulativeSeries.map(({ date, cum }) => ({ date, value: cum })),
    [cumulativeSeries],
  );
  const drawdownChartData = useMemo(
    () => drawdowns.map(({ date, dd }) => ({ date, value: dd })),
    [drawdowns],
  );

  if (daily.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
        <BarChart2 size={40} />
        <p className="text-sm">No historical trade data</p>
      </div>
    );
  }

  const finalCum = cumulativeSeries[cumulativeSeries.length - 1]?.cum ?? 0;

  return (
    <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Max Drawdown</div>
            <div className={`text-xl font-bold font-mono tabular-nums ${maxDrawdown < 0 ? "text-loss" : "text-profit"}`}>
              {maxDrawdown.toFixed(2)}%
            </div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Net Cumulative P&amp;L</div>
            <div className={`text-xl font-bold font-mono tabular-nums ${pnlColor(finalCum)}`}>
              {formatCompactINR(finalCum)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Equity curve */}
      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Equity Curve</CardTitle>
        </CardHeader>
        <CardContent className="p-3 pt-1">
          <PnlAreaChart
            ariaLabel="P&L monitor equity curve chart"
            className="h-36 min-h-32 w-full"
            data={equityChartData}
            tone={finalCum >= 0 ? "profit" : "loss"}
          />
        </CardContent>
      </Card>

      {/* Drawdown chart */}
      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Drawdown (%)</CardTitle>
        </CardHeader>
        <CardContent className="p-3 pt-1">
          <PnlAreaChart
            ariaLabel="P&L monitor drawdown chart"
            className="h-24 min-h-24 w-full"
            data={drawdownChartData}
            tone="loss"
          />
        </CardContent>
      </Card>
    </div>
  );
}
