import { useAtomValue } from "jotai";
import { Link } from "react-router";
import { indicesSummaryAtom } from "@/atoms/marketAtoms";
import FeedFreshnessChip from "@/components/FeedFreshnessChip";
import { useFeedFreshness } from "@/hooks/useFeedFreshness";
import { useOperatorMarketSession } from "@/hooks/useOperatorMarketSession";
import { isMarketHours, operatorMarketLabel } from "@/lib/market";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import TickerMarquee, { type TickerMode } from "./TickerMarquee";
import { deriveTickerVenueStrip, type TickerVenueBadge } from "./tickerVenues";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

function VenueBadge({ badge }: { badge: TickerVenueBadge }) {
  return (
    <span
      className={`text-xxs font-mono uppercase tracking-wider px-1 py-0.5 rounded border ${
        badge.open
          ? "text-amber-400 border-amber-500/40 bg-amber-500/10"
          : "text-text-disabled border-border-default"
      }`}
      title={badge.title}
      aria-label={badge.label}
    >
      {badge.venue}
    </span>
  );
}

export interface TickerBarProps {
  /** Display mode for the dedicated scrolling strip. Default: marquee. */
  mode?: TickerMode;
}

/**
 * TickerBar — the single dedicated scrolling ticker strip under TopBar
 * (FT-UX-002). Reads live prices from indicesSummaryAtom.
 *
 * NSE/BSE indices and MCX commodities share one marquee. Pinned venue
 * badges are derived from the symbols on that tape (NSE, BSE, MCX, and NFO
 * when an F&O symbol feeds). A venue that is not on the tape is omitted.
 */
export default function TickerBar({ mode = "marquee" }: TickerBarProps) {
  const indices = useAtomValue(indicesSummaryAtom);
  const reducedMotion = usePrefersReducedMotion();
  const session = useOperatorMarketSession();
  const deskMode = useModeStore((s) => s.mode);
  const liveFeedConnected = useConnectionStore((s) => s.wsConnected);
  const freshness = useFeedFreshness();
  // A disconnected socket is when the REST fallback can still be fresh.
  // "Last close" waits until neither source has fresh quotes, and an
  // unconfirmed session is never labelled as closed.
  const restQuotesFresh = freshness.state === "delayed";
  const socketQuotesFresh = liveFeedConnected && freshness.state !== "stale";
  const quotesFresh = freshness.state === "live" || restQuotesFresh || socketQuotesFresh;
  const showLastClose =
    deskMode === "practice" && session.status !== "unavailable" && !quotesFresh;
  const marketLabel = operatorMarketLabel(session);
  const sharedClosed = session.status === "closed";
  const venueStrip = deriveTickerVenueStrip(
    indices,
    (exchange) => isMarketHours(exchange),
    sharedClosed ? marketLabel : undefined,
  );

  return (
    <div
      className="bg-surface-base border-b border-border-default flex flex-col shrink-0"
      role="region"
      aria-label="Market indices"
      data-testid="ticker-strip"
    >
      <div className="h-7 flex items-center overflow-hidden">
        <div className="flex items-center px-1.5 shrink-0 border-r border-border-default h-full">
          <FeedFreshnessChip />
        </div>

        {venueStrip.kind !== "empty" && (
          <div
            className="flex items-center gap-1.5 px-2 shrink-0 border-r border-border-default h-full"
            aria-label="Venue badges"
            data-testid="ticker-venue-badges"
            data-venues={
              venueStrip.kind === "badges"
                ? venueStrip.badges.map((badge) => badge.venue).join(",")
                : "unavailable"
            }
          >
            {venueStrip.kind === "unavailable" ? (
              <span
                className="text-xxs font-mono uppercase tracking-wider px-1 py-0.5 rounded border text-text-disabled border-border-default"
                aria-label="Venues unavailable"
              >
                Unavailable
              </span>
            ) : (
              venueStrip.badges.map((badge) => (
                <VenueBadge key={badge.venue} badge={badge} />
              ))
            )}
          </div>
        )}

        {mode === "marquee" && reducedMotion && (
          <span
            className="text-xxs text-text-muted px-2 shrink-0 select-none"
            data-testid="ticker-reduced-motion"
            title="Scrolling is paused because reduced motion is on"
          >
            Reduced motion
          </span>
        )}

        <TickerMarquee
          mode={mode}
          className="flex-1 min-w-0 h-7"
          labelled={false}
          announce={false}
        />

        {/* Accessibility: one polite live region summarises all index prices for
            screen readers (Issue #50). The nested marquee stays silent so ticks
            do not double-announce. */}
        <span
          className="sr-only"
          aria-live="polite"
          aria-atomic="true"
        >
          {indices
            .filter((i) => i.data?.ltp != null && (i.data.ltp ?? 0) > 0)
            .map((i) => `${i.name} ${i.data!.ltp}`)
            .join(", ")}
        </span>
      </div>
      {showLastClose ? (
        <p
          data-testid="ticker-last-close"
          className="px-2 pb-1 text-xs text-text-secondary"
        >
          Last close prices ·{" "}
          <Link to="/settings#brokers" className="text-text-secondary underline-offset-2 hover:underline">
            Connect a broker for live prices →
          </Link>
        </p>
      ) : null}
    </div>
  );
}
