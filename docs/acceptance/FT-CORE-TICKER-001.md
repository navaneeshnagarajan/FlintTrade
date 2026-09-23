# FT-CORE-TICKER-001 — Ticker venue badges

Tracking lock for the dedicated ticker strip. This note does not change
ticker behaviour. The product tip follows after UX confirms the bars
below.

## Finding

Ticker exchange chrome must name the venues the strip is actually
showing. A single pinned MCX badge is not an honest label when the same
marquee also carries NSE, BSE, or NFO symbols.

## Locked product bars

- Ticker exchange chrome must reflect the venues this install actually
  feeds. If the marquee includes NSE/BSE (or NFO) symbols, those venues
  must not be represented by an MCX-only pinned badge.
- Continuous marquee when multiple symbols are present (unless the
  operator has reduced-motion on).
- With `prefers-reduced-motion: reduce`, do not leave a frozen/static
  strip that looks broken — use a stepping/paged or otherwise honest
  non-animated presentation.
- The Sample/Explore freshness chip may stay. It must not hide venue
  honesty.

## Tester evidence (hypothesis)

On an Explore strip, the Sample freshness chip and an MCX-only pinned
badge were visible while NIFTY, SENSEX, and BANK NIFTY scrolled in the
same marquee. Scroll was continuous when reduced motion was off.

## Acceptance

1. When the marquee includes NSE, BSE, or NFO symbols, pinned exchange
   chrome names those venues. An MCX-only badge does not stand in for
   them.
2. With more than one symbol and reduced motion off, the strip keeps a
   continuous marquee.
3. With `prefers-reduced-motion: reduce`, the strip uses a stepping,
   paged, or other honest non-animated presentation. It does not sit as
   a frozen marquee that looks broken.
4. The Sample/Explore freshness chip may remain, and venue chrome stays
   visible beside it.
5. British English in operator copy.

## Out of scope

- Removing or replacing the Sample/Explore freshness chip.
- Order placement, broker connect, or feed transport.
- Any ticker behaviour change in this tracking commit.
