/**
 * Reusable metric display card.
 * Props:
 *   label — metric name
 *   value — raw number
 *   format — "%" | "₹" | "ratio" | "count" | "x"
 *   good — "positive" (green if >0) or "negative" (green if <0)
 */
export default function MetricCard({ label, value, format = "ratio", good = "positive" }) {
  const num = Number(value) || 0;
  const isGood = good === "positive" ? num > 0 : num < 0;
  const isBad = good === "positive" ? num < 0 : num > 0;
  const color = isGood ? "text-emerald-400" : isBad ? "text-red-400" : "text-gray-100";

  let display;
  if (format === "%") display = `${num >= 0 ? "+" : ""}${num.toFixed(2)}%`;
  else if (format === "₹") display = `₹${num.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  else if (format === "count") display = num.toLocaleString("en-IN");
  else if (format === "x") display = `${num.toFixed(2)}x`;
  else display = num.toFixed(2);

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-3">
      <div className="text-[10px] text-gray-500 mb-1 truncate">{label}</div>
      <div className={`text-lg font-bold font-mono ${color}`}>{display}</div>
    </div>
  );
}
