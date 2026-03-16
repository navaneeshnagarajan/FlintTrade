import { useState, useMemo } from "react";
import {
  ResponsiveContainer, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import StatCard from "../components/StatCard";

const RANGES = ["Today", "This Week", "This Month", "Custom"];

// Sample data generators for demo
function genDailyPnL(days) {
  const data = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const pnl = (Math.random() - 0.42) * 15000;
    data.push({ date: d.toISOString().slice(5, 10), pnl: Math.round(pnl) });
  }
  return data;
}

function genEquityCurve(days) {
  let equity = 1000000;
  const data = [];
  const now = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    equity += (Math.random() - 0.42) * 8000;
    data.push({ date: d.toISOString().slice(5, 10), equity: Math.round(equity) });
  }
  return data;
}

function genDrawdown(equityData) {
  let peak = 0;
  return equityData.map((e) => {
    if (e.equity > peak) peak = e.equity;
    const dd = peak > 0 ? ((e.equity - peak) / peak) * 100 : 0;
    return { date: e.date, dd: Number(dd.toFixed(2)) };
  });
}

function genMonthlyReturns() {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return months.map((m) => ({ month: m, ret: Number(((Math.random() - 0.4) * 10).toFixed(1)) }));
}

function genHourlyPnL() {
  const hours = [];
  for (let h = 9; h <= 15; h++) {
    hours.push({ hour: `${h}:00`, pnl: Math.round((Math.random() - 0.4) * 5000) });
  }
  return hours;
}

const TOOLTIP_STYLE = { background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 11 };
const TICK_STYLE = { fill: "#6b7280", fontSize: 9 };

export default function PnLAnalytics() {
  const [range, setRange] = useState("This Month");

  const days = range === "Today" ? 1 : range === "This Week" ? 7 : 30;

  const dailyPnL = useMemo(() => genDailyPnL(days), [days]);
  const equityCurve = useMemo(() => genEquityCurve(days), [days]);
  const drawdown = useMemo(() => genDrawdown(equityCurve), [equityCurve]);
  const monthlyReturns = useMemo(() => genMonthlyReturns(), []);
  const hourlyPnL = useMemo(() => genHourlyPnL(), []);

  const totalReturn = dailyPnL.reduce((s, d) => s + d.pnl, 0);
  const maxDD = Math.min(...drawdown.map((d) => d.dd));
  const winDays = dailyPnL.filter((d) => d.pnl > 0).length;
  const winRate = dailyPnL.length > 0 ? ((winDays / dailyPnL.length) * 100).toFixed(0) : "0";
  const avgWin = dailyPnL.filter((d) => d.pnl > 0).reduce((s, d) => s + d.pnl, 0) / (winDays || 1);
  const lossDays = dailyPnL.filter((d) => d.pnl < 0).length;
  const avgLoss = Math.abs(dailyPnL.filter((d) => d.pnl < 0).reduce((s, d) => s + d.pnl, 0) / (lossDays || 1));
  const profitFactor = avgLoss > 0 ? (avgWin / avgLoss).toFixed(2) : "—";

  // Streaks
  let currentStreak = 0;
  let streakType = "none";
  let longestWin = 0;
  let longestLoss = 0;
  let tempWin = 0;
  let tempLoss = 0;
  for (const d of dailyPnL) {
    if (d.pnl > 0) { tempWin++; tempLoss = 0; if (tempWin > longestWin) longestWin = tempWin; }
    else if (d.pnl < 0) { tempLoss++; tempWin = 0; if (tempLoss > longestLoss) longestLoss = tempLoss; }
    else { tempWin = 0; tempLoss = 0; }
  }
  if (tempWin > 0) { currentStreak = tempWin; streakType = "win"; }
  else if (tempLoss > 0) { currentStreak = tempLoss; streakType = "loss"; }

  return (
    <div className="space-y-4">
      {/* Range selector */}
      <div className="flex gap-2">
        {RANGES.map((r) => (
          <button key={r} onClick={() => setRange(r)}
            className={`px-3 py-1 rounded text-xs font-semibold ${range === r ? "bg-emerald-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}>
            {r}
          </button>
        ))}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-7 gap-2">
        <StatCard title="Total Return" value={`₹${totalReturn >= 0 ? "+" : ""}${totalReturn.toLocaleString("en-IN")}`}
          color={totalReturn >= 0 ? "text-emerald-400" : "text-red-400"} />
        <StatCard title="CAGR" value="—" subtitle="Needs 1yr data" />
        <StatCard title="Sharpe" value="—" subtitle="Needs 1yr data" />
        <StatCard title="Max Drawdown" value={`${maxDD.toFixed(1)}%`} color="text-red-400" />
        <StatCard title="Win Rate" value={`${winRate}%`} />
        <StatCard title="Profit Factor" value={profitFactor} />
        <StatCard title="Avg Win/Loss" value={avgLoss > 0 ? (avgWin / avgLoss).toFixed(2) : "—"} />
      </div>

      {/* P&L bar chart */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="text-xs text-gray-400 mb-2">Daily P&L</div>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={dailyPnL}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="date" tick={TICK_STYLE} />
            <YAxis tick={TICK_STYLE} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="pnl" fill="#22c55e"
              shape={(props) => {
                const { x, y, width, height, pnl } = props;
                const fill = pnl >= 0 ? "#22c55e" : "#ef4444";
                return <rect x={x} y={y} width={width} height={height} fill={fill} rx={2} />;
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Equity + Drawdown side by side */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
          <div className="text-xs text-gray-400 mb-2">Cumulative Equity Curve</div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={equityCurve}>
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" tick={TICK_STYLE} />
              <YAxis tick={TICK_STYLE} domain={["auto", "auto"]} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Area type="monotone" dataKey="equity" stroke="#22c55e" fill="url(#eqGrad)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
          <div className="text-xs text-gray-400 mb-2">Drawdown</div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={drawdown}>
              <XAxis dataKey="date" tick={TICK_STYLE} />
              <YAxis tick={TICK_STYLE} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Area type="monotone" dataKey="dd" stroke="#ef4444" fill="rgba(239,68,68,0.15)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Monthly returns heatmap */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="text-xs text-gray-400 mb-2">Monthly Returns</div>
        <div className="grid grid-cols-12 gap-1">
          {monthlyReturns.map((m) => {
            const intensity = Math.min(Math.abs(m.ret) / 5, 1);
            const bg = m.ret >= 0
              ? `rgba(34, 197, 94, ${0.15 + intensity * 0.6})`
              : `rgba(239, 68, 68, ${0.15 + intensity * 0.6})`;
            return (
              <div key={m.month} className="rounded p-2 text-center" style={{ background: bg }}>
                <div className="text-[9px] text-gray-400">{m.month}</div>
                <div className={`text-xs font-mono font-bold ${m.ret >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {m.ret >= 0 ? "+" : ""}{m.ret}%
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Time-of-day analysis */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="text-xs text-gray-400 mb-2">Average P&L by Hour</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={hourlyPnL}>
            <XAxis dataKey="hour" tick={TICK_STYLE} />
            <YAxis tick={TICK_STYLE} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="pnl" fill="#22c55e"
              shape={(props) => {
                const { x, y, width, height, pnl } = props;
                return <rect x={x} y={y} width={width} height={height} fill={pnl >= 0 ? "#22c55e" : "#ef4444"} rx={2} />;
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Streaks */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
          <div className="text-[10px] text-gray-500 mb-1">Current Streak</div>
          <div className={`text-lg font-bold font-mono ${streakType === "win" ? "text-emerald-400" : streakType === "loss" ? "text-red-400" : "text-gray-400"}`}>
            {currentStreak} {streakType === "win" ? "W" : streakType === "loss" ? "L" : "—"}
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
          <div className="text-[10px] text-gray-500 mb-1">Longest Win Streak</div>
          <div className="text-lg font-bold font-mono text-emerald-400">{longestWin}</div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
          <div className="text-[10px] text-gray-500 mb-1">Longest Loss Streak</div>
          <div className="text-lg font-bold font-mono text-red-400">{longestLoss}</div>
        </div>
      </div>
    </div>
  );
}
