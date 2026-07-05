/**
 * NetWorthTab.tsx
 *
 * Full net worth breakdown: known total, donut allocation chart, and
 * per-asset-class status cards. Equity + Cash live from the connected broker;
 * other asset classes show "Not connected" with a disabled Add button.
 *
 * Adapted pattern from etftracker Dashboard3_SectorRotation: side-by-side
 * donut + legend layout with category pills below.
 */

import { useMemo } from "react";
import { FlintDonutBreakdown, FlintRankedBarList } from "@flinttrade/design-system";
import {
  TrendingUp,
  Wallet,
  BarChart3,
  Globe,
  DollarSign,
  Plus,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { GlassCard } from "@/components/ui/GlassCard";
import { StaggeredList } from "@/components/motion/StaggeredList";
import { cn } from "@/lib/utils";
import { useInvest } from "../InvestContext";
import { DisabledActionButton } from "../DisabledActionButton";
import { formatINRCompact, formatPercent } from "../formatters";

// ─── Asset category definition ────────────────────────────────────────────────

interface AssetCategory {
  label: string;
  value: number | null;
  note: string;
  hexColor: string;
  tailwindBg: string;
  tailwindText: string;
  icon: typeof TrendingUp;
  addLabel: string;
  addTooltip: string;
}

// ─── Invested vs current bar data ────────────────────────────────────────────

interface ComparisonEntry {
  name: string;
  value: number;
}

function buildComparison(totalInvested: number, currentValue: number): ComparisonEntry[] {
  return [
    { name: "Invested", value: totalInvested },
    { name: "Current", value: currentValue },
    { name: "P&L", value: currentValue - totalInvested },
  ];
}

// ─── Component ────────────────────────────────────────────────────────────────

export function NetWorthTab() {
  const { summary, isLoading } = useInvest();
  const { currentValue, totalInvested, totalPnl, totalPnlPercent, availableCash } = summary;

  const knownTotal = currentValue + availableCash;
  const comparison = useMemo(
    () => buildComparison(totalInvested, currentValue),
    [totalInvested, currentValue],
  );

  const categories: AssetCategory[] = [
    {
      label: "Equity Holdings",
      value: isLoading ? null : currentValue,
      note: "Live from broker",
      hexColor: "#3b82f6",
      tailwindBg: "bg-blue-500",
      tailwindText: "text-blue-400",
      icon: TrendingUp,
      addLabel: "Add Equity",
      addTooltip: "Buy via your connected broker — holdings sync automatically.",
    },
    {
      label: "Available Cash",
      value: isLoading ? null : availableCash,
      note: "Live from broker",
      hexColor: "#22c55e",
      tailwindBg: "bg-emerald-500",
      tailwindText: "text-emerald-400",
      icon: Wallet,
      addLabel: "Add Cash",
      addTooltip: "Deposit funds via your broker — balance syncs automatically.",
    },
    {
      label: "Mutual Funds",
      value: null,
      note: "Connect NAV source — Settings → Data Sources",
      hexColor: "#a855f7",
      tailwindBg: "bg-purple-500",
      tailwindText: "text-purple-400",
      icon: BarChart3,
      addLabel: "Add MF",
      addTooltip: "Connect a NAV provider (jugaad-data / mftool) in Settings to track MF folios.",
    },
    {
      label: "Gold",
      value: null,
      note: "Manual entry available in a future update",
      hexColor: "#f59e0b",
      tailwindBg: "bg-amber-500",
      tailwindText: "text-amber-400",
      icon: Globe,
      addLabel: "Add Gold",
      addTooltip: "Manual gold tracking (sovereign bonds, physical, ETF) coming in a future update.",
    },
    {
      label: "Fixed Deposits",
      value: null,
      note: "Manual entry available in a future update",
      hexColor: "#06b6d4",
      tailwindBg: "bg-cyan-500",
      tailwindText: "text-cyan-400",
      icon: DollarSign,
      addLabel: "Add FD",
      addTooltip: "Track fixed deposits with maturity dates and interest tracking — coming soon.",
    },
  ];

  const knownCategories = categories.filter((c) => c.value !== null && c.value > 0);
  const donutTotal = knownCategories.reduce((acc, c) => acc + (c.value ?? 0), 0);

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div>
        <h3 className="font-heading font-semibold text-sm text-text-primary">
          Net Worth Breakdown
        </h3>
        <p className="text-xs text-text-muted mt-0.5">
          Live equity and cash from your connected broker. Other asset classes require additional data sources.
        </p>
      </div>

      {/* Known total + donut side by side */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Known total card */}
        <GlassCard className="p-5 flex flex-col justify-between gap-3">
          <div className="text-xxs text-text-muted uppercase tracking-wider">
            Known Total (Equity + Cash)
          </div>
          <div
            className={cn(
              "font-mono text-2xl font-bold tabular-nums",
              isLoading ? "text-text-muted" : "text-text-primary",
            )}
          >
            {isLoading ? "—" : formatINRCompact(knownTotal)}
          </div>
          {!isLoading && (
            <div
              className={cn(
                "text-sm font-mono tabular-nums",
                totalPnl >= 0 ? "text-profit" : "text-loss",
              )}
            >
              {formatINRCompact(totalPnl)}{" "}
              <span className="text-xs opacity-75">
                ({formatPercent(totalPnlPercent)} unrealised)
              </span>
            </div>
          )}

          {/* Invested vs current bar */}
          {!isLoading && currentValue > 0 && (
            <div className="pt-2 border-t border-border-default">
              <div className="text-xxs text-text-muted mb-2 uppercase tracking-wider">
                Invested vs Current
              </div>
              <FlintRankedBarList
                ariaLabel="Invested versus current values"
                entries={comparison.map((entry, index) => ({
                  label: entry.name,
                  value: entry.value,
                  color: ["#60a5fa", "#34d399", totalPnl >= 0 ? "#34d399" : "#f87171"][index],
                }))}
                valueFormatter={(v: number) => formatINRCompact(v)}
                className="text-xs"
              />
            </div>
          )}
        </GlassCard>

        {/* Donut chart */}
        <GlassCard className="p-5 flex flex-col items-center gap-4">
          <div className="text-xxs text-text-muted uppercase tracking-wider self-start">
            Allocation (live assets only)
          </div>
          {knownCategories.length > 0 ? (
            <>
              <div className="relative w-36 h-36 shrink-0 flex items-center justify-center">
                <FlintDonutBreakdown
                  ariaLabel="Live asset allocation donut"
                  slices={knownCategories.map((c) => ({
                    label: c.label,
                    value: c.value ?? 0,
                    color: c.hexColor,
                  }))}
                  className="size-36"
                />
                <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span className="text-xxs text-text-muted">tracked</span>
                  <span className="font-mono text-xs font-bold text-text-primary tabular-nums">
                    {isLoading ? "—" : formatINRCompact(knownTotal)}
                  </span>
                </div>
              </div>

              {/* Legend */}
              <div className="w-full space-y-1.5">
                {knownCategories.map((cat) => {
                  const pct = donutTotal > 0 ? ((cat.value ?? 0) / donutTotal) * 100 : 0;
                  return (
                    <div key={cat.label} className="flex items-center gap-2 text-xs">
                      <span className={cn("size-2.5 rounded-sm shrink-0", cat.tailwindBg)} />
                      <span className="text-text-secondary flex-1">{cat.label}</span>
                      <span className="font-mono tabular-nums text-text-primary">
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-xs text-text-muted text-center">
              Connect a broker to see allocation chart.
            </div>
          )}
        </GlassCard>
      </div>

      {/* Per-category cards */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          All Asset Classes
        </h4>
        <StaggeredList staggerDelay={30}>
          {categories.map((cat) => {
            const Icon = cat.icon;
            return (
              <div
                key={cat.label}
                className="flex items-center gap-3 p-3 rounded-lg bg-surface-card border border-border-default"
              >
                <div
                  className="size-8 rounded-lg flex items-center justify-center shrink-0 opacity-80"
                  style={{ backgroundColor: cat.hexColor + "20" }}
                >
                  <Icon className={cn("size-4", cat.tailwindText)} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-text-primary">{cat.label}</div>
                  <div className="text-xs text-text-muted">{cat.note}</div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {cat.value !== null ? (
                    <span className="font-mono tabular-nums text-xs text-text-primary">
                      {formatINRCompact(cat.value)}
                    </span>
                  ) : (
                    <Badge
                      variant="outline"
                      className="text-xs border-border-default text-text-muted"
                    >
                      Not connected
                    </Badge>
                  )}
                  <DisabledActionButton
                    label={cat.addLabel}
                    tooltip={cat.addTooltip}
                    icon={Plus}
                  />
                </div>
              </div>
            );
          })}
        </StaggeredList>
      </div>
    </div>
  );
}
