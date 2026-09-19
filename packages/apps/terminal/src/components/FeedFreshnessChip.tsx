/**
 * Source chip — Live · Delayed · Sample, or muted Stale/Unknown + age.
 * Feed provenance, not execution mode (FT-CORE-002).
 */

import { useFeedFreshness } from "@/hooks/useFeedFreshness";
import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  live: "text-profit bg-profit/10 border-profit/30",
  delayed: "text-warning bg-warning/10 border-warning/30",
  sample: "text-text-secondary bg-surface-hover border-border-default",
  stale: "text-text-muted bg-surface-hover border-border-default",
  unknown: "text-text-muted bg-surface-hover border-border-default",
};

export default function FeedFreshnessChip({ className }: { className?: string }) {
  const freshness = useFeedFreshness();
  const ageHint = freshness.ageLabel ? `, ${freshness.ageLabel} old` : "";

  return (
    <span
      data-testid="feed-freshness-chip"
      data-state={freshness.state}
      aria-label={`Feed source: ${freshness.label}${ageHint}`}
      title={`Feed source · ${freshness.chipText} (not execution mode)`}
      className={cn(
        "inline-flex items-center px-1.5 py-0.5 text-xxs font-medium border rounded shrink-0 whitespace-nowrap tabular-nums",
        TONE[freshness.state],
        className,
      )}
    >
      {freshness.chipText}
    </span>
  );
}
