# FT-DESK-ROUTES-001 — Desk route aliases, one Practice place path

Bookmark paths resolve to the desk that owns the content. Practice places
go through one admission path. A missing price is a plain sentence, not a
raw engine error.

## Locked behaviour

1. `/positions` resolves to `/trade#positions`. `/login` opens sign-in at `/welcome`.
2. `/holdings` resolves to `/invest#holdings`.
3. `/monitoring` resolves to `/settings#monitoring`.
4. `/schedules` resolves to `/automate#schedules`.
5. `/glossary` resolves to `/learn#glossary`.
6. Settings → Practice Mode does not place orders. The only Practice place
   is `POST /api/v1/orders/place` (mode guard → Laya, then the sandbox).
   Capital, status, and book reads may stay on the sandbox routes.
7. A Practice MARKET order uses one price rule. A live LTP
   (`price_basis: "ltp"` and a positive `price`) fills at that price.
   Otherwise the last stored close is the fill, labelled
   `Simulated at last close ₹812.40 (2 days old)` and tagged
   `price_source=last_close`. An unmarked number is not a fill. If neither
   a live price nor a stored close exists, the operator sees
   `No price for SBIN right now. Practice needs a live price or a recent close.`
   An option outside market hours is refused. Nothing fills at 0.00.
8. Laya readiness is unchanged. The Down sentence stays the one already
   shipped: `Laya is Down. New orders are paused until it's Ready. You can still close positions.`
9. The default Trade desk opens a bottom Positions, Orders, and Alerts book
   (about 28% of the workspace) and a **Positions and orders** control.
   `/trade#positions` and `/trade#orders` select the tab. The right-hand
   panel may still start collapsed.

## Acceptance

1. Opening any of the five bookmark paths lands on the destination above.
2. Settings → Practice Mode does not post a sandbox order.
3. A marked live LTP fills at that price. With no live price, the last
   stored close fills and is labelled. With neither, the plain no-price
   sentence is shown. The raw "no LTP was available" sentence does not
   reach the screen.
4. The bottom book and the control exist on the default Trade desk.
