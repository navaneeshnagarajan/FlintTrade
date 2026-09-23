# FT-CORE-TICKER-001 — Ticker venue badges

UX has confirmed these bars, and the product tip implements them on the
dedicated ticker strip. Pinned venue badges follow the marquee. A
reduced-motion freeze is labelled **Reduced motion**.

## Finding

Badges must match venues that feed the marquee (NSE/BSE/MCX; NFO when
F&O symbols feed). MCX-only while equity indices scroll is dishonest.

## Locked product bars

- Badges must match venues that feed the marquee (NSE/BSE/MCX; NFO when
  F&O symbols feed). MCX-only while equity indices scroll is dishonest.
- Continuous marquee when motion is allowed.
- With `prefers-reduced-motion: reduce`, a freeze is OK if labelled
  (e.g. “Reduced motion”). Empty/unavailable venues → omit badge or
  Unavailable; never a fake venue strip.
- The Sample/Explore freshness chip may stay. It must not hide venue
  honesty.

## Observed strip

On an Explore strip, the Sample freshness chip and an MCX-only pinned
badge were visible while NIFTY, SENSEX, and BANK NIFTY scrolled in the
same marquee. Scroll was continuous when reduced motion was off.

## Acceptance

1. Badges must match venues that feed the marquee (NSE/BSE/MCX; NFO when
   F&O symbols feed). MCX-only while equity indices scroll is dishonest.
2. Continuous marquee when motion is allowed.
3. With `prefers-reduced-motion: reduce`, a freeze is OK if labelled
   (e.g. “Reduced motion”). Empty/unavailable venues → omit badge or
   Unavailable; never a fake venue strip.
4. The Sample/Explore freshness chip may stay. It must not hide venue
   honesty.
5. British English in operator copy.

## Out of scope

- Removing or replacing the Sample/Explore freshness chip.
- Order placement, broker connect, or feed transport.
