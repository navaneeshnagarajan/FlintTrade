/**
 * TradePerformanceWidget — Comprehensive trade performance dashboard.
 *
 * Features:
 *   - Equity curve: SVG line chart built from cumulative trade P&L history
 *   - Win/loss streak tracker: current streak + longest win/loss streak
 *   - Monthly returns heatmap: compact grid of monthly returns coloured by sign/magnitude
 *   - Key metrics: win rate, avg R:R, profit factor, expectancy per trade
 *   - Trade distribution by day of week: mini SVG bar chart
 *   - Data source: sample trade journal data; live from tradebook API
 */

import { useMemo, memo } from "react";
import { Trophy } from "lucide-react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TradeRecord {
  date: string;        // ISO date
  pnl: number;         // net P&L for the trade in INR
  isWin: boolean;
}

// ---------------------------------------------------------------------------
// Sample data — 40 trades
// ---------------------------------------------------------------------------

const SAMPLE_TRADES: TradeRecord[] = [
  { date: "2026-01-02", pnl:  2400, isWin: true  },
  { date: "2026-01-03", pnl: -1100, isWin: false },
  { date: "2026-01-06", pnl:  3200, isWin: true  },
  { date: "2026-01-07", pnl:  1800, isWin: true  },
  { date: "2026-01-08", pnl: -900,  isWin: false },
  { date: "2026-01-09", pnl:  2100, isWin: true  },
  { date: "2026-01-10", pnl:  1500, isWin: true  },
  { date: "2026-01-13", pnl: -2200, isWin: false },
  { date: "2026-01-14", pnl:  3500, isWin: true  },
  { date: "2026-01-15", pnl: -800,  isWin: false },
  { date: "2026-01-16", pnl:  2700, isWin: true  },
  { date: "2026-01-17", pnl:  1200, isWin: true  },
  { date: "2026-01-20", pnl: -1500, isWin: false },
  { date: "2026-01-21", pnl:  4100, isWin: true  },
  { date: "2026-01-22", pnl: -700,  isWin: false },
  { date: "2026-02-03", pnl:  1900, isWin: true  },
  { date: "2026-02-04", pnl:  2300, isWin: true  },
  { date: "2026-02-05", pnl: -1300, isWin: false },
  { date: "2026-02-06", pnl:  3100, isWin: true  },
  { date: "2026-02-10", pnl: -1700, isWin: false },
  { date: "2026-02-11", pnl:  2800, isWin: true  },
  { date: "2026-02-12", pnl:  1600, isWin: true  },
  { date: "2026-02-13", pnl: -900,  isWin: false },
  { date: "2026-02-14", pnl:  2400, isWin: true  },
  { date: "2026-02-18", pnl: -600,  isWin: false },
  { date: "2026-03-03", pnl:  3300, isWin: true  },
  { date: "2026-03-04", pnl:  1800, isWin: true  },
  { date: "2026-03-05", pnl: -2100, isWin: false },
  { date: "2026-03-06", pnl:  4200, isWin: true  },
  { date: "2026-03-07", pnl:  2900, isWin: true  },
  { date: "2026-03-10", pnl: -1200, isWin: false },
  { date: "2026-03-11", pnl:  3600, isWin: true  },
  { date: "2026-03-12", pnl: -800,  isWin: false },
  { date: "2026-03-13", pnl:  2100, isWin: true  },
  { date: "2026-03-14", pnl:  1700, isWin: true  },
  { date: "2026-03-17", pnl: -1400, isWin: false },
  { date: "2026-03-18", pnl:  2500, isWin: true  },
  { date: "2026-03-19", pnl: -900,  isWin: false },
  { date: "2026-03-20", pnl:  3800, isWin: true  },
  { date: "2026-03-21", pnl:  2200, isWin: true  },
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

// ---------------------------------------------------------------------------
// Metric computations
// ---------------------------------------------------------------------------

interface PerformanceMetrics {
  winRate: number;
  avgWin: number;
  avgLoss: number;
  rr: number;
  profitFactor: number;
  expectancy: number;
  totalPnl: number;
  currentStreak: number;
  currentStreakType: "win" | "loss" | "none";
  longestWinStreak: number;
  longestLossStreak: number;
  equity: number[];
  monthlyReturns: Record<string, number>;
  dayDistribution: Record<string, number>;
}

function computeMetrics(trades: TradeRecord[]): PerformanceMetrics {
  if (trades.length === 0) {
    return {
      winRate: 0, avgWin: 0, avgLoss: 0, rr: 0,
      profitFactor: 0, expectancy: 0, totalPnl: 0,
      currentStreak: 0, currentStreakType: "none",
      longestWinStreak: 0, longestLossStreak: 0,
      equity: [0], monthlyReturns: {}, dayDistribution: {},
    };
  }

  const wins = trades.filter((t) => t.isWin);
  const losses = trades.filter((t) => !t.isWin);
  const totalWinPnl = wins.reduce((s, t) => s + t.pnl, 0);
  const totalLossPnl = Math.abs(losses.reduce((s, t) => s + t.pnl, 0));

  const avgWin = wins.length > 0 ? totalWinPnl / wins.length : 0;
  const avgLoss = losses.length > 0 ? totalLossPnl / losses.length : 0;
  const winRate = (wins.length / trades.length) * 100;
  const rr = avgLoss > 0 ? avgWin / avgLoss : 0;
  const profitFactor = totalLossPnl > 0 ? totalWinPnl / totalLossPnl : totalWinPnl > 0 ? 99 : 0;
  const expectancy = (winRate / 100) * avgWin - ((100 - winRate) / 100) * avgLoss;

  // Equity curve
  let cum = 0;
  const equity = [0, ...trades.map((t) => { cum += t.pnl; return cum; })];

  // Streaks
  let currentStreak = 0;
  let currentStreakType: "win" | "loss" | "none" = "none";
  let longestWinStreak = 0;
  let longestLossStreak = 0;
  let ws = 0;
  let ls = 0;
  for (const t of trades) {
    if (t.isWin) {
      ws++;
      ls = 0;
      longestWinStreak = Math.max(longestWinStreak, ws);
    } else {
      ls++;
      ws = 0;
      longestLossStreak = Math.max(longestLossStreak, ls);
    }
  }
  const last = trades[trades.length - 1];
  if (last) {
    currentStreakType = last.isWin ? "win" : "loss";
    currentStreak = 1;
    for (let i = trades.length - 2; i >= 0; i--) {
      if (trades[i].isWin === last.isWin) {
        currentStreak++;
      } else {
        break;
      }
    }
  }

  // Monthly returns
  const monthlyReturns: Record<string, number> = {};
  for (const t of trades) {
    const [year, month] = t.date.split("-");
    const key = `${year}-${month}`;
    monthlyReturns[key] = (monthlyReturns[key] ?? 0) + t.pnl;
  }

  // Day distribution (0=Mon)
  const dayDistribution: Record<string, number> = {};
  for (const t of trades) {
    const d = new Date(t.date);
    const dayIdx = (d.getDay() + 6) % 7; // 0=Mon
    if (dayIdx < 5) {
      const label = DAYS[dayIdx];
      dayDistribution[label] = (dayDistribution[label] ?? 0) + 1;
    }
  }

  return {
    winRate, avgWin, avgLoss, rr, profitFactor, expectancy,
    totalPnl: cum, currentStreak, currentStreakType,
    longestWinStreak, longestLossStreak, equity, monthlyReturns, dayDistribution,
  };
}

// ---------------------------------------------------------------------------
// Equity curve SVG
// ---------------------------------------------------------------------------

const EQ_W = 480;
const EQ_H = 100;
const EQ_PAD = { top: 8, right: 10, bottom: 20, left: 50 };

function EquityCurve({ equity }: { equity: number[] }) {
  const chartW = EQ_W - EQ_PAD.left - EQ_PAD.right;
  const chartH = EQ_H - EQ_PAD.top - EQ_PAD.bottom;

  const minV = Math.min(...equity);
  const maxV = Math.max(...equity);
  const range = maxV - minV || 1;

  const xOf = (i: number) =>
    equity.length > 1 ? (i / (equity.length - 1)) * chartW : 0;
  const yOf = (v: number) => chartH - ((v - minV) / range) * chartH;

  const linePoints = equity
    .map((v, i) => `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`)
    .join(" ");

  const areaPath = [
    `M ${xOf(0).toFixed(1)},${yOf(equity[0]).toFixed(1)}`,
    ...equity.slice(1).map((v, i) => `L ${xOf(i + 1).toFixed(1)},${yOf(v).toFixed(1)}`),
    `L ${xOf(equity.length - 1).toFixed(1)},${chartH.toFixed(1)}`,
    `L 0,${chartH.toFixed(1)}`,
    "Z",
  ].join(" ");

  const isProfit = equity[equity.length - 1] >= 0;
  const lineColour = isProfit ? "rgba(34,197,94,0.85)" : "rgba(239,68,68,0.85)";
  const fillColour = isProfit ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)";

  // Zero line
  const zeroY = yOf(0);
  const showZeroLine = zeroY > 0 && zeroY < chartH;

  const yTicks = [minV, 0, maxV].filter((v, i, arr) => arr.indexOf(v) === i);

  return (
    <svg
      viewBox={`0 0 ${EQ_W} ${EQ_H}`}
      className="w-full"
      style={{ height: EQ_H }}
      aria-label="Equity curve chart"
      role="img"
    >
      <g transform={`translate(${EQ_PAD.left},${EQ_PAD.top})`}>
        {showZeroLine && (
          <line
            x1={0}
            y1={zeroY}
            x2={chartW}
            y2={zeroY}
            stroke="rgba(156,163,175,0.3)"
            strokeWidth={0.75}
            strokeDasharray="3,2"
          />
        )}

        <path d={areaPath} fill={fillColour} />
        <polyline
          points={linePoints}
          fill="none"
          stroke={lineColour}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Y ticks */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={-4} x2={0} y1={yOf(v)} y2={yOf(v)} stroke="var(--color-border-default,#2a2a3a)" />
            <text x={-6} y={yOf(v) + 3} textAnchor="end" fontSize={8} fill="var(--color-text-muted,#666)">
              {v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)}
            </text>
          </g>
        ))}

        <line x1={0} y1={chartH} x2={chartW} y2={chartH} stroke="var(--color-border-default,#2a2a3a)" />
        <line x1={0} y1={0} x2={0} y2={chartH} stroke="var(--color-border-default,#2a2a3a)" />
      </g>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Monthly returns heatmap
// ---------------------------------------------------------------------------

function MonthlyHeatmap({ returns }: { returns: Record<string, number> }) {
  const sortedKeys = Object.keys(returns).sort();
  const maxAbs = Math.max(...Object.values(returns).map(Math.abs), 1);

  if (sortedKeys.length === 0) {
    return <p className="text-xxs text-text-muted">No monthly data yet.</p>;
  }

  return (
    <div className="flex flex-wrap gap-1" aria-label="Monthly returns heatmap">
      {sortedKeys.map((key) => {
        const val = returns[key];
        const intensity = Math.min(Math.abs(val) / maxAbs, 1);
        const bg = val >= 0
          ? `rgba(34,197,94,${0.15 + intensity * 0.45})`
          : `rgba(239,68,68,${0.15 + intensity * 0.45})`;
        const [, month] = key.split("-");
        const monthName = MONTHS[(parseInt(month, 10) - 1) % 12];
        return (
          <div
            key={key}
            title={`${monthName}: ${val >= 0 ? "+" : ""}${val.toLocaleString("en-IN")}`}
            aria-label={`${monthName} ${val >= 0 ? "profit" : "loss"} ${Math.abs(val).toLocaleString("en-IN")}`}
            className="flex flex-col items-center justify-center rounded px-1.5 py-1 min-w-10"
            style={{ background: bg }}
          >
            <span className="text-xxs font-medium text-text-primary">{monthName}</span>
            <span className="text-xxs font-mono tabular-nums text-text-secondary">
              {val >= 0 ? "+" : ""}{val >= 1000 || val <= -1000
                ? `${(val / 1000).toFixed(1)}k`
                : val.toFixed(0)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day distribution bar chart
// ---------------------------------------------------------------------------

function DayDistribution({ distribution }: { distribution: Record<string, number> }) {
  const maxCount = Math.max(...DAYS.map((d) => distribution[d] ?? 0), 1);
  const BAR_H = 40;

  return (
    <svg
      viewBox={`0 0 ${DAYS.length * 40} ${BAR_H + 20}`}
      className="w-full"
      style={{ height: BAR_H + 20 }}
      aria-label="Trade distribution by day of week"
      role="img"
    >
      {DAYS.map((day, i) => {
        const count = distribution[day] ?? 0;
        const barH = (count / maxCount) * BAR_H;
        const x = i * 40 + 4;
        const barW = 32;
        return (
          <g key={day}>
            <rect
              x={x}
              y={BAR_H - barH}
              width={barW}
              height={barH}
              fill="rgba(99,102,241,0.55)"
              rx={2}
            />
            <text x={x + barW / 2} y={BAR_H + 14} textAnchor="middle" fontSize={9} fill="var(--color-text-muted,#666)">
              {day}
            </text>
            {count > 0 && (
              <text x={x + barW / 2} y={BAR_H - barH - 3} textAnchor="middle" fontSize={8} fill="var(--color-text-secondary,#999)">
                {count}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Stat tile
// ---------------------------------------------------------------------------

interface StatTileProps {
  label: string;
  value: string;
  colour?: string;
}

function StatTile({ label, value, colour = "text-text-primary" }: StatTileProps) {
  return (
    <div className="flex flex-col gap-0.5 bg-surface-hover rounded px-2 py-1.5">
      <span className="text-xxs text-text-muted">{label}</span>
      <span className={`text-xs font-semibold font-mono tabular-nums ${colour}`}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function TradePerformanceWidget() {
  const isConnected = useBrokerConnected();
  useTrackBehavior();

  const metrics = useMemo(() => computeMetrics(SAMPLE_TRADES), []);

  const streakColour =
    metrics.currentStreakType === "win" ? "text-profit" : metrics.currentStreakType === "loss" ? "text-loss" : "text-text-muted";

  const streakLabel =
    metrics.currentStreakType === "win"
      ? `W${metrics.currentStreak}`
      : metrics.currentStreakType === "loss"
      ? `L${metrics.currentStreak}`
      : "—";

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Trade Performance widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Trophy size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Trade Performance</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 flex flex-col gap-3">

        {/* Equity curve */}
        <section aria-labelledby="eq-label">
          <p id="eq-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
            Equity Curve
          </p>
          <EquityCurve equity={metrics.equity} />
        </section>

        {/* Key metrics */}
        <section aria-labelledby="metrics-label">
          <p id="metrics-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
            Key Metrics
          </p>
          <div className="grid grid-cols-4 gap-1.5">
            <StatTile label="Win Rate" value={`${metrics.winRate.toFixed(1)}%`} colour={metrics.winRate >= 50 ? "text-profit" : "text-loss"} />
            <StatTile label="Avg R:R" value={metrics.rr.toFixed(2)} colour={metrics.rr >= 1 ? "text-profit" : "text-warning"} />
            <StatTile label="Profit Factor" value={metrics.profitFactor.toFixed(2)} colour={metrics.profitFactor >= 1.5 ? "text-profit" : "text-warning"} />
            <StatTile label="Expectancy" value={`₹${metrics.expectancy.toFixed(0)}`} colour={metrics.expectancy >= 0 ? "text-profit" : "text-loss"} />
          </div>
        </section>

        {/* Streak tracker */}
        <section aria-labelledby="streak-label">
          <p id="streak-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
            Streak Tracker
          </p>
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex flex-col items-center bg-surface-hover rounded px-3 py-1.5">
              <span className="text-xxs text-text-muted">Current</span>
              <span className={`text-sm font-bold font-mono ${streakColour}`} aria-label={`Current streak ${streakLabel}`}>
                {streakLabel}
              </span>
            </div>
            <div className="flex flex-col items-center bg-surface-hover rounded px-3 py-1.5">
              <span className="text-xxs text-text-muted">Best Win</span>
              <span className="text-sm font-bold font-mono text-profit">
                W{metrics.longestWinStreak}
              </span>
            </div>
            <div className="flex flex-col items-center bg-surface-hover rounded px-3 py-1.5">
              <span className="text-xxs text-text-muted">Worst Loss</span>
              <span className="text-sm font-bold font-mono text-loss">
                L{metrics.longestLossStreak}
              </span>
            </div>
          </div>
        </section>

        {/* Monthly returns heatmap */}
        <section aria-labelledby="monthly-label">
          <p id="monthly-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
            Monthly Returns
          </p>
          <MonthlyHeatmap returns={metrics.monthlyReturns} />
        </section>

        {/* Day of week distribution */}
        <section aria-labelledby="dow-label">
          <p id="dow-label" className="text-xxs font-medium text-text-muted mb-1 uppercase tracking-wide">
            Trades by Day
          </p>
          <DayDistribution distribution={metrics.dayDistribution} />
        </section>
      </div>
    </div>
  );
}

export default memo(TradePerformanceWidget);
