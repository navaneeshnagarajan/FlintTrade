# Scrub calendar-day operator copy from Setup

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
2. Operator strings and `docs/USER_GUIDE.md` use product language.
   A weekday name stays only where it names a real calendar day.
3. Setup wizard complexity (step count, layout, which connect action is
   primary) is a separate UX call. This finding
   is copy honesty only.

## Verified operator surfaces

Quotes below are the operator strings this tip replaced.

### Mode Select

`packages/apps/terminal/src/routes/ModeSelectRoute.tsx` — Practice card
`brokerNote`, rendered on the mode card:

`No broker needed · primary Practice path`

The Example and Live notes on the same screen already use product
language (`No broker needed`, `Broker required · PIN and authenticator
required`).

### Setup connection step

- `You do not need a broker for Practice.`

- `Settings fallback only — not the primary connect path.`

- `Primary broker connect: native Dhan + Kotak Neo.`

`packages/apps/terminal/src/routes/setup/ConnectionStep.tsx` renders
these operator sentences:

The same step already uses honest product language beside those leaks:
`Connected (read) / API smoke only — never placeable Live orders` and
`Live read only until funded unlock.`

### Broker Connect (Setup and Settings)

- Strong copy: `The path is native Dhan + Kotak Neo Connected (read).`


`packages/apps/terminal/src/components/account/BrokerConnect.tsx` is the
shared Brokers surface (setup direct connect, and Settings → Brokers via
`packages/apps/terminal/src/tools/Settings/BrokersSection.tsx`). The
warning banner says:

The rest of that paragraph already uses **Connected (read)**, **API
smoke**, and fail-closed Live place.

### Operator guide

`docs/USER_GUIDE.md` is operator copy. It describes the same behaviour
in product language:

- Native Dhan + Kotak Neo Connected (read) / API smoke (broker setup
  and the native-read section).
- Practice fills and the Learn → Practice Trading fallback.
- AI Suggest labelling, Chat live-read context, and the Settings AI note.

The surrounding sentences use Practice, Connected (read), API smoke,
and `Live read only until funded unlock.` The acceptance notes are
`docs/acceptance/native-connected-read.md` and
`docs/acceptance/ai-live-reads.md`.

The same operator-copy rule covers these setup pages:

- `docs/setup/QUICKSTART.md` (broker-access section)
- `docs/setup/static-ip-setup.md` (native Dhan + Kotak Neo section)
- `docs/COMPATIBILITY.md` (Kotak Neo catalogue paragraph)

Contributor docs use the same product language: `docs/ARCHITECTURE.md`,
`docs/DEVELOPER_GUIDE.md`, `docs/INVENTORY.md`, and the maintainer index
in `docs/README.md`.

### Operator-reachable error text

The former “market feed is not wired” operator error is retired. Kotak Neo now
has a locally tested v3 async market/order-feed lifecycle. This does not change the
honest product boundary: the recorded broker-account smoke remains non-funded
REST reads, and live-account/market-hours streaming, funded order safety, Live
catalogue promotion, and cross-platform proof are still outstanding.

`packages/integrations/gateway/src/flinttrade_gateway/connected_read_smoke.py`
raises `ValueError` with `Connected (read) / API smoke is Dhan + Neo only` and
`Connected (read) reads are Dhan + Neo only`. Callers found in-tree are tests.
Treat either message as in scope if a route shows `str(exc)` to an
operator; the function names may stay.

## Identifiers

These names are not operator chrome. The painted status is already
product language (`Connected (read)`, `Connected`, `Unavailable`,
`Degraded`):

- `isConnectedReadBroker` and `connectedReadChrome` in
  `packages/apps/terminal/src/lib/connectedReadChrome.ts`
- `nativeConnectedRead`, `CONNECTED_READ_BROKERS`, and
  `run_connected_read_smoke`
- `read_smoke_ok` notes in `types/broker.ts` and
  `services/ftApi.native.ts`, which are not rendered
- Account switcher and incident chrome, which pass the connected-read
  flag through and paint the product status

## Out of scope

- Setup wizard structure, step order, or which control is the primary
  continue action.
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
not a Mode chip or Mode bar label. Operator copy does not name a
weekday as a product path.
