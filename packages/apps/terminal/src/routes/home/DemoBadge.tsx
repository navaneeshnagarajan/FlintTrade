/**
 * DemoBadge — thin route shim for backward compatibility.
 * Re-exports the canonical ProvenanceBadge from components/data.
 * Preserves the internal default testId="home-demo-badge" for callers that do not pass testId.
 * New code should import ProvenanceBadge directly.
 */

import { ProvenanceBadge, ProvenanceBadgeProps, ProvenanceKind } from "@/components/data/ProvenanceBadge";

export type { ProvenanceKind, ProvenanceBadgeProps };
export { ProvenanceBadge };

export function DemoBadge(props: ProvenanceBadgeProps) {
  const effectiveTestId = props.testId ?? "home-demo-badge";
  return <ProvenanceBadge {...props} testId={effectiveTestId} />;
}
