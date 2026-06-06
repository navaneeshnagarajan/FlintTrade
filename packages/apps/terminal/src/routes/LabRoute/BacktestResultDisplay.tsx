import { useEffect, useMemo, useRef } from "react";
import { motion } from "framer-motion";
import type { Time } from "lightweight-charts";
import { createFlintHistogramChart } from "@flinttrade/design-system";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightHistogramRuntime } from "@/lib/lightweightChartRuntime";
import { motionConfig } from "@/lib/motion";
import { type BacktestResult } from "@/services/ftApi";
import { fmtInr, fmtPct, fmtNum } from "./formatters";
import { AnimatedMetricCard, MetricCard } from "./MetricCards";
import { EquityCurve } from "./EquityCurve";
import { RobustnessCard } from "./RobustnessCard";

export interface BacktestResultDisplayProps {
  result: BacktestResult;
}

interface MonthlyPnlPoint {
  month: string;
  pnl: number;
}

function monthToUtcTimestamp(month: string): Time {
  return Math.floor(new Date(`${month}-01T00:00:00.000Z`).getTime() / 1000) as unknown as Time;
}

function MonthlyPnlChart({ data }: { data: MonthlyPnlPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartTheme = useLightweightChartTheme();

  const histogramData = useMemo(
    () =>
      data.map((point) => ({
        time: monthToUtcTimestamp(point.month),
        value: point.pnl,
        color: point.pnl >= 0 ? "#34d399" : "#f87171",
      })),
    [data],
  );

  useEffect(() => {
    if (!containerRef.current || histogramData.length === 0) return;

    const flintChart = createFlintHistogramChart(
      lightweightHistogramRuntime,
      containerRef.current,
      chartTheme,
      {
        ariaLabel: "Monthly P&L chart",
        height: 144,
        crosshair: { vertLine: { visible: true }, horzLine: { visible: true } },
        handleScroll: false,
        handleScale: false,
        defaultSeriesOptions: {
          color: "#34d399",
          priceFormat: { type: "price", precision: 0, minMove: 1 },
          priceScaleId: "right",
          priceLineVisible: false,
          lastValueVisible: true,
        },
        series: [{ id: "monthly-pnl" }],
      },
    );

    flintChart.seriesById["monthly-pnl"].setData(histogramData);
    flintChart.chart.timeScale().fitContent();

    return () => {
      flintChart.remove();
    };
  }, [chartTheme, histogramData]);

  if (data.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={motionConfig.transitions.fade}
    >
      <div
        ref={containerRef}
        className="h-36 min-h-36 w-full overflow-hidden rounded-md border border-border-default bg-surface-card"
        style={{ height: 144 }}
      />
    </motion.div>
  );
}

export function BacktestResultDisplay({ result }: BacktestResultDisplayProps) {
  const { metrics, trades, equity_curve, final_equity } = result;
  const totalReturnPositive = metrics.total_return >= 0;
  const initialEquity =
    equity_curve.length > 0 ? equity_curve[0].equity : final_equity;

  const monthlyPnl = useMemo(() => {
    const grouped: Record<string, number> = {};
    trades.forEach((t) => {
      const month = t.exit_timestamp.slice(0, 7);
      grouped[month] = (grouped[month] ?? 0) + t.pnl;
    });
    return Object.entries(grouped)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, pnl]) => ({ month, pnl }));
  }, [trades]);

  return (
    <div className="space-y-4">
      <GlassCard className="p-5 gap-3">
        <h4 className="font-heading font-semibold text-sm text-text-primary">
          Performance Metrics
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <AnimatedMetricCard
            label="Sharpe Ratio"
            numericValue={metrics.sharpe_ratio}
            displayValue={fmtNum(metrics.sharpe_ratio)}
            positive={metrics.sharpe_ratio > 1}
            formatter={(v) => v.toFixed(2)}
          />
          <AnimatedMetricCard
            label="Max Drawdown"
            numericValue={Math.abs(metrics.max_drawdown) * 100}
            displayValue={fmtPct(Math.abs(metrics.max_drawdown))}
            positive={false}
            formatter={(v) => v.toFixed(2) + "%"}
          />
          <AnimatedMetricCard
            label="Win Rate"
            numericValue={metrics.win_rate * 100}
            displayValue={fmtPct(metrics.win_rate)}
            positive={metrics.win_rate >= 0.5}
            formatter={(v) => v.toFixed(2) + "%"}
          />
          <AnimatedMetricCard
            label="Profit Factor"
            numericValue={metrics.profit_factor}
            displayValue={fmtNum(metrics.profit_factor)}
            positive={metrics.profit_factor > 1}
            formatter={(v) => v.toFixed(2)}
          />
          <MetricCard
            label="Total Return"
            value={fmtPct(metrics.total_return)}
            positive={totalReturnPositive}
          />
          <MetricCard
            label="Final Equity"
            value={fmtInr(final_equity)}
            positive={null}
          />
          <MetricCard
            label="Sortino Ratio"
            value={fmtNum(metrics.sortino_ratio)}
            positive={metrics.sortino_ratio > 1}
          />
          <MetricCard
            label="Total Trades"
            value={String(metrics.total_trades)}
            positive={null}
          />
          <MetricCard
            label="Expectancy"
            value={fmtInr(metrics.expectancy)}
            positive={metrics.expectancy >= 0}
          />
        </div>
      </GlassCard>

      {equity_curve.length > 0 && (
        <GlassCard className="p-5 gap-3">
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Equity Curve
          </h4>
          <EquityCurve curve={equity_curve} initialEquity={initialEquity} />
        </GlassCard>
      )}

      {equity_curve.length > 0 && <RobustnessCard result={result} />}

      {monthlyPnl.length > 0 && (
        <GlassCard className="p-5 gap-3">
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Monthly P&L
          </h4>
          <MonthlyPnlChart data={monthlyPnl} />
        </GlassCard>
      )}

      {trades.length > 0 && (
        <GlassCard className="p-5 gap-3">
          <h4 className="font-heading font-semibold text-sm text-text-primary">
            Trade Log
            <span className="ml-2 text-xs text-text-muted font-normal">
              ({trades.length} trades)
            </span>
          </h4>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default">
                  <TableHead className="text-text-muted text-xs">Entry</TableHead>
                  <TableHead className="text-text-muted text-xs">Exit</TableHead>
                  <TableHead className="text-text-muted text-xs">Symbol</TableHead>
                  <TableHead className="text-text-muted text-xs">Side</TableHead>
                  <TableHead className="text-text-muted text-xs text-right">Entry ₹</TableHead>
                  <TableHead className="text-text-muted text-xs text-right">Exit ₹</TableHead>
                  <TableHead className="text-text-muted text-xs text-right">P&L</TableHead>
                  <TableHead className="text-text-muted text-xs text-right">Bars</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade, i) => (
                  <TableRow key={i} className="border-border-default">
                    <TableCell className="text-xxs text-text-secondary font-mono">
                      {trade.entry_timestamp.slice(0, 16).replace("T", " ")}
                    </TableCell>
                    <TableCell className="text-xxs text-text-secondary font-mono">
                      {trade.exit_timestamp.slice(0, 16).replace("T", " ")}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-text-primary">
                      {trade.symbol}
                    </TableCell>
                    <TableCell>
                      <Badge
                        className={`text-xxs ${
                          trade.side === "BUY"
                            ? "bg-bullish-bg text-profit"
                            : "bg-bearish-bg text-loss"
                        }`}
                      >
                        {trade.side}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xxs font-mono text-text-secondary text-right">
                      {trade.entry_price.toLocaleString("en-IN")}
                    </TableCell>
                    <TableCell className="text-xxs font-mono text-text-secondary text-right">
                      {trade.exit_price.toLocaleString("en-IN")}
                    </TableCell>
                    <TableCell
                      className={`text-xs font-mono font-semibold text-right ${
                        trade.pnl >= 0 ? "text-profit" : "text-loss"
                      }`}
                    >
                      {fmtInr(trade.pnl)}
                    </TableCell>
                    <TableCell className="text-xxs font-mono text-text-muted text-right">
                      {trade.bars_held}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </GlassCard>
      )}
    </div>
  );
}
