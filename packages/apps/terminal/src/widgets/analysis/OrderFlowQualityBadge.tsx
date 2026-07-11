import { Badge } from "@/components/ui/badge";
import {
  getOrderFlowQualitySummary,
  type OrderFlowResponse,
} from "@/services/ftApi.data";

interface OrderFlowQualityBadgeProps {
  data: OrderFlowResponse;
}

const PROVENANCE_LABELS = {
  trade_tick: "trade ticks",
  cumulative_quote_delta: "cumulative quote deltas",
  synthetic: "synthetic data",
  mixed: "mixed sources",
  unknown: "unknown source",
} as const;

/** Compact quality disclosure shared by both order-flow visualisations. */
export function OrderFlowQualityBadge({ data }: OrderFlowQualityBadgeProps) {
  const { quality, provenance } = getOrderFlowQualitySummary(data);
  const provenanceLabel = PROVENANCE_LABELS[provenance];
  const presentation = quality === "exact"
    ? {
        label: provenance === "trade_tick" ? "Exact trades" : "Exact",
        className: "border-sky-500/40 text-sky-400 bg-sky-500/10",
      }
    : quality === "estimated"
      ? {
          label: provenance === "cumulative_quote_delta"
            ? "Estimated quote deltas"
            : "Estimated",
          className: "border-amber-500/40 text-amber-400 bg-amber-500/10",
        }
      : quality === "sample"
        ? {
            label: "Sample data",
            className: "border-amber-500/40 text-amber-400 bg-amber-500/10",
          }
        : {
            label: "Quality unknown",
            className: "border-border-default text-text-muted bg-surface-hover",
          };
  const qualityLabel = quality === "unknown"
    ? "Unknown"
    : `${quality[0].toUpperCase()}${quality.slice(1)}`;
  const accessibleLabel = `${qualityLabel} order flow quality from ${provenanceLabel}`;

  return (
    <Badge
      variant="outline"
      className={`h-5 shrink-0 whitespace-nowrap px-1.5 text-xs ${presentation.className}`}
      aria-label={accessibleLabel}
      title={accessibleLabel}
    >
      {presentation.label}
    </Badge>
  );
}
