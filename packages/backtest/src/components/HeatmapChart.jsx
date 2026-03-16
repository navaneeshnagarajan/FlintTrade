import { useState } from "react";

const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function cellColor(ret) {
  if (ret == null) return "bg-gray-800";
  const abs = Math.min(Math.abs(ret), 10);
  const intensity = 0.15 + (abs / 10) * 0.65;
  if (ret >= 0) return undefined; // use inline style
  return undefined;
}

/**
 * Monthly returns heatmap.
 * Props:
 *   data — array of { year, month (1-12), return_pct }
 */
export default function HeatmapChart({ data = [] }) {
  const [tooltip, setTooltip] = useState(null);

  if (data.length === 0) {
    return <div className="text-xs text-gray-500 p-4 text-center">No monthly return data</div>;
  }

  // Group by year
  const years = [...new Set(data.map((d) => d.year))].sort();
  const lookup = {};
  for (const d of data) {
    lookup[`${d.year}-${d.month}`] = d.return_pct;
  }

  return (
    <div className="overflow-auto">
      <table className="text-[10px] w-full">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left text-gray-500">Year</th>
            {MONTH_LABELS.map((m) => (
              <th key={m} className="px-2 py-1 text-center text-gray-500">{m}</th>
            ))}
            <th className="px-2 py-1 text-center text-gray-500">Total</th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => {
            let yearTotal = 0;
            let count = 0;
            return (
              <tr key={year}>
                <td className="px-2 py-1 font-mono text-gray-400">{year}</td>
                {Array.from({ length: 12 }, (_, i) => {
                  const key = `${year}-${i + 1}`;
                  const ret = lookup[key];
                  if (ret != null) { yearTotal += ret; count++; }
                  const abs = Math.min(Math.abs(ret || 0), 10);
                  const intensity = ret != null ? 0.15 + (abs / 10) * 0.65 : 0;
                  const bg = ret == null
                    ? "rgba(31, 41, 55, 0.5)"
                    : ret >= 0
                      ? `rgba(34, 197, 94, ${intensity})`
                      : `rgba(239, 68, 68, ${intensity})`;
                  return (
                    <td key={i} className="px-1 py-1 text-center relative"
                      onMouseEnter={() => setTooltip({ year, month: MONTH_LABELS[i], ret })}
                      onMouseLeave={() => setTooltip(null)}>
                      <div className="rounded px-1 py-0.5 font-mono" style={{ background: bg }}>
                        <span className={ret == null ? "text-gray-600" : ret >= 0 ? "text-emerald-400" : "text-red-400"}>
                          {ret != null ? `${ret >= 0 ? "+" : ""}${ret.toFixed(1)}` : "—"}
                        </span>
                      </div>
                    </td>
                  );
                })}
                <td className="px-2 py-1 text-center font-mono font-bold">
                  <span className={yearTotal >= 0 ? "text-emerald-400" : "text-red-400"}>
                    {yearTotal >= 0 ? "+" : ""}{yearTotal.toFixed(1)}%
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {tooltip && tooltip.ret != null && (
        <div className="text-[10px] text-gray-400 mt-1 text-center">
          {tooltip.month} {tooltip.year}: <span className={tooltip.ret >= 0 ? "text-emerald-400" : "text-red-400"}>
            {tooltip.ret >= 0 ? "+" : ""}{tooltip.ret.toFixed(2)}%
          </span>
        </div>
      )}
    </div>
  );
}
