# FT-SETUP-COPY-001 — Scrub calendar-day operator copy from Setup

Operator-visible Setup, Mode Select, Broker Connect, and the operator
guide used a weekday pack name as a product path. Mode chrome is
**Practice**, **Connected (read)**, and **Live**. **API smoke** is not a
Mode chip or Mode bar label. It may appear only in broker-connect helper
copy for a non-funded read. Wizard flow and broker behaviour are unchanged.

The quotes below are the strings this tip replaced.

## Locked behaviour

1. Mode chips and the Mode bar use **Practice**, **Connected (read)**,
   and **Live**. **API smoke** is not a Mode chip or Mode bar label, and
   it does not rename Live or Connected (read). It may appear only in
   broker-connect helper copy for a non-funded read. A calendar day or
   weekday pack name is not a product path in UI strings.
2. Code identifiers and acceptance-doc IDs may keep internal tracking
   names in developer docs and in source that is not shown as operator
   chrome. Operator strings and `docs/USER_GUIDE.md` operator copy must
   not advertise those names.
3. Setup wizard complexity (step count, layout, which connect action is
   primary) is a separate UX call (**FT-SETUP-FLOW-001**). This finding
   is copy honesty only.

## Verified operator surfaces

Quotes below are the operator strings this tip replaced.

### Mode Select

`packages/apps/terminal/src/routes/ModeSelectRoute.tsx` — Practice card
`brokerNote`, rendered on the mode card:

`No broker needed · primary Monday Practice path`

The Example and Live notes on the same screen already use product
language (`No broker needed`, `Broker required · PIN and authenticator
required`).

### Setup connection step

- `You do not need a broker for Monday Practice.`

- `Settings fallback only — not the Monday primary connect path.`

- `Monday primary broker connect: native Dhan + Kotak Neo.`

`packages/apps/terminal/src/routes/setup/ConnectionStep.tsx` renders
these operator sentences:

The same step already uses honest product language beside those leaks:
`Connected (read) / API smoke only — never placeable Live orders` and
`Live read only until funded unlock.`

### Broker Connect (Setup and Settings)

- Strong copy: `Monday path is native Dhan + Kotak Neo Connected (read).`


`packages/apps/terminal/src/components/account/BrokerConnect.tsx` is the
shared Brokers surface (setup direct connect, and Settings → Brokers via
`packages/apps/terminal/src/tools/Settings/BrokersSection.tsx`). The
warning banner says:

The rest of that paragraph already uses **Connected (read)**, **API
smoke**, and fail-closed Live place.

### Operator guide

`docs/USER_GUIDE.md` is operator copy. It advertises internal tracking
IDs that contain the weekday pack name:

- `(FT-MONDAY-002)` beside native Dhan + Kotak Neo Connected (read) /
  API smoke (broker setup and the native-read section).
- `(FT-MONDAY-001)` beside Practice fills and the Learn →
  Practice Trading fallback.
- `(FT-MONDAY-003)` beside AI Suggest labelling, Chat live-read context,
  and the Settings AI note.

The surrounding sentences are already product language (Practice,
Connected (read), API smoke, `Live read only until funded unlock.`).
The follow-up removes the tracking IDs from the operator guide. The
acceptance docs `docs/acceptance/FT-MONDAY-001.md` (if present),
`FT-MONDAY-002.md`, and `FT-MONDAY-003.md` may keep those IDs.

The same operator-copy rule covers these setup pages, which cite the
same tracking IDs in running prose:

- `docs/setup/QUICKSTART.md` (broker-access section)
- `docs/setup/static-ip-setup.md` (native Dhan + Kotak Neo section)
- `docs/COMPATIBILITY.md` (Kotak Neo catalogue paragraph)

Contributor docs may keep the IDs: `docs/ARCHITECTURE.md`,
`docs/DEVELOPER_GUIDE.md`, `docs/INVENTORY.md`, and the maintainer index
in `docs/README.md`.

### Operator-reachable error text

The former “market feed is not wired” operator error is retired. Kotak Neo now
has a locally tested v3 async market/order-feed lifecycle. This does not change the
honest product boundary: the recorded broker-account smoke remains non-funded
REST reads, and live-account/market-hours streaming, funded order safety, Live
catalogue promotion, and cross-platform proof are still outstanding.

`packages/integrations/gateway/src/flinttrade_gateway/monday_read_smoke.py`
raises `ValueError` with `Monday read-smoke is Dhan + Neo only` and
`Monday AI reads are Dhan + Neo only`. Callers found in-tree are tests.
Treat either message as in scope if a route shows `str(exc)` to an
operator; the function names may stay.

## May keep internal names

These are not operator chrome. Do not rename them as part of this
finding:

- Identifiers such as `isMondayReadBroker` and `mondayReadChrome` in
  `packages/apps/terminal/src/lib/connectedReadChrome.ts`,
  `nativeMonday`, `MONDAY_READ_BROKERS`, and `run_monday_read_smoke`.
- Developer comments, including the file headers on `ConnectionStep.tsx`
  and `SetupAccountRoute.tsx`, the comment in
  `ModeSelectRoute.test.tsx`, and the `read_smoke_ok` notes in
  `types/broker.ts` and `services/ftApi.native.ts`. Those notes are not
  rendered.
- Acceptance-doc IDs `FT-MONDAY-001`, `FT-MONDAY-002`, and
  `FT-MONDAY-003` inside `docs/acceptance/`.
- Account switcher and incident chrome. `AccountSwitcher` passes the
  internal flag through, and the painted status is already product
  language (`Connected (read)`, `Connected`, `Unavailable`, `Degraded`).

## Out of scope

- Setup wizard structure, step order, or which control is the primary
  continue action (**FT-SETUP-FLOW-001**).
- Exchange-calendar copy that states a real session fact, including
  welcome copy that markets resume on a weekday at 09:15, seasonality
  weekday columns, and IST weekday arithmetic.
- Order gating, native HTTP freeze, connectability, and funded Live
  unlock. Those stay on their existing acceptance tips.
- Renaming modules or tests whose only “leak” is an identifier.

## Acceptance

The product fix is done when all of the following hold:

## Status

Done. Mode chrome is Practice, Connected (read), and Live. API smoke
stays in broker-connect helper copy for a non-funded read, and it is
not a Mode chip or Mode bar label. Internal identifiers and
acceptance-doc IDs are unchanged.
