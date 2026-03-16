import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { TrendingUp, TrendingDown, ArrowUpRight, ArrowDownRight } from "lucide-react";

const QUADRANT_CONFIG = {
  LONG_BUILDUP: { label: "Long Buildup", color: "text-emerald-400", bg: "border-emerald-500/30", icon: TrendingUp, desc: "OI ↑ Price ↑" },
  SHORT_BUILDUP: { label: "Short Buildup", color: "text-red-400", bg: "border-red-500/30", icon: TrendingDown, desc: "OI ↑ Price ↓" },
  SHORT_COVERING: { label: "Short Covering", color: "text-blue-400", bg: "border-blue-500/30", icon: ArrowUpRight, desc: "OI ↓ Price ↑" },
  LONG_UNWINDING: { label: "Long Unwinding", color: "text-orange-400", bg: "border-orange-500/30", icon: ArrowDownRight, desc: "OI ↓ Price ↓" },
};

// Sample data — in production, fetched from backend screener API
const SAMPLE_DATA = {
  LONG_BUILDUP: [
    { symbol: "NIFTY", oiChangePct: 12.5, priceChangePct: 1.2, ltp: 24200 },
    { symbol: "RELIANCE", oiChangePct: 8.3, priceChangePct: 0.8, ltp: 2540 },
    { symbol: "HDFCBANK", oiChangePct: 6.1, priceChangePct: 0.5, ltp: 1650 },
  ],
  SHORT_BUILDUP: [
    { symbol: "TATAMOTORS", oiChangePct: 15.2, priceChangePct: -2.1, ltp: 520 },
    { symbol: "WIPRO", oiChangePct: 9.8, priceChangePct: -1.5, ltp: 430 },
  ],
  SHORT_COVERING: [
    { symbol: "INFY", oiChangePct: -7.5, priceChangePct: 1.8, ltp: 1580 },
    { symbol: "TCS", oiChangePct: -5.2, priceChangePct: 0.9, ltp: 3600 },
  ],
  LONG_UNWINDING: [
    { symbol: "SBIN", oiChangePct: -11.3, priceChangePct: -1.4, ltp: 780 },
    { symbol: "ITC", oiChangePct: -6.8, priceChangePct: -0.6, ltp: 440 },
  ],
};

function QuadrantPanel({ quadrant, items }) {
  const cfg = QUADRANT_CONFIG[quadrant];
  const Icon = cfg.icon;
  return (
    <div className={`bg-gray-900 rounded-lg border ${cfg.bg} p-3`}>
      <div className={`flex items-center gap-2 mb-3 ${cfg.color}`}>
        <Icon size={16} />
        <span className="font-semibold text-sm">{cfg.label}</span>
        <span className="text-xs text-gray-500 ml-auto">{cfg.desc}</span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500">
            <th className="text-left pb-1">Symbol</th>
            <th className="text-right pb-1">OI Chg%</th>
            <th className="text-right pb-1">Price Chg%</th>
            <th className="text-right pb-1">LTP</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.symbol} className="border-t border-gray-800/50 hover:bg-gray-800/30">
              <td className="py-1 font-medium">{item.symbol}</td>
              <td className={`py-1 text-right font-mono ${item.oiChangePct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {item.oiChangePct >= 0 ? "+" : ""}{item.oiChangePct.toFixed(1)}%
              </td>
              <td className={`py-1 text-right font-mono ${item.priceChangePct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {item.priceChangePct >= 0 ? "+" : ""}{item.priceChangePct.toFixed(1)}%
              </td>
              <td className="py-1 text-right font-mono">{item.ltp.toLocaleString()}</td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={4} className="py-3 text-center text-gray-500">No data</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function FuturesOI() {
  const [data] = useState(SAMPLE_DATA);

  const basisData = [
    { name: "NIFTY", spot: 24180, futures: 24220, basis: 40 },
    { name: "BANKNIFTY", spot: 51200, futures: 51350, basis: 150 },
    { name: "FINNIFTY", spot: 23100, futures: 23130, basis: 30 },
  ];

  return (
    <div className="space-y-4">
      {/* 4 Quadrants */}
      <div className="grid grid-cols-2 gap-3">
        {Object.keys(QUADRANT_CONFIG).map((q) => (
          <QuadrantPanel key={q} quadrant={q} items={data[q] || []} />
        ))}
      </div>

      {/* Basis chart */}
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <div className="text-sm text-gray-400 mb-3">Futures Basis (Premium/Discount)</div>
        <ResponsiveContainer width="100%" height={150}>
          <BarChart data={basisData} layout="vertical">
            <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 10 }} />
            <YAxis dataKey="name" type="category" tick={{ fill: "#e5e5e5", fontSize: 11 }} width={80} />
            <Tooltip contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8, fontSize: 12 }} />
            <Bar dataKey="basis" radius={[0, 4, 4, 0]}>
              {basisData.map((entry, i) => (
                <Cell key={i} fill={entry.basis >= 0 ? "#22c55e" : "#ef4444"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
