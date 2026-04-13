import { motion } from "framer-motion";
import { AreaChart } from "@tremor/react";
import { motionConfig } from "@/lib/motion";
import { fmtInr } from "./formatters";

export interface EquityCurveProps {
  curve: Array<{ timestamp: string; equity: number }>;
  initialEquity: number;
}

export function EquityCurve({ curve, initialEquity }: EquityCurveProps) {
  if (curve.length === 0) return null;

  const step = Math.max(1, Math.floor(curve.length / 120));
  const sampled = curve
    .filter((_, i) => i % step === 0)
    .map((p) => ({
      date: p.timestamp.slice(0, 10),
      Equity: p.equity,
    }));

  const lastEquity = sampled[sampled.length - 1]?.Equity ?? initialEquity;
  const isPositive = lastEquity >= initialEquity;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={motionConfig.transitions.fade}
    >
      <AreaChart
        data={sampled}
        index="date"
        categories={["Equity"]}
        colors={[isPositive ? "emerald" : "red"]}
        valueFormatter={(v: number) => fmtInr(v)}
        showLegend={false}
        showYAxis={true}
        showXAxis={true}
        showGridLines={false}
        className="h-36 text-xs"
        curveType="monotone"
      />
    </motion.div>
  );
}
