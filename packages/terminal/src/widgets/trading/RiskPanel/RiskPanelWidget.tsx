/**
 * RiskPanelWidget
 *
 * Absorbed from:
 *   openalgo-chart/src/components/RiskCalculatorPanel/RiskCalculatorPanel.tsx
 *   (risk field structure and validation concepts)
 *
 * Data sources:
 *   - useFunds()     → margin used / available
 *   - usePositions() → active position count
 *   - useSettingsStore() → riskLimits (maxPositionLots, mtmStoploss, mtmTarget, maxOrdersPerMin)
 *   - useTradingStore()  → totalPnl, openOrderCount
 *
 * Visual:
 *   - shadcn Card + custom Tailwind progress bars
 *   - Color: green < 80%, yellow 80-95%, red >= 95%
 */

import { useMemo } from "react";
import {
  ShieldAlert,
  TrendingDown,
  Layers,
  Zap,
  Banknote,
  Target,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useFunds } from "@/hooks/useFunds";
import { usePositions } from "@/hooks/usePositions";
import { useSettingsStore } from "@/stores/settingsStore";
import { useTradingStore } from "@/stores/tradingStore";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function pct(used: number, max: number): number {
  if (max <= 0) return 0;
  return Math.min((used / max) * 100, 100);
}

type RiskLevel = "safe" | "warning" | "danger";

function riskLevel(usage: number): RiskLevel {
  if (usage >= 95) return "danger";
  if (usage >= 80) return "warning";
  return "safe";
}

const LEVEL_COLORS: Record<RiskLevel, { bar: string; text: string; badge: string }> = {
  safe: {
    bar: "bg-[#22C55E]",
    text: "text-[#22C55E]",
    badge: "bg-green-900/30 text-green-400 border-green-800",
  },
  warning: {
    bar: "bg-amber-400",
    text: "text-amber-400",
    badge: "bg-amber-900/30 text-amber-400 border-amber-800",
  },
  danger: {
    bar: "bg-[#EF4444]",
    text: "text-[#EF4444]",
    badge: "bg-red-900/30 text-red-400 border-red-800",
  },
};

// ---------------------------------------------------------------------------
// Progress bar row
// ---------------------------------------------------------------------------
function ProgressRow({
  label,
  usedLabel,
  maxLabel,
  usagePct,
  icon,
}: {
  label: string;
  usedLabel: string;
  maxLabel: string;
  usagePct: number;
  icon: React.ReactNode;
}) {
  const level = riskLevel(usagePct);
  const colors = LEVEL_COLORS[level];

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-white/30">{icon}</span>
          <span className="text-[10px] text-white/50">{label}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`font-mono text-[11px] font-medium ${colors.text}`}>{usedLabel}</span>
          <span className="text-[10px] text-white/20">/ {maxLabel}</span>
          <Badge
            className={`text-[9px] px-1 py-0 border ${colors.badge}`}
          >
            {usagePct.toFixed(0)}%
          </Badge>
        </div>
      </div>
      <div className="h-1 rounded-full bg-white/5 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${colors.bar}`}
          style={{ width: `${usagePct}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Summary badge row
// ---------------------------------------------------------------------------
function SummaryBadge({
  label,
  value,
  color,
  icon,
}: {
  label: string;
  value: string;
  color: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1 text-white/30">
        {icon}
        <span className="text-[9px] uppercase tracking-wider">{label}</span>
      </div>
      <span className={`font-mono text-[12px] font-bold ${color}`}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------
const INR_FMT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
  notation: "compact",
  compactDisplay: "short",
});

function formatINR(n: number): string {
  return INR_FMT.format(n);
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------
export default function RiskPanelWidget(_props: WidgetProps) {
  const { data: fundsData } = useFunds();
  const { data: positions } = usePositions();
  const riskLimits = useSettingsStore((s) => s.riskLimits);
  const { totalPnl, openOrderCount } = useTradingStore();

  // Derived values
  const usedMargin = fundsData?.usedMargin ?? 0;
  const availableCash = fundsData?.availableCash ?? 0;
  const totalBalance = fundsData?.totalBalance ?? (usedMargin + availableCash);

  // Position count (each row = 1 lot for simplicity; real lot tracking needs instrument metadata)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const positionCount = (positions as any[] | undefined)?.length ?? 0;

  // Daily PnL vs target/stoploss
  const pnlVsTarget = pct(Math.max(totalPnl, 0), riskLimits.mtmTarget);
  const pnlVsSl = pct(Math.abs(Math.min(totalPnl, 0)), Math.abs(riskLimits.mtmStoploss));

  // Margin utilisation
  const marginUsagePct = pct(usedMargin, totalBalance);

  // Position lots usage
  const positionUsagePct = pct(positionCount, riskLimits.maxPositionLots);

  // Order rate (live tracking not available without WS; shows open orders vs max/min as proxy)
  const orderRatePct = pct(openOrderCount, riskLimits.maxOrdersPerMin);

  // Overall risk status — highest danger level wins
  const overallLevel = useMemo<RiskLevel>(() => {
    const levels: RiskLevel[] = [
      riskLevel(marginUsagePct),
      riskLevel(positionUsagePct),
      riskLevel(pnlVsSl),
    ];
    if (levels.includes("danger")) return "danger";
    if (levels.includes("warning")) return "warning";
    return "safe";
  }, [marginUsagePct, positionUsagePct, pnlVsSl]);

  const overallColors = LEVEL_COLORS[overallLevel];
  const overallLabel = overallLevel === "danger" ? "High Risk" : overallLevel === "warning" ? "Caution" : "Safe";

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-[#0a0a0f]">
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-[#1e1e2e] shrink-0">
        <div className="flex items-center gap-1.5">
          <ShieldAlert size={11} className="text-white/40" />
          <span className="text-white/60 uppercase tracking-wider text-[10px]">Risk Panel</span>
        </div>
        <Badge className={`text-[9px] px-1.5 py-0 border ${overallColors.badge}`}>
          {overallLabel}
        </Badge>
      </div>

      <div className="flex-1 overflow-auto p-2 space-y-3">
        {/* Summary row */}
        <Card className="bg-[#12121a] border-[#1e1e2e]">
          <CardContent className="p-2">
            <div className="grid grid-cols-3 gap-2">
              <SummaryBadge
                label="Available"
                value={formatINR(availableCash)}
                color="text-white/80"
                icon={<Banknote size={9} />}
              />
              <SummaryBadge
                label="Daily PnL"
                value={formatINR(totalPnl)}
                color={totalPnl >= 0 ? "text-[#22C55E]" : "text-[#EF4444]"}
                icon={<TrendingDown size={9} />}
              />
              <SummaryBadge
                label="Positions"
                value={`${positionCount} / ${riskLimits.maxPositionLots}`}
                color={LEVEL_COLORS[riskLevel(positionUsagePct)].text}
                icon={<Layers size={9} />}
              />
            </div>
          </CardContent>
        </Card>

        {/* Progress bars */}
        <Card className="bg-[#12121a] border-[#1e1e2e]">
          <CardContent className="p-2 space-y-3">
            <ProgressRow
              label="Margin Used"
              usedLabel={formatINR(usedMargin)}
              maxLabel={formatINR(totalBalance)}
              usagePct={marginUsagePct}
              icon={<Banknote size={9} />}
            />

            <ProgressRow
              label="Position Lots"
              usedLabel={String(positionCount)}
              maxLabel={String(riskLimits.maxPositionLots)}
              usagePct={positionUsagePct}
              icon={<Layers size={9} />}
            />

            <ProgressRow
              label="Open Orders"
              usedLabel={String(openOrderCount)}
              maxLabel={`${riskLimits.maxOrdersPerMin}/min`}
              usagePct={orderRatePct}
              icon={<Zap size={9} />}
            />

            <div className="border-t border-[#1e1e2e] pt-2 space-y-3">
              <ProgressRow
                label="Daily Target"
                usedLabel={totalPnl > 0 ? formatINR(totalPnl) : formatINR(0)}
                maxLabel={formatINR(riskLimits.mtmTarget)}
                usagePct={pnlVsTarget}
                icon={<Target size={9} />}
              />

              <ProgressRow
                label="Daily SL Exposure"
                usedLabel={totalPnl < 0 ? formatINR(Math.abs(totalPnl)) : formatINR(0)}
                maxLabel={formatINR(Math.abs(riskLimits.mtmStoploss))}
                usagePct={pnlVsSl}
                icon={<TrendingDown size={9} />}
              />
            </div>
          </CardContent>
        </Card>

        {/* Limits reference */}
        <Card className="bg-[#12121a] border-[#1e1e2e]">
          <CardContent className="p-2">
            <p className="text-[9px] text-white/20 uppercase tracking-wider mb-1.5">Configured Limits</p>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
              {[
                ["Max Lots", riskLimits.maxPositionLots],
                ["MTM Target", formatINR(riskLimits.mtmTarget)],
                ["MTM SL", formatINR(riskLimits.mtmStoploss)],
                ["Orders/Min", riskLimits.maxOrdersPerMin],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between">
                  <span className="text-[10px] text-white/30">{label}</span>
                  <span className="font-mono text-[10px] text-white/60">{value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
