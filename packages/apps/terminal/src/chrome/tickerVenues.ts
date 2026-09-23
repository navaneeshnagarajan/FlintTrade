/**
 * Venue badges for the dedicated ticker strip.
 *
 * Badges are derived from the symbols that actually feed the marquee.
 * A pinned MCX chip while NSE and BSE indices scroll is dishonest.
 */

export const TICKER_VENUES = ["NSE", "BSE", "NFO", "MCX"] as const;

export type TickerVenue = (typeof TICKER_VENUES)[number];

export interface TickerFeedSymbol {
  name: string;
  /** Public venue badge when the feed already knows it. */
  venue?: string | null;
  /** Feed exchange (NSE_INDEX, BSE_INDEX, NFO, MCX, …). */
  exchange?: string | null;
}

export interface TickerVenueBadge {
  venue: TickerVenue;
  open: boolean;
  /** Accessible session state, e.g. "NSE open". */
  label: string;
  title: string;
}

export type TickerVenueStrip =
  | { kind: "badges"; badges: TickerVenueBadge[] }
  | { kind: "unavailable" }
  | { kind: "empty" };

const EXCHANGE_TO_VENUE: Record<string, TickerVenue> = {
  NSE: "NSE",
  NSE_INDEX: "NSE",
  BSE: "BSE",
  BSE_INDEX: "BSE",
  NFO: "NFO",
  MCX: "MCX",
  MCX_INDEX: "MCX",
};

/** Display names on the default tape, used when a row has no venue field. */
const NAME_TO_VENUE: Record<string, TickerVenue> = {
  "NIFTY 50": "NSE",
  NIFTY: "NSE",
  "BANK NIFTY": "NSE",
  BANKNIFTY: "NSE",
  VIX: "NSE",
  "INDIA VIX": "NSE",
  INDIAVIX: "NSE",
  SENSEX: "BSE",
  GOLD: "MCX",
  SILVER: "MCX",
  CRUDEOIL: "MCX",
  "CRUDE OIL": "MCX",
  NATGAS: "MCX",
  NATURALGAS: "MCX",
  "NATURAL GAS": "MCX",
};

const SESSION_COPY: Record<TickerVenue, { hours: string; exchange: string }> = {
  NSE: { hours: "09:15–15:30 IST", exchange: "NSE" },
  BSE: { hours: "09:15–15:30 IST", exchange: "BSE" },
  NFO: { hours: "09:15–15:40 IST", exchange: "NFO" },
  MCX: { hours: "09:00–23:30 IST", exchange: "MCX" },
};

function asTickerVenue(raw: string | null | undefined): TickerVenue | null {
  if (!raw) return null;
  const key = raw.trim().toUpperCase();
  if ((TICKER_VENUES as readonly string[]).includes(key)) return key as TickerVenue;
  return EXCHANGE_TO_VENUE[key] ?? null;
}

/**
 * Resolve the public venue for one marquee symbol.
 *
 * Explicit venue or exchange wins. Known tape names cover rows that only
 * carry a display name. Anything else is unresolved and must not invent a venue.
 */
export function venueForTickerSymbol(symbol: TickerFeedSymbol): TickerVenue | null {
  const explicit = asTickerVenue(symbol.venue) ?? asTickerVenue(symbol.exchange);
  if (explicit) return explicit;

  const keyed = symbol.name.split(":");
  if (keyed.length === 2) {
    const fromKey = asTickerVenue(keyed[0]);
    if (fromKey) return fromKey;
  }

  return NAME_TO_VENUE[symbol.name.trim().toUpperCase()] ?? null;
}

/**
 * Badges for the venues that feed this marquee, in first-seen order.
 *
 * No symbols → omit the strip. Symbols with no resolvable venue → Unavailable.
 * Never fill the gap with a venue that is not on the tape.
 */
export function deriveTickerVenueStrip(
  symbols: readonly TickerFeedSymbol[],
  isOpen: (exchange: string) => boolean,
): TickerVenueStrip {
  if (symbols.length === 0) return { kind: "empty" };

  const seen = new Set<TickerVenue>();
  const order: TickerVenue[] = [];
  for (const symbol of symbols) {
    const venue = venueForTickerSymbol(symbol);
    if (!venue || seen.has(venue)) continue;
    seen.add(venue);
    order.push(venue);
  }

  if (order.length === 0) return { kind: "unavailable" };

  return {
    kind: "badges",
    badges: order.map((venue) => {
      const session = SESSION_COPY[venue];
      const open = isOpen(session.exchange);
      return {
        venue,
        open,
        label: open ? `${venue} open` : `${venue} closed`,
        title: open
          ? `${venue} session is open (${session.hours})`
          : `${venue} session is closed`,
      };
    }),
  };
}
