import { useState } from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, Legend, CartesianGrid } from "recharts";

const TOOLTIP_STYLE = { background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 11 };
const TICK_STYLE = { fill: "#6b7280", fontSize: 9 };

function cmpColor(a, b, higherIsBetter = true) {
  if (a == null || b == null) return ["text-gray-100", "text-gray-100"];
  const aBetter = higherIsBetter ? a > b : a < b;
  return [
    aBetter ? "text-emerald-400 font-bold" : "text-gray-300",
    aBetter ? "text-gray-300" : "text-emerald-400 font-bold",
  ];
}

function fmtVal(v, fmt) {
  const n = Number(v) || 0;
  if (fmt === "%") return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
  if (fmt === "₹") return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  if (fmt === "x") return `${n.toFixed(2)}x`;
  if (fmt === "count") return n.toLocaleString("en-IN");
  return n.toFixed(2);
}

const COMPARE_METRICS = [
  { key: "total_return_pct", label: "Total Return", fmt: "%", higher: true },
  { key: "cagr", label: "CAGR", fmt: "%", higher: true },
  { key: "sharpe_ratio", label: "Sharpe Ratio", fmt: "ratio", higher: true },
  { key: "sortino_ratio", label: "Sortino Ratio", fmt: "ratio", higher: true },
  { key: "calmar_ratio", label: "Calmar Ratio", fmt: "ratio", higher: true },
  { key: "max_drawdown_pct", label: "Max Drawdown", fmt: "%", higher: false, nested: "drawdown" },
  { key: "win_rate", label: "Win Rate", fmt: "%", higher: true, nested: "trade_stats" },
  { key: "profit_factor", label: "Profit Factor", fmt: "x", higher: true, nested: "trade_stats" },
  { key: "total_trades", label: "Total Trades", fmt: "count", higher: false, nested: "trade_stats" },
  { key: "expectancy", label: "Expectancy", fmt: "₹", higher: true, nested: "trade_stats" },
  { key: "var_95", label: "VaR 95%", fmt: "%", higher: false, nested: "risk" },
];

function getMetricValue(result, metric) {
  if (!result || !result.metrics) return null;
  if (metric.nested) return result.metrics[metric.nested]?.[metric.key] ?? null;
  return result.metrics[metric.key] ?? null;
}

export default function ComparePanel({ history = [], onLoadResult }) {
  const [idA, setIdA] = useState("");
  const [idB, setIdB] = useState("");
  const [resultA, setResultA] = useState(null);
  const [resultB, setResultB] = useState(null);

  const handleSelect = async (id, side) => {
    if (side === "A") setIdA(id);
    else setIdB(id);
    if (onLoadResult) {
      try {
        const res = await onLoadResult(id);
        if (side === "A") setResultA(res);
        else setResultB(res);
      } catch { /* */ }
    }
  };

  // Overlay equity curves
  const equityOverlay = [];
  const maxLen = Math.max(
    resultA?.equity_curve?.length || 0,
    resultB?.equity_curve?.length || 0,
  );
  for (let i = 0; i < maxLen; i++) {
    equityOverlay.push({
      idx: i,
      a: resultA?.equity_curve?.[i]?.equity ?? null,
      b: resultB?.equity_curve?.[i]?.equity ?? null,
    });
  }

  return (
    <div className="space-y-4">
      {/* Selectors */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Backtest A</label>
          <select value={idA} onChange={(e) => handleSelect(e.target.value, "A")}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs">
            <option value="">Select...</option>
            {history.map((h) => (
              <option key={h.id} value={h.id}>
                {h.strategy} — {h.symbol} ({h.start_date} to {h.end_date})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-gray-500 mb-1">Backtest B</label>
          <select value={idB} onChange={(e) => handleSelect(e.target.value, "B")}
            className="w-full bg-gray-800 rounded px-2 py-1.5 text-xs">
            <option value="">Select...</option>
            {history.map((h) => (
              <option key={h.id} value={h.id}>
                {h.strategy} — {h.symbol} ({h.start_date} to {h.end_date})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Overlaid equity curves */}
      {equityOverlay.length > 0 && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
          <div className="text-xs text-gray-400 mb-2">Equity Curves Overlay</div>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={equityOverlay}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="idx" tick={TICK_STYLE} />
              <YAxis tick={TICK_STYLE} domain={["auto", "auto"]} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="a" name="Backtest A" stroke="#22c55e" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="b" name="Backtest B" stroke="#3b82f6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Comparison table */}
      {(resultA || resultB) && (
        <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-800">
              <tr className="text-gray-400">
                <th className="px-3 py-2 text-left">Metric</th>
                <th className="px-3 py-2 text-right">Backtest A</th>
                <th className="px-3 py-2 text-right">Backtest B</th>
                <th className="px-3 py-2 text-right">Difference</th>
              </tr>
            </thead>
            <tbody>
              {COMPARE_METRICS.map((m) => {
                const va = getMetricValue(resultA, m);
                const vb = getMetricValue(resultB, m);
                const diff = va != null && vb != null ? va - vb : null;
                const [colorA, colorB] = cmpColor(va, vb, m.higher);
                return (
                  <tr key={m.key} className="border-t border-gray-800 hover:bg-gray-800/30">
                    <td className="px-3 py-1.5 text-gray-400">{m.label}</td>
                    <td className={`px-3 py-1.5 text-right font-mono ${colorA}`}>{va != null ? fmtVal(va, m.fmt) : "—"}</td>
                    <td className={`px-3 py-1.5 text-right font-mono ${colorB}`}>{vb != null ? fmtVal(vb, m.fmt) : "—"}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                      {diff != null ? fmtVal(diff, m.fmt) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!resultA && !resultB && (
        <div className="text-center text-gray-500 text-sm py-8">Select two backtests to compare</div>
      )}
    </div>
  );
}
