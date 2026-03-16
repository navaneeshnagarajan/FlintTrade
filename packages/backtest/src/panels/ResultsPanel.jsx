import {
  ResponsiveContainer, LineChart, Line, AreaChart, Area,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import MetricCard from "../components/MetricCard";
import HeatmapChart from "../components/HeatmapChart";

const TOOLTIP_STYLE = { background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 11 };
const TICK_STYLE = { fill: "#6b7280", fontSize: 9 };

function PnLHistogram({ trades }) {
  if (!trades || trades.length === 0) return null;
  const pnls = trades.map((t) => t.net_pnl || t.pnl || 0);
  const min = Math.min(...pnls);
  const max = Math.max(...pnls);
  const range = max - min || 1;
  const bucketCount = Math.min(30, Math.max(10, Math.ceil(Math.sqrt(pnls.length))));
  const bucketSize = range / bucketCount;
  const buckets = Array.from({ length: bucketCount }, (_, i) => ({
    label: Math.round(min + i * bucketSize),
    count: 0,
    pnl: min + (i + 0.5) * bucketSize,
  }));
  for (const p of pnls) {
    const idx = Math.min(Math.floor((p - min) / bucketSize), bucketCount - 1);
    buckets[idx].count++;
  }
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
      <div className="text-xs text-gray-400 mb-2">Trade P&L Distribution</div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={buckets}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="label" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="count" fill="#3b82f6"
            shape={(props) => {
              const { x, y, width, height, pnl } = props;
              return <rect x={x} y={y} width={width} height={height} fill={pnl >= 0 ? "#22c55e" : "#ef4444"} rx={1} />;
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function TimeAnalysisCharts({ trades }) {
  if (!trades || trades.length === 0) return null;

  // By hour
  const hourBuckets = {};
  for (const t of trades) {
    const ts = t.entry_timestamp || "";
    const h = parseInt(ts.slice(11, 13), 10);
    if (isNaN(h)) continue;
    if (!hourBuckets[h]) hourBuckets[h] = { total: 0, count: 0 };
    hourBuckets[h].total += t.net_pnl || t.pnl || 0;
    hourBuckets[h].count++;
  }
  const hourData = Object.entries(hourBuckets)
    .map(([h, v]) => ({ hour: `${h}:00`, pnl: Math.round(v.total / v.count) }))
    .sort((a, b) => parseInt(a.hour) - parseInt(b.hour));

  // By day of week
  const dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const dayBuckets = {};
  for (const t of trades) {
    const ts = t.entry_timestamp || "";
    try {
      const d = new Date(ts);
      const dow = d.getDay();
      if (!dayBuckets[dow]) dayBuckets[dow] = { total: 0, count: 0 };
      dayBuckets[dow].total += t.net_pnl || t.pnl || 0;
      dayBuckets[dow].count++;
    } catch { /* */ }
  }
  const dayData = Object.entries(dayBuckets)
    .map(([d, v]) => ({ day: dayNames[d], pnl: Math.round(v.total / v.count) }))
    .sort((a, b) => dayNames.indexOf(a.day) - dayNames.indexOf(b.day));

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="text-xs text-gray-400 mb-2">Avg P&L by Hour</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={hourData}>
            <XAxis dataKey="hour" tick={TICK_STYLE} />
            <YAxis tick={TICK_STYLE} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="pnl"
              shape={(props) => {
                const { x, y, width, height, pnl } = props;
                return <rect x={x} y={y} width={width} height={height} fill={pnl >= 0 ? "#22c55e" : "#ef4444"} rx={2} />;
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="text-xs text-gray-400 mb-2">Avg P&L by Day of Week</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={dayData}>
            <XAxis dataKey="day" tick={TICK_STYLE} />
            <YAxis tick={TICK_STYLE} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Bar dataKey="pnl"
              shape={(props) => {
                const { x, y, width, height, pnl } = props;
                return <rect x={x} y={y} width={width} height={height} fill={pnl >= 0 ? "#22c55e" : "#ef4444"} rx={2} />;
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function ResultsPanel({ result }) {
  if (!result) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        Configure and run a backtest to see results
      </div>
    );
  }

  const {
    equity_curve = [],
    trades = [],
    metrics = {},
    monthly_returns = [],
  } = result;

  const ts = metrics.trade_stats || {};
  const dd = metrics.drawdown || {};
  const risk = metrics.risk || {};

  // Prepare drawdown chart data
  const drawdownData = equity_curve.map((pt) => ({
    ts: (pt.timestamp || "").slice(5, 10),
    dd: -(pt.drawdown || 0),
  }));

  // Equity chart data
  const equityData = equity_curve.map((pt) => ({
    ts: (pt.timestamp || "").slice(5, 10),
    equity: pt.equity,
  }));

  return (
    <div className="space-y-3 overflow-y-auto">
      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-2">
        <MetricCard label="Total Return" value={metrics.total_return_pct} format="%" />
        <MetricCard label="CAGR" value={metrics.cagr} format="%" />
        <MetricCard label="Sharpe Ratio" value={metrics.sharpe_ratio} />
        <MetricCard label="Max Drawdown" value={dd.max_drawdown_pct} format="%" good="negative" />
      </div>
      <div className="grid grid-cols-4 gap-2">
        <MetricCard label="Win Rate" value={ts.win_rate} format="%" />
        <MetricCard label="Profit Factor" value={ts.profit_factor} format="x" />
        <MetricCard label="Total Trades" value={ts.total_trades} format="count" />
        <MetricCard label="Expectancy" value={ts.expectancy} format="₹" />
      </div>
      <div className="grid grid-cols-4 gap-2">
        <MetricCard label="Sortino" value={metrics.sortino_ratio} />
        <MetricCard label="Calmar" value={metrics.calmar_ratio} />
        <MetricCard label="VaR 95%" value={risk.var_95} format="%" good="negative" />
        <MetricCard label="Avg Win/Loss" value={ts.avg_win && ts.avg_loss ? ts.avg_win / ts.avg_loss : 0} format="x" />
      </div>

      {/* Equity curve */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="text-xs text-gray-400 mb-2">Equity Curve</div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={equityData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="ts" tick={TICK_STYLE} />
            <YAxis tick={TICK_STYLE} domain={["auto", "auto"]} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Line type="monotone" dataKey="equity" stroke="#22c55e" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Drawdown */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="text-xs text-gray-400 mb-2">Drawdown</div>
        <ResponsiveContainer width="100%" height={150}>
          <AreaChart data={drawdownData}>
            <XAxis dataKey="ts" tick={TICK_STYLE} />
            <YAxis tick={TICK_STYLE} />
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Area type="monotone" dataKey="dd" stroke="#ef4444" fill="rgba(239,68,68,0.15)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Monthly returns heatmap */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
        <div className="text-xs text-gray-400 mb-2">Monthly Returns</div>
        <HeatmapChart data={monthly_returns} />
      </div>

      {/* P&L histogram */}
      <PnLHistogram trades={trades} />

      {/* Time analysis */}
      <TimeAnalysisCharts trades={trades} />
    </div>
  );
}
