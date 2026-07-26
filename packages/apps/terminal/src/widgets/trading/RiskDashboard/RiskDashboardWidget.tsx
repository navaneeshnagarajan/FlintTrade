/**
 * Risk — the single risk surface (component id `riskdashboard`).
 *
 * Merged from the former Risk Panel (`riskpanel`) and Risk Dashboard
 * (`riskdashboard`). The two widgets shared exactly ONE real metric — margin
 * utilisation, computed identically — but banded it differently (80/95 vs
 * 70/90), so an operator with both open saw the same account at two different
 * risk levels. There is now one metric source ({@link computeLiveRisk}) and one
 * threshold set ({@link AMBER_AT}/{@link RED_AT}).
 *
 * What this widget actually computes:
 *   - Margin utilised % (usedMargin / totalBalance) — the only gauge, because
 *     it is the only quantity with a real 0–100% limit.
 *   - Total exposure, open position count and available cash — informational,
 *     no limit semantics.
 *   - Session mark-to-market against the operator's local MTM target and
 *     stop-loss references.
 *
 * What it deliberately does NOT compute: max drawdown and leverage (both were
 * promised by the old catalogue entries and implemented by neither widget), and
 * net delta / net theta / max-loss (no portfolio greeks feed is wired).
 *
 * Uses a labelled sample in Explore, sandbox data in Practice, and broker data
 * in Live.
 */

import { useMemo, useEffect, memo } from "react";
import { ShieldAlert, TrendingDown, Layers, Zap, Target } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { FlintRadialGauge } from "@flinttrade/design-system";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { totalPositionMtm } from "@/lib/pnl";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useDataScope } from "@/hooks/useDataScope";
import { useFunds } from "@/hooks/useFunds";
import { usePositions } from "@/hooks/usePositions";
import { useSettingsStore } from "@/stores/settingsStore";
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

/** Informational value with no limit/traffic-light semantics (e.g. exposure). */
export interface RiskInfoStat {
  label: string;
  value: string;
}

export interface RiskDashboardData {
  metrics: RiskMetric[];
  /** Plain values shown without a gauge — for quantities that have no meaningful
   *  0–100% limit (notional exposure under F&O leverage). Optional. */
  infoStats?: RiskInfoStat[];
  overallLevel: TrafficLight;
  timestamp: string;
  /** Session mark-to-market, from the shared {@link totalPositionMtm} definition. */
  dayPnl: number;
}

// ---------------------------------------------------------------------------
// Thresholds — ONE set for every band in this widget
// ---------------------------------------------------------------------------

/**
 * Amber/red bands, applied to every usage percentage the widget renders: the
 * margin gauge and the daily target/stop-loss bars.
 *
 * The two merged widgets disagreed — Risk Panel warned at 80/95, Risk Dashboard
 * at 70/90 — and the earlier pair is kept deliberately, not averaged. A risk
 * readout's failure modes are not symmetric: a caution shown a little early
 * costs the operator a glance, a caution shown late costs a margin call or a
 * blown daily stop, and margin utilisation moves fastest exactly when it is
 * already high. 90% used margin is already inside the broker's square-off
 * territory, so 95% is not a useful place to first turn red.
 */
const AMBER_AT = 70;
const RED_AT = 90;

/** The single banding function. Both the gauges and the bars go through it. */
export function levelForUsage(usagePct: number): TrafficLight {
  if (usagePct >= RED_AT) return "red";
  if (usagePct >= AMBER_AT) return "amber";
  return "green";
}

/** Usage percentage of `used` against `max`, clamped to 0–100. */
function pct(used: number, max: number): number {
  if (max <= 0) return 0;
  return Math.min((used / max) * 100, 100);
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

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

function fmtPct(v: number): string {
  return `${fmtNum(v, 1)}%`;
}

// ---------------------------------------------------------------------------
// Metric construction
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
  return {
    id,
    label,
    value,
    limit,
    unit,
    formatted: formatFn(value),
    limitFormatted: formatFn(limit),
    usagePct,
    level: levelForUsage(usagePct),
  };
}

const LEVEL_RANK: Record<TrafficLight, number> = { green: 0, amber: 1, red: 2 };

function worstLevel(metrics: RiskMetric[]): TrafficLight {
  return metrics.reduce<TrafficLight>(
    (worst, m) => (LEVEL_RANK[m.level] > LEVEL_RANK[worst] ? m.level : worst),
    "green",
  );
}

function worstOf(a: TrafficLight, b: TrafficLight): TrafficLight {
  return LEVEL_RANK[b] > LEVEL_RANK[a] ? b : a;
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

// ---------------------------------------------------------------------------
// Sample data (Explore)
// ---------------------------------------------------------------------------

/**
 * The Explore sample carries the same shape the live path produces — one margin
 * gauge plus the informational stats — and nothing else.
 *
 * The retired Risk Dashboard sample also carried net delta, net theta and a
 * max-loss figure. Those were dropped rather than ported: no live code path can
 * ever produce them (there is no portfolio greeks/payoff feed), so a sample that
 * showed them promised the operator a capability the widget does not have. The
 * sample's job is to demonstrate the real layout, not a richer imaginary one.
 */
const SAMPLE_METRICS: RiskMetric[] = [
  buildMetric("margin", "Margin Utilised", 68, 100, "%", fmtPct),
];

export const SAMPLE_RISK_DATA: RiskDashboardData = {
  metrics: SAMPLE_METRICS,
  infoStats: [
    { label: "Total Exposure", value: fmtINR(1_420_000) },
    { label: "Open Positions", value: "3" },
    { label: "Available Cash", value: fmtINR(455_000) },
  ],
  overallLevel: worstLevel(SAMPLE_METRICS),
  timestamp: "15:23 IST",
  dayPnl: 4_200,
};

// ---------------------------------------------------------------------------
// Live metrics — the single source
// ---------------------------------------------------------------------------

/**
 * Build the risk readout from real account data. The ONE metric source for this
 * widget; nothing else in it derives a risk number from positions or funds.
 *
 * Margin Utilised (usedMargin / totalBalance) is the one metric that maps to a
 * meaningful 0–100% traffic-light gauge, so it is the only gauge shown. Total
 * Exposure (gross notional from the positionbook) is shown as an informational
 * value, NOT a gauge: account balance is the wrong "limit" for it — F&O leverage
 * routinely makes notional exceed balance, and before funds load the balance is
 * unknown, both of which would otherwise paint a false red "Risk Breached".
 * Open Positions is a row count, likewise informational — a position row is not
 * a lot, and it must never stand in for a lot limit. Net delta, net theta and
 * max-loss need a portfolio option-greeks/payoff feed that is not wired yet and
 * are omitted rather than fabricated. A connected user is therefore never shown
 * an invented or misleading risk verdict.
 *
 * `dayPnl` uses {@link totalPositionMtm} — the shared mark-to-market definition
 * — so the daily target/stop-loss bars below agree with MTM Monitor's chart
 * rather than re-summing the raw broker `pnl` field the way the retired Risk
 * Panel did.
 *
 * @param positions - Current position book (empty when flat or unloaded).
 * @param funds - Account funds; undefined until the funds query resolves.
 * @returns The metrics, info stats, overall level, timestamp and session MTM.
 */
export function computeLiveRisk(positions: Position[], funds?: Funds): RiskDashboardData {
  const exposure = positions.reduce((s, p) => s + Math.abs(p.quantity * p.averagePrice), 0);
  const totalBalance = funds?.totalBalance ?? 0;
  const usedMargin = funds?.usedMargin ?? 0;
  const marginPct = totalBalance > 0 ? (usedMargin / totalBalance) * 100 : 0;

  // Only gauge metrics that have a real 0–100% limit. Margin utilisation only
  // applies once funds are known; otherwise it is shown as an info stat too.
  const metrics: RiskMetric[] = [];
  const infoStats: RiskInfoStat[] = [
    { label: "Total Exposure", value: fmtINR(exposure) },
    { label: "Open Positions", value: String(positions.length) },
    { label: "Available Cash", value: funds ? fmtINR(funds.availableCash) : "—" },
  ];

  if (totalBalance > 0) {
    metrics.push(buildMetric("margin", "Margin Utilised", marginPct, 100, "%", fmtPct));
  } else {
    infoStats.push({ label: "Margin Utilised", value: "—" });
  }

  return {
    metrics,
    infoStats,
    overallLevel: worstLevel(metrics),
    timestamp: nowIstHHMM(),
    dayPnl: totalPositionMtm(positions),
  };
}

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

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

const BAR_CLASSES: Record<TrafficLight, string> = {
  green: "bg-profit",
  amber: "bg-warning",
  red:   "bg-loss",
};

const TEXT_CLASSES: Record<TrafficLight, string> = {
  green: "text-profit",
  amber: "text-warning",
  red:   "text-loss",
};

// ---------------------------------------------------------------------------
// Metric card (gauge)
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
        className={cn("w-2.5 h-2.5 rounded-full shrink-0", BAR_CLASSES[metric.level])}
        aria-label={`${metric.level} status`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress bar row (settings-referenced MTM bars)
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
  const level = levelForUsage(usagePct);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-text-disabled">{icon}</span>
          <span className="text-xs text-text-secondary">{label}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={cn("font-mono tabular-nums text-xs font-medium", TEXT_CLASSES[level])}>{usedLabel}</span>
          <span className="text-xs text-text-disabled">/ {maxLabel}</span>
          <Badge className={cn("text-xxs px-1 py-0 border", BADGE_CLASSES[level])}>
            {usagePct.toFixed(0)}%
          </Badge>
        </div>
      </div>
      <div className="h-1 rounded-full bg-surface-hover overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-[width] duration-500", BAR_CLASSES[level])}
          style={{ width: `${usagePct}%` }}
        />
      </div>
    </div>
  );
}

/** A limit the widget cannot measure. Says so instead of substituting a proxy. */
function UnavailableRow({
  label,
  detail,
  icon,
}: {
  label: string;
  detail: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex items-center gap-1.5">
        <span className="text-text-disabled">{icon}</span>
        <span className="text-xs text-text-secondary">{label}</span>
      </div>
      <span className="max-w-[65%] text-right text-xxs leading-relaxed text-text-disabled">
        Unavailable: {detail}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overall status banner
// ---------------------------------------------------------------------------

/**
 * Wording is deliberately observational. The widget sees margin utilisation and
 * the operator's local MTM references — not the whole account's risk — so it
 * never claims "All Clear".
 */
const STATUS_LABELS: Record<TrafficLight, string> = {
  green: "Indicators normal",
  amber: "Observed caution",
  red:   "Observed danger",
};

function StatusBanner({ level, timestamp }: { level: TrafficLight; timestamp: string }) {
  return (
    <div
      className={cn(
        "flex items-center justify-between px-3 py-2 rounded border text-xs font-semibold",
        BADGE_CLASSES[level],
      )}
      aria-label={`Overall risk status: ${STATUS_LABELS[level]}`}
    >
      <span>{STATUS_LABELS[level]}</span>
      <span className="text-xxs font-normal opacity-70">{timestamp}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function RiskWidget() {
  const track = useTrackBehavior();

  // ONE enablement predicate for this widget: the data scope. It is the same key
  // the position/funds queries are cached under, so the read gate and the cache
  // can never disagree, and unlike `useAccountReadsEnabled` it distinguishes
  // "Explore, show the labelled sample" from "Live but no broker configured",
  // which this widget renders differently.
  const dataScope = useDataScope();
  const isExplore = dataScope === "explore:mock";
  const isPractice = dataScope.startsWith("practice:");
  const hasAccountSource = dataScope !== "live:unconfigured";
  const shouldReadAccountData = hasAccountSource && !isExplore;

  useEffect(() => {
    track("trade", "widget_view_risk_dashboard");
  }, [track]);

  const { data: livePositions } = usePositions({ enabled: shouldReadAccountData });
  const { data: liveFunds } = useFunds({ enabled: shouldReadAccountData });

  // The MTM target/stop-loss references are ONE setting with two renderings:
  // this widget draws them as progress bars, MTM Monitor draws the identical
  // `settingsStore.riskLimits` values as chart price lines
  // (widgets/trading/MTMMonitor/MTMMonitorWidget.tsx). Read the shared store —
  // never re-derive or re-store these numbers, or the two surfaces drift.
  const riskLimits = useSettingsStore(useShallow((s) => s.riskLimits));

  const data: RiskDashboardData | null = useMemo(
    () => isExplore
      ? SAMPLE_RISK_DATA
      : hasAccountSource
        ? computeLiveRisk(livePositions ?? [], liveFunds)
        : null,
    [hasAccountSource, isExplore, livePositions, liveFunds],
  );

  // Daily P&L against the local references. Same banding as the margin gauge.
  const dayPnl = data?.dayPnl ?? 0;
  const targetUsage = pct(Math.max(dayPnl, 0), riskLimits.mtmTarget);
  const slUsage = pct(Math.abs(Math.min(dayPnl, 0)), Math.abs(riskLimits.mtmStoploss));

  // Overall level covers what the widget observes: the margin gauge and the
  // stop-loss bar. Progress towards a profit target is not a risk, so it is
  // excluded.
  const overallLevel = worstOf(data?.overallLevel ?? "green", levelForUsage(slUsage));

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Risk widget"
      data-tour-target="risk-panel"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <ShieldAlert size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Risk</span>
        {(isExplore || isPractice) && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            {isExplore ? "Sample" : "Practice"}
          </span>
        )}
        {!hasAccountSource && (
          <Badge
            variant="outline"
            className="text-xxs px-1.5 py-0 border-warning/30 text-warning bg-warning/10"
          >
            Broker required
          </Badge>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-2">
        {!data ? (
          <div className="rounded border border-border-default bg-surface-card px-3 py-4 text-center text-xs text-text-muted" role="status">
            Connect a broker to load risk metrics
          </div>
        ) : (
          <>
            {/* Overall status */}
            <StatusBanner level={overallLevel} timestamp={data.timestamp} />

            {/* Gauged metrics */}
            <div className="space-y-1.5" aria-label="Risk metrics">
              {data.metrics.map((m) => (
                <MetricCard key={m.id} metric={m} />
              ))}
            </div>

            {/* Informational values (no gauge/limit semantics — e.g. exposure). */}
            {data.infoStats && data.infoStats.length > 0 && (
              <div className="grid grid-cols-2 gap-1.5" aria-label="Risk info">
                {data.infoStats.map((s) => (
                  <div
                    key={s.label}
                    className="flex flex-col gap-0.5 bg-surface-card rounded-lg border border-border-default px-3 py-2"
                  >
                    <span className="text-xxs text-text-muted uppercase tracking-wide truncate">{s.label}</span>
                    <span className="text-sm font-bold font-mono tabular-nums text-text-primary">{s.value}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Daily MTM against the local references. */}
            <div
              className="bg-surface-card rounded-lg border border-border-default px-3 py-2.5 space-y-3"
              aria-label="Daily mark to market"
            >
              <div className="flex items-center justify-between">
                <span className="text-xxs text-text-muted uppercase tracking-wide">Daily P&amp;L</span>
                <span
                  className={cn(
                    "font-mono tabular-nums text-sm font-bold",
                    dayPnl >= 0 ? "text-profit" : "text-loss",
                  )}
                >
                  {fmtINR(dayPnl)}
                </span>
              </div>

              <ProgressRow
                label="Daily Target"
                usedLabel={fmtINR(Math.max(dayPnl, 0))}
                maxLabel={fmtINR(riskLimits.mtmTarget)}
                usagePct={targetUsage}
                icon={<Target size={9} />}
              />

              <ProgressRow
                label="Daily SL Exposure"
                usedLabel={fmtINR(Math.abs(Math.min(dayPnl, 0)))}
                maxLabel={fmtINR(Math.abs(riskLimits.mtmStoploss))}
                usagePct={slUsage}
                icon={<TrendingDown size={9} />}
              />

              <div className="border-t border-border-default pt-2 space-y-3">
                <UnavailableRow
                  label="Position lot usage"
                  detail="instrument lot metadata is not loaded"
                  icon={<Layers size={9} />}
                />

                <UnavailableRow
                  label="Order rate"
                  detail="rolling placement events are not tracked"
                  icon={<Zap size={9} />}
                />
              </div>
            </div>
          </>
        )}

        {/* Local references; these values are not backend or broker enforcement.
            They are the same settingsStore.riskLimits values MTM Monitor plots. */}
        <div className="bg-surface-card rounded-lg border border-border-default px-3 py-2">
          <p className="text-xxs text-text-disabled uppercase tracking-wider mb-1.5">Local Reference Values</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1">
            {[
              ["Lot reference", String(riskLimits.maxPositionLots)],
              ["MTM Target", fmtINR(riskLimits.mtmTarget)],
              ["MTM SL", fmtINR(riskLimits.mtmStoploss)],
              ["Order-rate reference", `${riskLimits.maxOrdersPerMinute}/min`],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between gap-2">
                <span className="text-xs text-text-muted truncate">{label}</span>
                <span className="font-mono tabular-nums text-xs text-text-secondary">{value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Honest note: greeks-derived metrics aren't wired for live data yet. */}
        {!isExplore && (
          <p className="text-xxs text-text-muted px-1 leading-snug">
            Net delta, net theta and max-loss need an option-greeks feed and are
            not shown here; only metrics derived from the current account scope appear above.
          </p>
        )}

        {/* Legend */}
        <div className="flex items-center gap-3 pt-1 px-1">
          {(["green", "amber", "red"] as TrafficLight[]).map((l) => {
            const labels: Record<TrafficLight, string> = {
              green: `Within limits (<${AMBER_AT}%)`,
              amber: `Approaching (${AMBER_AT}–${RED_AT}%)`,
              red: `Breached (≥${RED_AT}%)`,
            };
            return (
              <div key={l} className="flex items-center gap-1.5">
                <div className={cn("w-2 h-2 rounded-full shrink-0", BAR_CLASSES[l])} />
                <span className="text-xxs text-text-muted">{labels[l]}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default memo(RiskWidget);
