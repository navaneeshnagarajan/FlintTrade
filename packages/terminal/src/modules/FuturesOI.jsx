import { useState } from "react";
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight } from "lucide-react";

const QUADRANT_CONFIG = {
  LONG_BUILDUP: { label: "Long Buildup", color: "text-emerald-400", bg: "border-emerald-500/30", icon: TrendingUp, desc: "OI ↑ Price ↑" },
  SHORT_BUILDUP: { label: "Short Buildup", color: "text-red-400", bg: "border-red-500/30", icon: TrendingDown, desc: "OI ↑ Price ↓" },
  SHORT_COVERING: { label: "Short Covering", color: "text-blue-400", bg: "border-blue-500/30", icon: ArrowUpRight, desc: "OI ↓ Price ↑" },
  LONG_UNWINDING: { label: "Long Unwinding", color: "text-orange-400", bg: "border-orange-500/30", icon: ArrowDownRight, desc: "OI ↓ Price ↓" },
};

function QuadrantPanel({ quadrant, items }) {
  const cfg = QUADRANT_CONFIG[quadrant];
  const Icon = cfg.icon;
  return (
    <div className={`bg-gray-900 rounded-xl border ${cfg.bg} p-4`}>
      <div className={`flex items-center gap-2 mb-3 ${cfg.color}`}>
        <Icon size={16} />
        <span className="font-semibold text-sm">{cfg.label}</span>
        <span className="text-xs text-gray-600 ml-auto">{cfg.desc}</span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-600">
            <th className="text-left pb-1">Symbol</th>
            <th className="text-right pb-1">OI Chg%</th>
            <th className="text-right pb-1">Price Chg%</th>
            <th className="text-right pb-1">LTP</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.symbol} className="border-t border-gray-800/50 hover:bg-gray-800/30">
              <td className="py-1.5 font-medium font-mono">{item.symbol}</td>
              <td className={`py-1.5 text-right font-mono ${item.oiChangePct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {item.oiChangePct >= 0 ? "+" : ""}{item.oiChangePct.toFixed(1)}%
              </td>
              <td className={`py-1.5 text-right font-mono ${item.priceChangePct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {item.priceChangePct >= 0 ? "+" : ""}{item.priceChangePct.toFixed(1)}%
              </td>
              <td className="py-1.5 text-right font-mono">{item.ltp.toLocaleString("en-IN")}</td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={4} className="py-6 text-center text-gray-600">No data — requires market hours</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function FuturesOI() {
  // Data will come from a backend screener API (not yet built).
  // During market hours, this would fetch OI change + price change data.
  const [data] = useState({ LONG_BUILDUP: [], SHORT_BUILDUP: [], SHORT_COVERING: [], LONG_UNWINDING: [] });

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        {Object.keys(QUADRANT_CONFIG).map((q) => (
          <QuadrantPanel key={q} quadrant={q} items={data[q] || []} />
        ))}
      </div>
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 text-center text-gray-600 text-sm">
        Futures OI analysis requires the screener backend (coming soon).
        During market hours, this will show live OI buildup across F&O stocks.
      </div>
    </div>
  );
}
