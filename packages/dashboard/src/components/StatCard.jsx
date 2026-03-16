import { TrendingUp, TrendingDown } from "lucide-react";

export default function StatCard({ title, value, subtitle, trend, color = "text-gray-100" }) {
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
      <div className="text-[11px] text-gray-500 mb-1">{title}</div>
      <div className={`text-xl font-bold font-mono flex items-center gap-2 ${color}`}>
        {value}
        {trend === "up" && <TrendingUp size={16} className="text-emerald-400" />}
        {trend === "down" && <TrendingDown size={16} className="text-red-400" />}
      </div>
      {subtitle && <div className="text-[10px] text-gray-500 mt-1">{subtitle}</div>}
    </div>
  );
}
