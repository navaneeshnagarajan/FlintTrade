# FT-CORE-TICKER-001 — Ticker venue badges

Tracking lock for the dedicated ticker strip. UX has confirmed these
bars. The product tip may proceed. This note does not change ticker
behaviour.

## Finding

Badges must match venues that feed the marquee (NSE/BSE/MCX; NFO when
F&O symbols feed). MCX-only while equity indices scroll is dishonest.

## Locked product bars

- Badges must match venues that feed the marquee (NSE/BSE/MCX; NFO when
  F&O symbols feed). MCX-only while equity indices scroll is dishonest.
- Continuous marquee when motion is allowed.
- With `prefers-reduced-motion: reduce`, a freeze is OK if labeled
  (e.g. “Reduced motion”). Empty/unavailable venues → omit badge or
  Unavailable; never a fake venue strip.
- The Sample/Explore freshness chip may stay. It must not hide venue
  honesty.

## Tester evidence (hypothesis)

On an Explore strip, the Sample freshness chip and an MCX-only pinned
badge were visible while NIFTY, SENSEX, and BANK NIFTY scrolled in the
same marquee. Scroll was continuous when reduced motion was off.

## Acceptance

1. Badges must match venues that feed the marquee (NSE/BSE/MCX; NFO when
   F&O symbols feed). MCX-only while equity indices scroll is dishonest.
2. Continuous marquee when motion is allowed.
3. With `prefers-reduced-motion: reduce`, a freeze is OK if labeled
   (e.g. “Reduced motion”). Empty/unavailable venues → omit badge or
   Unavailable; never a fake venue strip.
4. The Sample/Explore freshness chip may stay. It must not hide venue
   honesty.
5. British English in operator copy.

## Out of scope

- Removing or replacing the Sample/Explore freshness chip.
- Order placement, broker connect, or feed transport.
- Any ticker behaviour change in this tracking commit.
