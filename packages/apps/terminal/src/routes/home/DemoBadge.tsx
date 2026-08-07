/**
 * ProvenanceBadge — canonical static provenance labels for home Bento cards.
 *
 * Allowed labels: Sample | Unavailable | Live | Stale.
 * Static presentation only — no `role="status"` and no `aria-live` (no noisy
 * announcements). Replaces the old user-visible "Demo" affordance.
 *
 * Enforces the no-mock-data house rule consistently across placeholder cards.
 * Absolutely positioned in the card's top-right corner — BentoCard is
 * `position: relative`, so it anchors to the card.
 *
 * `DemoBadge` remains a thin alias so existing internal imports keep working
 * without a mass rename of file paths.
 */

export type ProvenanceKind = "Sample" | "Unavailable" | "Live" | "Stale";

const DEFAULT_TITLES: Record<ProvenanceKind, string> = {
  Sample: "Sample data — not live",
  Unavailable: "Data unavailable",
  Live: "Live data",
  Stale: "Stale data — may be out of date",
};

export interface ProvenanceBadgeProps {
  label?: ProvenanceKind;
  title?: string;
  testId?: string;
}

export function ProvenanceBadge({
  label = "Sample",
  title,
  testId = "home-demo-badge",
}: ProvenanceBadgeProps) {
  return (
    <span
      className="absolute right-2 top-2 z-10 rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide"
      style={{ background: "var(--color-surface-active)", color: "var(--color-text-muted)" }}
      data-testid={testId}
      data-provenance={label}
      title={title ?? DEFAULT_TITLES[label]}
    >
      {label}
    </span>
  );
}

/** Internal alias — prefer {@link ProvenanceBadge} for new call sites. */
export function DemoBadge(props: ProvenanceBadgeProps) {
  return <ProvenanceBadge {...props} />;
}
