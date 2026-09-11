import { GlassCard } from "@/components/ui/GlassCard";

export interface AnimatedMetricCardProps {
  label: string;
  numericValue: number;
  displayValue: string;
  animate?: boolean;
  positive?: boolean | null;
  formatter?: (v: number) => string;
}

/**
 * Lab headline metric. Always paints ``displayValue`` once.
 *
 * A previous count-up through ``AnimatedCounter`` left a leftover ``0.00``
 * (the spring start) beside an ``sr-only`` final figure — Sharpe read as
 * ``0.00 1.84``. The unused numeric/animate/formatter props stay on the
 * signature so existing Lab call sites do not churn.
 */
export function AnimatedMetricCard({
  label,
  displayValue,
  positive,
}: AnimatedMetricCardProps) {
  return <MetricCard label={label} value={displayValue} positive={positive} />;
}

export interface MetricCardProps {
  label: string;
  value: string;
  positive?: boolean | null;
}

export function MetricCard({ label, value, positive }: MetricCardProps) {
  const valueColor =
    positive === true
      ? "text-profit"
      : positive === false
        ? "text-loss"
        : "text-text-primary";
  return (
    <GlassCard className="p-4 text-center gap-1">
      <p className="text-xs text-text-muted mb-1 uppercase tracking-wider">
        {label}
      </p>
      <p className={`text-sm font-mono font-semibold ${valueColor}`}>
        {value}
      </p>
    </GlassCard>
  );
}
