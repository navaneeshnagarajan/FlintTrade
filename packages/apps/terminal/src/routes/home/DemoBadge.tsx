/**
 * DemoBadge — the shared "this card shows placeholder data, not live" affordance
 * for home Bento cards that have no live data source wired yet.
 *
 * Enforces the no-mock-data house rule ("fabricated data needs a visible Demo
 * affordance") consistently across the placeholder cards, mirroring the badge
 * MiniChartCard already uses. Absolutely positioned in the card's top-right
 * corner — BentoCard is `position: relative`, so it anchors to the card.
 */

export function DemoBadge({
  label = "Demo",
  title = "Placeholder data — not live",
  testId = "home-demo-badge",
}: {
  label?: string;
  title?: string;
  testId?: string;
}) {
  return (
    <span
      className="absolute right-2 top-2 z-10 rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide"
      style={{ background: "var(--color-surface-active)", color: "var(--color-text-muted)" }}
      data-testid={testId}
      role="status"
      title={title}
    >
      {label}
    </span>
  );
}
