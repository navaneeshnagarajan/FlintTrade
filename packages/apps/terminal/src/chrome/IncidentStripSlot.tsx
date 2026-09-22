/**
 * Slot under TopBar for the operator incident strip (#270).
 *
 * #270 owns Info / Degraded / Blocked and is not implemented here. Until
 * that strip lands, this slot hosts the existing Live-risk and
 * feed-disconnected banner so an incident can sit above Mode honesty
 * without replacing it. Explore and Practice leave the slot empty.
 */

import { primaryBannerCopy, type PrimaryBannerKind } from "@/lib/primaryBanner";

export default function IncidentStripSlot({ kind }: { kind: PrimaryBannerKind }) {
  if (kind !== "live_risk" && kind !== "feed_disconnected") return null;
  const text = primaryBannerCopy(kind);
  if (!text) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="incident-strip"
      data-slot="incident-strip"
      data-banner-kind={kind}
      className="shrink-0 border-b border-loss/20 bg-loss/10 px-4 py-1 text-center"
    >
      <p className="text-xs text-loss">{text}</p>
    </div>
  );
}
