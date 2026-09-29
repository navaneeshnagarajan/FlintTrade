# FT-GTT-001 — GTT only as a reduce-only exit, linked to its position

## Context

GTT (Dhan **Forever Orders**) passes Laya admission and SafetySystem only
when it is placed. The broker fires it later without a FlintTrade check at
trigger time, including when Laya is Down, new orders are paused, or the kill
switch is on.

As an interim safeguard, session/auth PR #307 refuses `variety: "gtt"` on
every submit route. The Order Pad says **GTT orders aren't supported right
now.** in its tooltip and refuses with **Not placed. GTT orders aren't
supported right now.** This tracking item defines the safe path to bring GTT
back.

## Broker facts

- Dhan v2 Forever Orders support create, modify, cancel, and list for SINGLE
  or OCO orders. Creating one accepts only product type CNC or MTF.
- The Dhan list endpoint can return NSE_FNO and MARGIN/INTRADAY GTTs placed
  in the Dhan app.
- Neither Dhan nor Kotak Neo provides a reduce-only or exit-only flag.
- Kotak Neo's Trade API has no GTT; its validity options are DAY and IOC.
  App-placed Neo GTTs cannot be listed.
- Sources: [Dhan Forever Orders](https://dhanhq.co/docs/v2/forever/) and
  [Kotak Neo Trade API order validity](https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/functions/orders/place_order.md).

## Scope

1. **Reduce-only placement.** GTT is allowed only as a reduce-only exit (a
   stop or target) on an open position, and only where the broker API
   supports it (Dhan CNC/MTF in the supported broker API). It uses the same server-decided
   reduce-only proof as closes, and its quantity cannot exceed the open
   quantity.
2. **Position link.** When the position's open quantity drops below the GTT
   quantity because of a manual close, partial close, square-off, or expiry,
   FlintTrade cancels or shrinks the GTT at the broker. A stop/target pair is
   OCO: when one fills, the other is cancelled. If a broker cancel fails, the
   row shows the GTT as still live and new GTT placement for that position is
   refused.
3. **Startup reconciliation.** Before any order is accepted, list pending
   GTTs across every segment, not only CNC, and match them against positions.
   Any GTT larger than its position or without a position gets its own row
   tagged **Unexpected**, with the tooltip **Placed outside FlintTrade. It
   could open a new position if it fires.** Its Cancel action cancels it at
   the broker. This also catches entry GTTs placed before the interim
   refusal.
4. **Neo visibility.** Under Positions, show once per session, and only for
   the Neo broker, the quiet line **GTT orders placed in the Neo app aren't
   visible here.**
5. **Route coverage.** `test_order_submit_routes.py` covers
   `variety: "gtt"`, including bracket/cover-order legs if they are ever
   sent.

## Product copy

- The Order Pad offers GTT only on an open position, as **Stop** or
  **Target**.
- With no position, GTT is disabled with the tooltip **GTT is for stops and
  targets on an open position.**
- Refusal: **Not placed. GTT orders can only exit an open position, up to its
  open quantity.**
- Row tags: **GTT stop** and **GTT target**.
- Row tooltip: **Your broker fires this later. It can only reduce this
  position.**

## Out of scope

F&O stops held by FlintTrade itself, which would fire only while FlintTrade
is running, are parked for a separate specification.

## Pass bar

Test with a stub broker:

- A GTT with no position is refused.
- A GTT above the open quantity is refused.
- A manual close or partial close cancels or shrinks the GTT.
- When a stop or target fills, the other is cancelled.
- A failed cancel shows the GTT as still live.
- Startup reconciliation flags an NSE_FNO MARGIN app-placed GTT as
  **Unexpected**.
- The route-walk test covers `variety: "gtt"`.

Blocked on #307 merging.
