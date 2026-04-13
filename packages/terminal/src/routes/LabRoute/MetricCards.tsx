import { GlassCard } from "@/components/ui/GlassCard";
import { AnimatedCounter } from "@/components/magicui/animated-counter";

export interface AnimatedMetricCardProps {
  label: string;
  numericValue: number;
  displayValue: string;
  animate?: boolean;
  positive?: boolean | null;
  formatter?: (v: number) => string;
}

export function AnimatedMetricCard({
  label,
  numericValue,
  displayValue,
  animate = true,
  positive,
  formatter,
}: AnimatedMetricCardProps) {
  const valueColor =
    positive === true
      ? "text-profit"
      : positive === false
        ? "text-loss"
        : "text-text-primary";

  const isFiniteNumber =
    animate && isFinite(numericValue) && displayValue !== "—";

  return (
    <GlassCard className="p-4 text-center gap-1">
      <p className="text-xs text-text-muted mb-1 uppercase tracking-wider">
        {label}
      </p>
      <p className={`text-sm font-mono font-semibold ${valueColor}`}>
        {isFiniteNumber ? (
          <AnimatedCounter
            value={numericValue}
            formatter={formatter}
            duration={1.2}
            className={valueColor}
          />
        ) : (
          displayValue
        )}
      </p>
    </GlassCard>
  );
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
