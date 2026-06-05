/**
 * RiskDashboardWidget — Portfolio-level risk metrics with radial gauges.
 *
 * Metrics shown:
 *   - Total exposure (gross notional value of all open positions)
 *   - Net delta (sum of deltas across option/future positions)
 *   - Net theta (daily time decay in INR)
 *   - Margin utilised % (used margin / total margin)
 *   - Max loss (worst-case scenario from positions)
 *
 * Traffic-light system per metric:
 *   green  → within limits (usage < 70%)
 *   amber  → approaching limits (usage 70–90%)
 *   red    → breached or critical (usage ≥ 90%)
 *
 * Uses sample data when disconnected; live data from hooks when connected.
 */

import { useMemo, useEffect, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { FlintRadialGauge } from "@flinttrade/design-system";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getPositionbook, getFunds } from "@/services/api";
import { queryKeys } from "@/services/queryKeys";
import { isMarketHours } from "@/lib/market";
import type { Position, Funds } from "@/types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TrafficLight = "green" | "amber" | "red";

export interface RiskMetric {
  id: string;
  label: string;
  value: number;
  limit: number;
  unit: string;
  formatted: string;
  limitFormatted: string;
  usagePct: number;
  level: TrafficLight;
}

export interface RiskDashboardData {
  metrics: RiskMetric[];
  overallLevel: TrafficLight;
  timestamp: string;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

function buildMetric(
  id: string,
  label: string,
  value: number,
  limit: number,
  unit: string,
  formatFn: (v: number) => string,
): RiskMetric {
  const usagePct = limit > 0 ? Math.min((Math.abs(value) / limit) * 100, 100) : 0;
  const level: TrafficLight = usagePct >= 90 ? "red" : usagePct >= 70 ? "amber" : "green";
  return { id, label, value, limit, unit, formatted: formatFn(value), limitFormatted: formatFn(limit), usagePct, level };
}

const INR_COMPACT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  notation: "compact",
  maximumFractionDigits: 1,
});

function fmtINR(v: number): string {
  return INR_COMPACT.format(v);
}

function fmtNum(v: number, decimals = 0): string {
  return v.toFixed(decimals);
}

export const SAMPLE_RISK_DATA: RiskDashboardData = {
  metrics: [
    buildMetric("exposure",  "Total Exposure",   1_420_000, 2_000_000, "INR",  fmtINR),
    buildMetric("delta",     "Net Delta",         -12.5,     50,        "Δ",    (v) => fmtNum(v, 1)),
    buildMetric("theta",     "Net Theta",        -3200,    -10_000,     "INR/d", fmtINR),
    buildMetric("margin",    "Margin Utilised",   68,        100,       "%",    (v) => `${fmtNum(v, 1)}%`),
    buildMetric("maxloss",   "Max Loss",          85_000,   150_000,   "INR",  fmtINR),
  ],
  overallLevel: "amber",
  timestamp: "15:23 IST",
};

const LEVEL_RANK: Record<TrafficLight, number> = { green: 0, amber: 1, red: 2 };

function worstLevel(metrics: RiskMetric[]): TrafficLight {
  return metrics.reduce<TrafficLight>(
    (worst, m) => (LEVEL_RANK[m.level] > LEVEL_RANK[worst] ? m.level : worst),
    "green",
  );
}

function nowIstHHMM(): string {
  try {
    return (
      new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata",
      }).format(new Date()) + " IST"
    );
  } catch {
    return "";
  }
}

/**
 * Build the risk dashboard from real broker data. Only metrics we can derive
 * faithfully are shown: Total Exposure (gross notional from the positionbook)
 * and Margin Utilised (usedMargin / totalBalance from funds). Net delta, net
 * theta and max-loss require a portfolio option-greeks/payoff feed that is not
 * wired yet — they are omitted rather than fabricated, so a connected user is
 * never shown invented risk numbers.
 */
export function computeLiveRisk(positions: Position[], funds?: Funds): RiskDashboardData {
  const exposure = positions.reduce((s, p) => s + Math.abs(p.quantity * p.averagePrice), 0);
  const totalBalance = funds?.totalBalance ?? 0;
  const usedMargin = funds?.usedMargin ?? 0;
  const marginPct = totalBalance > 0 ? (usedMargin / totalBalance) * 100 : 0;

  const metrics: RiskMetric[] = [
    buildMetric(
      "exposure", "Total Exposure", exposure,
      totalBalance > 0 ? totalBalance : exposure, "INR", fmtINR,
    ),
    buildMetric("margin", "Margin Utilised", marginPct, 100, "%", (v) => `${fmtNum(v, 1)}%`),
  ];

  return { metrics, overallLevel: worstLevel(metrics), timestamp: nowIstHHMM() };
}

const GAUGE_COLOURS: Record<TrafficLight, { stroke: string; bg: string; text: string }> = {
  green: { stroke: "#22c55e", bg: "rgba(34,197,94,0.12)", text: "text-profit" },
  amber: { stroke: "#f59e0b", bg: "rgba(245,158,11,0.12)", text: "text-warning" },
  red:   { stroke: "#ef4444", bg: "rgba(239,68,68,0.12)",  text: "text-loss" },
};

const BADGE_CLASSES: Record<TrafficLight, string> = {
  green: "bg-bullish-bg text-profit border-bullish-border",
  amber: "bg-atm-bg text-warning border-atm-border",
  red:   "bg-bearish-bg text-loss border-bearish-border",
};

// ---------------------------------------------------------------------------
// Metric card
// ---------------------------------------------------------------------------

function MetricCard({ metric }: { metric: RiskMetric }) {
  const colours = GAUGE_COLOURS[metric.level];

  return (
    <div
      className="flex items-center gap-3 bg-surface-card rounded-lg border border-border-default px-3 py-2.5"
      style={{ background: metric.level !== "green" ? colours.bg : undefined }}
      aria-label={`${metric.label}: ${metric.formatted} of ${metric.limitFormatted} limit, ${metric.level} status`}
    >
      {/* Gauge */}
      <div className="relative shrink-0">
        <FlintRadialGauge
          value={metric.usagePct}
          color={colours.stroke}
          size={56}
          decorative
        />
        {/* Pct label inside gauge */}
        <div
          className={cn(
            "absolute inset-0 flex items-center justify-center text-xxs font-bold font-mono tabular-nums",
            colours.text,
          )}
          style={{ transform: "none" }}
        >
          {metric.usagePct.toFixed(0)}%
        </div>
      </div>

      {/* Labels */}
      <div className="flex-1 min-w-0">
        <div className="text-xxs text-text-muted uppercase tracking-wide truncate">{metric.label}</div>
        <div className={cn("text-sm font-bold font-mono tabular-nums", colours.text)}>
          {metric.formatted}
        </div>
        <div className="text-xxs text-text-muted font-mono">
          Limit: {metric.limitFormatted}
        </div>
      </div>

      {/* Traffic light dot */}
      <div
        className={cn("w-2.5 h-2.5 rounded-full shrink-0", {
          "bg-profit":  metric.level === "green",
          "bg-warning": metric.level === "amber",
          "bg-loss":    metric.level === "red",
        })}
        aria-label={`${metric.level} status`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overall status banner
// ---------------------------------------------------------------------------

function StatusBanner({ level, timestamp }: { level: TrafficLight; timestamp: string }) {
  const labels: Record<TrafficLight, string> = {
    green: "All Clear",
    amber: "Caution",
    red:   "Risk Breached",
  };

  return (
    <div
      className={cn(
        "flex items-center justify-between px-3 py-2 rounded border text-xs font-semibold",
        BADGE_CLASSES[level],
      )}
      aria-label={`Overall risk status: ${labels[level]}`}
    >
      <span>{labels[level]}</span>
      <span className="text-xxs font-normal opacity-70">{timestamp}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function RiskDashboardWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  useEffect(() => {
    track("trade", "widget_view_risk_dashboard");
  }, [track]);

  // Connected → real risk from the positionbook + funds; disconnected → labelled
  // sample data. Never show fabricated risk metrics to a live user.
  const { data: livePositions } = useQuery<Position[]>({
    queryKey: queryKeys.positions.all,
    queryFn: getPositionbook,
    enabled: isConnected,
    staleTime: 3_000,
    refetchInterval: isConnected ? () => (isMarketHours() ? 5_000 : 60_000) : false,
  });
  const { data: liveFunds } = useQuery<Funds>({
    queryKey: queryKeys.funds.all,
    queryFn: getFunds,
    enabled: isConnected,
    staleTime: 15_000,
    refetchInterval: isConnected ? 30_000 : false,
  });

  const data: RiskDashboardData = useMemo(
    () => (isConnected ? computeLiveRisk(livePositions ?? [], liveFunds) : SAMPLE_RISK_DATA),
    [isConnected, livePositions, liveFunds],
  );

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Risk Dashboard widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <ShieldAlert size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Risk Dashboard</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-2">

        {/* Overall status */}
        <StatusBanner level={data.overallLevel} timestamp={data.timestamp} />

        {/* Metric cards */}
        <div className="space-y-1.5" aria-label="Risk metrics">
          {data.metrics.map((m) => (
            <MetricCard key={m.id} metric={m} />
          ))}
        </div>

        {/* Honest note: greeks-derived metrics aren't wired for live data yet. */}
        {isConnected && (
          <p className="text-xxs text-text-muted px-1 leading-snug">
            Net delta, net theta and max-loss need a connected option-greeks feed
            and are not shown live yet — only metrics derived from your real
            positions and funds appear above.
          </p>
        )}

        {/* Legend */}
        <div className="flex items-center gap-3 pt-1 px-1">
          {(["green", "amber", "red"] as TrafficLight[]).map((l) => {
            const labels = { green: "Within limits (<70%)", amber: "Approaching (70–90%)", red: "Breached (≥90%)" };
            return (
              <div key={l} className="flex items-center gap-1.5">
                <div
                  className={cn("w-2 h-2 rounded-full shrink-0", {
                    "bg-profit":  l === "green",
                    "bg-warning": l === "amber",
                    "bg-loss":    l === "red",
                  })}
                />
                <span className="text-xxs text-text-muted">{labels[l]}</span>
              </div>
            );
          })}
        </div>

      </div>
    </div>
  );
}

export default memo(RiskDashboardWidget);
