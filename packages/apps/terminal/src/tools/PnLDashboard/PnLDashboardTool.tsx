// Adapted patterns from:
//   etftracker/frontend/src/pages/Dashboard1_AssetQuilt.tsx — heatmap color scale concept (green/red/gray grid cells)
//   tier1-core/openalgo/frontend/src/pages/PnLTracker.tsx — daily/weekly/monthly summary cards, drawdown calc
//   trading-journal/frontend/app/dashboard/analytics/page.tsx — symbol breakdown bar chart pattern

import { useEffect, useMemo, useRef } from "react";
import { PieChart, X, TrendingUp, TrendingDown, AlertCircle, Calendar, BarChart2, Wallet } from "lucide-react";
import { createFlintAreaChart, FlintDonutBreakdown, FlintRankedBarList } from "@flinttrade/design-system";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { useModeData } from "@/hooks/useModeData";
import { istParts, istToday } from "@/lib/ist";
import { lightweightAreaRuntime } from "@/lib/lightweightChartRuntime";
import { useModeStore } from "@/stores/modeStore";
import type { Funds, Position, Trade } from "@/types/api";
import { realisedFromTrades, totalPositionMtm } from "@/lib/pnl";
import type { Time } from "lightweight-charts";

interface Props {
  onClose?: () => void;
}

// ---- Helpers ----

function formatINR(value: number): string {
  const abs = Math.abs(value);
  let formatted: string;
  if (abs >= 10_000_000) {
    formatted = `${(abs / 10_000_000).toFixed(2)}Cr`;
  } else if (abs >= 100_000) {
    formatted = `${(abs / 100_000).toFixed(2)}L`;
  } else if (abs >= 1_000) {
    formatted = `${(abs / 1_000).toFixed(2)}K`;
  } else {
    formatted = abs.toFixed(2);
  }
  return `${value < 0 ? "-" : ""}₹${formatted}`;
}

function pnlClass(v: number) {
  if (v > 0) return "text-profit";
  if (v < 0) return "text-loss";
  return "text-text-secondary";
}

// Calendar heatmap cell color (adapted from etftracker heatmap colorscale concept)
function heatmapColor(pnl: number, maxAbs: number): string {
  if (maxAbs === 0) return "bg-surface-elevated";
  const ratio = Math.abs(pnl) / maxAbs;
  if (pnl > 0) {
    if (ratio > 0.75) return "bg-emerald-600";
    if (ratio > 0.4) return "bg-emerald-700/80";
    return "bg-emerald-900/60";
  }
  if (pnl < 0) {
    if (ratio > 0.75) return "bg-red-600";
    if (ratio > 0.4) return "bg-red-700/80";
    return "bg-red-900/60";
  }
  return "bg-surface-elevated";
}

// Derive daily P&L series from tradebook
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

// Position breakdown by instrument
interface SymbolPnl {
  symbol: string;
  pnl: number;
  pct: number;
  quantity: number;
}

function computeSymbolBreakdown(positions: Position[]): SymbolPnl[] {
  return positions
    .map((p) => ({ symbol: p.symbol, pnl: p.pnl, pct: p.pnlPercent, quantity: p.quantity }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
}

// Drawdown from cumulative P&L series
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

function PnlBreakdownDonut({ data }: { data: { name: string; value: number }[] }) {
  const colours = ["#34d399", "#60a5fa", "#a78bfa", "#fbbf24", "#fb7185", "#22d3ee"];
  const slices = data.slice(0, 6).map((item, index) => ({
    label: item.name,
    value: item.value,
    color: colours[index % colours.length],
  }));

  return (
    <div className="flex w-full items-center justify-center gap-5">
      <FlintDonutBreakdown
        ariaLabel="P&L breakdown by symbol"
        slices={slices}
        className="size-32"
      />
      <div className="min-w-0 space-y-1">
        {slices.map((slice) => (
          <div key={slice.label} className="flex items-center gap-2 text-xs">
            <span
              className="size-2 rounded-full"
              style={{ backgroundColor: slice.color }}
            />
            <span className="min-w-20 text-text-secondary">{slice.label}</span>
            <span className="font-mono text-text-primary">{formatINR(slice.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PnlBarList({
  data,
  tone,
  ariaLabel,
  valueFormatter = formatINR,
}: {
  data: { name: string; value: number }[];
  tone: "profit" | "loss";
  ariaLabel: string;
  valueFormatter?: (value: number) => string;
}) {
  const color = tone === "profit" ? "var(--color-profit, #34d399)" : "var(--color-loss, #f87171)";

  return (
    <FlintRankedBarList
      ariaLabel={ariaLabel}
      entries={data.map((item) => ({ label: item.name, value: item.value, color }))}
      valueFormatter={valueFormatter}
    />
  );
}

// ---- Sub-tabs ----

function SummaryTab({ positions, funds }: { positions: Position[]; funds: { availableCash: number; usedMargin: number; totalBalance: number } | undefined }) {
  // Shared MTM definition — this summed the raw broker `pnl`, which is
  // wrong for some brokers (CLAUDE.md quirk 4) and disagreed with the
  // Intraday P&L widget for the same book.
  const totalPnl = totalPositionMtm(positions);
  const positivePos = positions.filter((p) => p.pnl > 0);
  const negativePos = positions.filter((p) => p.pnl < 0);

  return (
    <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-2">
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">MTM P&L</div>
            <div className={`text-xl font-bold font-mono tabular-nums ${pnlClass(totalPnl)}`}>{formatINR(totalPnl)}</div>
            <div className="text-xs text-text-muted mt-0.5">{positions.length} open positions</div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Available Margin</div>
            <div className="text-xl font-bold font-mono tabular-nums text-text-primary">{formatINR(funds?.availableCash ?? 0)}</div>
            <div className="text-xs text-text-muted mt-0.5">Used: {formatINR(funds?.usedMargin ?? 0)}</div>
          </CardContent>
        </Card>
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Total Balance</div>
            <div className="text-xl font-bold font-mono tabular-nums text-text-primary">{formatINR(funds?.totalBalance ?? 0)}</div>
            <div className="text-xs text-text-muted mt-0.5">
              {positivePos.length}P / {negativePos.length}N positions
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Symbol P&L donut */}
      {positions.length > 0 && (() => {
        const donutData = computeSymbolBreakdown(positions)
          .filter((s) => s.pnl !== 0)
          .map((s) => ({ name: s.symbol, value: Math.abs(s.pnl) }));
        return donutData.length > 0 ? (
          <Card className="bg-surface-card border-border-default">
            <CardHeader className="p-3 pb-1">
              <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">P&L Breakdown</CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-1 flex items-center justify-center">
              <PnlBreakdownDonut data={donutData} />
            </CardContent>
          </Card>
        ) : null;
      })()}

      {/* Positions breakdown */}
      <Card className="bg-surface-card border-border-default">
        <CardHeader className="p-3 pb-1">
          <CardTitle className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Open Positions</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {positions.length === 0 ? (
            <div className="text-center py-6 text-text-muted text-xs">No open positions</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="text-xs text-text-muted h-7 pl-3 font-normal">Symbol</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 font-normal">Product</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right font-normal">Qty</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right font-normal">Avg</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right font-normal">LTP</TableHead>
                  <TableHead className="text-xs text-text-muted h-7 text-right pr-3 font-normal">P&L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions.map((pos, i) => (
                  <TableRow key={`${pos.symbol}-${i}`} className="border-border-subtle hover:bg-surface-base">
                    <TableCell className="py-1 pl-3 text-xs font-mono text-text-primary font-medium">{pos.symbol}</TableCell>
                    <TableCell className="py-1 text-xs text-text-muted">{pos.product}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">{pos.quantity}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-text-secondary text-right">{pos.averagePrice.toFixed(2)}</TableCell>
                    <TableCell className="py-1 text-xs font-mono text-text-primary text-right">{pos.ltp.toFixed(2)}</TableCell>
                    <TableCell className={`py-1 text-xs font-mono text-right pr-3 ${pnlClass(pos.pnl)}`}>
                      {formatINR(pos.pnl)}
                      <span className={`text-xxs ml-1 ${pnlClass(pos.pnlPercent)}`}>
                        ({pos.pnlPercent >= 0 ? "+" : ""}{pos.pnlPercent.toFixed(2)}%)
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Instrument P&L breakdown */}
      {positions.length > 0 && (() => {
        const breakdown = computeSymbolBreakdown(positions);
        const winners = breakdown.filter((s) => s.pnl >= 0).map((s) => ({ name: s.symbol, value: s.pnl }));
        const losers = breakdown.filter((s) => s.pnl < 0).map((s) => ({ name: s.symbol, value: Math.abs(s.pnl) }));
        return (
          <div className="grid grid-cols-2 gap-2">
            {winners.length > 0 && (
              <Card className="bg-surface-card border-border-default">
                <CardHeader className="p-3 pb-1">
                  <CardTitle className="font-heading font-semibold text-xs text-profit uppercase tracking-wider">Top Winners</CardTitle>
                </CardHeader>
                <CardContent className="p-3 pt-1">
                  <PnlBarList data={winners} tone="profit" ariaLabel="Top winners P&L" />
                </CardContent>
              </Card>
            )}
            {losers.length > 0 && (
              <Card className="bg-surface-card border-border-default">
                <CardHeader className="p-3 pb-1">
                  <CardTitle className="font-heading font-semibold text-xs text-loss uppercase tracking-wider">Top Losers</CardTitle>
                </CardHeader>
                <CardContent className="p-3 pt-1">
                  <PnlBarList
                    data={losers}
                    tone="loss"
                    ariaLabel="Top losers P&L"
                    valueFormatter={(v: number) => `-${formatINR(v)}`}
                  />
                </CardContent>
              </Card>
            )}
          </div>
        );
      })()}
    </div>
  );
}

function CalendarTab({ trades }: { trades: Trade[] }) {
  const daily = useMemo(() => computeDailyPnl(trades), [trades]);

  // Build a calendar view for the last 3 months. "Today" is the IST trading
  // day: the cells are keyed by the trade dates the backend reports, which are
  // Indian market days, so the highlight and the future greying must be read
  // off the same calendar. `new Date().toISOString()` would still be on
  // yesterday for the whole IST early morning (UTC turns over at 05:30 IST),
  // which un-highlighted today and greyed it out as "future".
  const todayKey = istToday();
  const { year: istYear, month: istMonth } = istParts();
  const months: { year: number; month: number; label: string }[] = [];
  for (let i = 2; i >= 0; i--) {
    const d = new Date(istYear, istMonth - i, 1);
    months.push({ year: d.getFullYear(), month: d.getMonth(), label: d.toLocaleString("en-IN", { month: "short", year: "2-digit" }) });
  }

  const pnlByDate = useMemo(() => {
    const m: Record<string, number> = {};
    daily.forEach(({ date, pnl }) => { m[date] = pnl; });
    return m;
  }, [daily]);

  const maxAbs = useMemo(() => {
    return Math.max(...daily.map((d) => Math.abs(d.pnl)), 1);
  }, [daily]);

  const totalPnl = daily.reduce((s, d) => s + d.pnl, 0);
  const tradingDays = daily.filter((d) => d.pnl !== 0).length;
  const greenDays = daily.filter((d) => d.pnl > 0).length;
  const redDays = daily.filter((d) => d.pnl < 0).length;

  const DOW_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

  return (
    <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
      {/* Summary strip */}
      <div className="grid grid-cols-4 gap-2">
        {[
          { label: "Total P&L", value: formatINR(totalPnl), pos: totalPnl >= 0 },
          { label: "Trading Days", value: String(tradingDays), pos: undefined },
          { label: "Green Days", value: String(greenDays), pos: true },
          { label: "Red Days", value: String(redDays), pos: redDays === 0 },
        ].map(({ label, value, pos }) => (
          <Card key={label} className="bg-surface-card border-border-default">
            <CardContent className="p-3">
              <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">{label}</div>
              <div className={`text-base font-bold font-mono tabular-nums ${pos === undefined ? "text-text-primary" : pos ? "text-profit" : "text-loss"}`}>{value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Calendar heatmap — adapted from etftracker heatmap color concept */}
      {months.map(({ year, month, label }) => {
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        // Offset: Monday=0
        let startOffset = firstDay.getDay() - 1;
        if (startOffset < 0) startOffset = 6;

        const cells: (number | null)[] = Array(startOffset).fill(null);
        for (let d = 1; d <= lastDay.getDate(); d++) cells.push(d);
        while (cells.length % 7 !== 0) cells.push(null);

        return (
          <Card key={`${year}-${month}`} className="bg-surface-card border-border-default">
            <CardHeader className="p-3 pb-1">
              <CardTitle className="text-xs font-medium text-text-secondary">{label}</CardTitle>
            </CardHeader>
            <CardContent className="p-3 pt-0">
              {/* Day-of-week header */}
              <div className="grid grid-cols-7 gap-1 mb-1">
                {DOW_LABELS.map((l, i) => (
                  <div key={i} className="text-center text-xxs text-text-muted">{l}</div>
                ))}
              </div>
              {/* Weeks */}
              {Array.from({ length: cells.length / 7 }).map((_, wi) => (
                <div key={wi} className="grid grid-cols-7 gap-1 mb-1">
                  {cells.slice(wi * 7, wi * 7 + 7).map((day, di) => {
                    if (!day) return <div key={di} className="h-7" />;
                    const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
                    const pnl = pnlByDate[dateStr];
                    // Both keys are ISO ``YYYY-MM-DD``, so a string compare is
                    // the calendar compare — no re-parsing into a zone.
                    const isToday = dateStr === todayKey;
                    const isFuture = dateStr > todayKey;
                    return (
                      <div
                        key={di}
                        title={pnl !== undefined ? `${dateStr}: ${formatINR(pnl)}` : dateStr}
                        className={`h-7 rounded flex items-center justify-center text-xxs font-mono cursor-default transition-colors
                          ${isFuture ? "bg-surface-base text-text-disabled" :
                            pnl !== undefined ? `${heatmapColor(pnl, maxAbs)} text-white/80` :
                            "bg-surface-elevated text-text-muted"}
                          ${isToday ? "ring-1 ring-ring" : ""}`}
                      >
                        {day}
                      </div>
                    );
                  })}
                </div>
              ))}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function DrawdownTab({ trades }: { trades: Trade[] }) {
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
            <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">Net Cumulative P&L</div>
            <div className={`text-xl font-bold font-mono tabular-nums ${pnlClass(cumulativeSeries[cumulativeSeries.length - 1]?.cum ?? 0)}`}>
              {formatINR(cumulativeSeries[cumulativeSeries.length - 1]?.cum ?? 0)}
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
            ariaLabel="P&L dashboard equity curve chart"
            className="h-36 min-h-32 w-full"
            data={equityChartData}
            tone={cumulativeSeries[cumulativeSeries.length - 1]?.cum >= 0 ? "profit" : "loss"}
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
            ariaLabel="P&L dashboard drawdown chart"
            className="h-24 min-h-24 w-full"
            data={drawdownChartData}
            tone="loss"
          />
        </CardContent>
      </Card>
    </div>
  );
}

// ---- Main component ----

export default function PnLDashboardTool({ onClose }: Props) {
  const mode = useModeStore((state) => state.mode);
  const positionsResult = useModeData<Position[]>("positions");
  const fundsResult = useModeData<Funds>("funds");
  const tradesResult = useModeData<Trade[]>("tradebook");
  const positions = positionsResult.data ?? [];
  const funds = fundsResult.data;
  const trades = tradesResult.data ?? [];

  const isLoading = positionsResult.isLoading || fundsResult.isLoading || tradesResult.isLoading;
  const isError = positionsResult.error !== null;

  // Shared MTM definition — this summed the raw broker `pnl`, which is
  // wrong for some brokers (CLAUDE.md quirk 4) and disagreed with the
  // Intraday P&L widget for the same book.
  const totalPnl = totalPositionMtm(positions);

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <PieChart size={16} className="text-primary" />
          <h1 className="font-heading font-bold text-lg text-text-primary">P&L Dashboard</h1>
          {mode !== "live" && (
            <Badge variant="outline" className="text-xxs px-1.5 py-0 border-warning/30 text-warning bg-warning/10">
              {mode === "explore" ? "Sample data" : "Practice data"}
            </Badge>
          )}
          {isLoading && <span className="text-xs text-text-muted">Loading...</span>}
          {isError && <AlertCircle size={12} className="text-loss" />}
          {!isLoading && !isError && (
            <Badge
              variant="outline"
              className={`text-xxs px-1.5 py-0 border-0 font-mono font-medium ${totalPnl >= 0 ? "bg-bullish-bg text-profit" : "bg-bearish-bg text-loss"}`}
            >
              {totalPnl >= 0 ? <TrendingUp size={9} className="inline mr-0.5" /> : <TrendingDown size={9} className="inline mr-0.5" />}
              {formatINR(totalPnl)}
            </Badge>
          )}
        </div>
        <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
          <X size={15} />
        </button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="summary" className="flex-1 flex flex-col min-h-0">
        <TabsList className="shrink-0 rounded-none bg-surface-base border-b border-border-default justify-start px-3 h-8 gap-1">
          <TabsTrigger value="summary" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Wallet size={11} className="mr-1" />Summary
          </TabsTrigger>
          <TabsTrigger value="calendar" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <Calendar size={11} className="mr-1" />Calendar
          </TabsTrigger>
          <TabsTrigger value="drawdown" className="text-xs font-medium h-6 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted">
            <BarChart2 size={11} className="mr-1" />Drawdown
          </TabsTrigger>
        </TabsList>

        <TabsContent value="summary" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <SummaryTab positions={positions} funds={funds} />
        </TabsContent>

        <TabsContent value="calendar" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <CalendarTab trades={trades} />
        </TabsContent>

        <TabsContent value="drawdown" className="flex-1 flex flex-col m-0 min-h-0 overflow-hidden">
          <DrawdownTab trades={trades} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
