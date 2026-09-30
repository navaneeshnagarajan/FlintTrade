# FlintTrade API Reference

FlintTrade exposes two HTTP surfaces and one WebSocket channel.

| Surface | Base URL (production) | Base URL (Vite dev proxy) | Purpose |
|---|---|---|---|
| OpenAlgo passthrough | `http://<openalgo-host>:5000/api/v1/` | `/api/v1/` | Broker-facing endpoints — orders, positions, quotes, history, etc. |
| FlintTrade backend | `http://<flinttrade-host>:5100/v1/` and `http://<flinttrade-host>:5100/api/v1/` | `/ft-api/v1/` and `/ft-api/api/v1/` | FlintTrade-specific endpoints. Blueprints mount at `/v1` *or* `/api/v1` — match the prefix the frontend uses. Operations, native brokers, and orders live under `/api/v1`. |
| WebSocket | `ws://<openalgo-host>:8765` | `/ws` | Streaming market data (LTP, Quote, Depth). |

> **WSGI prefix strip.** Blueprints mount at `/v1/*` *or* `/api/v1/*` —
> match the prefix the frontend uses. The Vite dev proxy and a production
> reverse proxy add `/ft-api` before forwarding, and WSGI middleware strips
> that prefix before URL dispatch. A client path `/ft-api/v1/X` is `/v1/X`
> inside the backend; `/ft-api/api/v1/X` is `/api/v1/X`. Never double-prefix.

---

## 1. OpenAlgo passthrough (`/api/v1/*`)

Source of truth: `packages/core/core/src/flinttrade_core/openalgo_client.py`. All endpoints are
POST unless explicitly marked **GET**.

### Orders

| Endpoint | Purpose |
|---|---|
| `placeorder` | Place a standard order (MARKET / LIMIT / SL / SL-M). Omits undeclared `market_protection` — v2.0.2.2 dropped that field; FlintTrade refuses `market_protection=true` rather than silently dropping it. |
| `placesmartorder` | Conditional / multi-leg / target-position smart order. Same `market_protection` rule as `placeorder`. |
| `modifyorder` | Modify price / quantity / order type of a pending order. `trigger_price` stays explicit. Full-replacement brokers receive `disclosed_quantity` (recovered from the live order when omitted); partial-modify adapters omit the request model's default disclosure when the caller did not supply it. Stop-loss modify requires a positive `trigger_price`. |
| `cancelorder` | Cancel a single pending order by ID. |
| `cancelallorder` | Cancel every pending order for a strategy. |
| `closeposition` | Square off every position for a strategy. |
| `openposition` | Open a position with auto-computed quantity from target exposure. |
| `orderstatus` | Look up the status of a specific order. |
| `optionsorder` | Place a single-leg options order. |
| `optionsmultiorder` | Place a multi-leg options strategy (spread / straddle / strangle / butterfly). |
| `basketorder` | Submit a basket of orders atomically. |
| `splitorder` | Split a large order into smaller child orders. |

### GTT (Good Till Triggered) — added in OpenAlgo 2.0.0.9

GTT triggers sit on the broker until the LTP crosses the trigger price,
at which point the broker emits a real order. The schema rejects MIS
(intraday) product because triggers can sit for days. Live broker support
upstream: Dhan + Zerodha. Other brokers respond with a clean 501 on the
OpenAlgo service itself. FlintTrade does not propagate that 501 through
`/orders/gtt-*` on Live.

| Endpoint | Purpose |
|---|---|
| `placegttorder` | Place a single-leg (SINGLE) or two-leg (OCO) GTT trigger. |
| `modifygttorder` | Full-replacement modify of an active trigger by `trigger_id`. |
| `cancelgttorder` | Cancel an active trigger by `trigger_id`. |
| `gttorderbook` | List all live (non-terminal) GTT triggers for the user. |

FlintTrade still registers `/api/v1/orders/gtt-{place,modify,cancel}` so
the mode gate runs, but those verbs are **not** gated like regular
`/orders/place`. A sample-data session (claim `explore`) returns 403 `mode_blocked`. Practice returns a
rejected GTT — the sandbox does not simulate price triggers. Live requires
the unlocked JWT, then `gtt-*` returns HTTP 501 (they do not call
`gate_order` → `BrokerRouter`, and they do not forward an upstream
OpenAlgo 501). A body with `"variety": "gtt"` (any case or separator
spelling) on place, routed place, exit-all, or a bracket is HTTP 422
`gtt_unsupported`: `Not placed. GTT orders aren't supported right now.`
That refusal is before Laya, SafetySystem, and any broker call. No submit
route reaches a broker forever or super-order endpoint. The Kotak Neo
adapter refuses a `gtt` place with that same message.
`POST /api/v1/orders/forever` does not place one.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/orders/forever` | Does not place and does not call a broker. Requires a live, PIN-unlocked session: HTTP 401 without a JWT, HTTP 403 for any other live-guard failure. A body that fails the forever contract is HTTP 400. A body that fails order validation is HTTP 400 `Order validation failed`. A valid body is HTTP 501 `Orders are placed through /api/v1/orders/place.` |
| `PUT /api/v1/orders/forever/<order_id>` | Modify a resting forever order (`changes` object). Gated `modify_forever`. |
| `DELETE /api/v1/orders/forever/<order_id>` | Cancel a resting forever order. Gated `cancel_forever`. |
| `GET /api/v1/orders/forever` | List resting forever orders (`?broker=` / `?account_id=`). |

### Accounts

| Endpoint | Purpose |
|---|---|
| `funds` | Available margin, used margin, cash balance. |
| `orderbook` | All orders for the trading day. |
| `tradebook` | All executed trades. |
| `positionbook` | Open positions (intraday and overnight). |
| `holdings` | Long-term holdings (CNC / delivery). |
| `margin` | Pre-trade margin estimate for a list of positions. |
| `ping` | OpenAlgo health check (POST). Distinct from FlintTrade `GET /api/v1/ping`. |
| `analyzer` | Read sandbox / analyzer mode status. |
| `analyzer/toggle` | Toggle sandbox / live mode. |

### Data

| Endpoint | Purpose |
|---|---|
| `quotes` | Single-symbol quote (LTP, OHLC, OI). Current ticker polling uses this POST — the terminal `getTicker` helper is an alias, not a separate route. |
| `multiquotes` | Quote for a list of symbols in one request. |
| `depth` | Level-2 market depth from brokers with a wired FlintTrade snapshot read; documented feed-only depth is not exposed here until the adapter bridge is wired. |
| `history` | Historical OHLCV bars. |
| `optionchain` | Full option chain. FlintTrade sends `underlying`, `exchange`, and `expiry_date` (OpenAlgo `DDMMMYY`, e.g. `26MAR26`). FlintTrade's Python and terminal helpers refuse a missing expiry before posting; a raw HTTP body without `expiry_date` still reaches OpenAlgo and is rejected there. |
| `optiongreeks` | Greeks for a specific strike. |
| `multioptiongreeks` | Greeks for a list of strikes in one request. |
| `optionsymbol` | Resolve expiry / type / offset to a tradeable symbol. Remote calls use official offsets `ATM` / `ITM1`–`ITM50` / `OTM1`–`OTM50`. Explicit numeric strikes are built locally as compact symbols and are not posted. |
| `symbol` | Symbol metadata lookup. |
| `search` | Symbol search by name / partial match. |
| `expiry` | List of available expiries for a symbol. |
| `intervals` | Supported chart intervals. **POST** with `apikey` in the JSON body (not GET). The OpenAlgo response may be bucketed (`seconds` / `minutes` / `hours` / `days` / `weeks` / `months`); the terminal flattens those buckets to a string list. The Python client returns the bucketed object. |
| `syntheticfuture` | Synthetic future from CE - PE + strike. Same required fields as `optionchain`: `underlying`, `exchange`, and `expiry_date` (`DDMMMYY`). FlintTrade helpers refuse a missing expiry before posting; raw HTTP still reaches OpenAlgo. |
| `ticker/{exchange}:{symbol}` (**GET**) | Dated historical helper on the Python client only (`apikey`, `interval`, `from`, `to` query params). Not the live polling path — polling uses POST `quotes`. Missing `from`/`to` fails closed. |
| `instruments` (**GET**) | Instrument master for an exchange. Requires `apikey` and `exchange` query params. When no exchange is given, FlintTrade queries `NFO` / `BFO` / `MCX` / `CDS`. |

`gex`, `iv_smile`, `max_pain`, `oi_profile`, `pnl/symbols`, and `chart` are
**not** OpenAlgo passthroughs. The `OpenAlgoClient` wrappers were removed
because those routes do not exist upstream. GEX / IV smile / max-pain / OI
profile are FlintTrade analysis routes below. Chart preferences are
FlintTrade `GET`/`POST` `/api/v1/chart`.

### Utilities

| Endpoint | Purpose |
|---|---|
| `market/holidays` | Holiday calendar. **POST** with `apikey` and `year` (2020–2050) in the JSON body. Do not call bare `holidays` as the current passthrough path. |
| `market/timings` | Exchange-timing windows. **POST** with `apikey` and `date` in the JSON body. Missing date fails closed. Do not call bare `timings` as the current passthrough path. |
| `telegram/notify` | Send a Telegram message via the OpenAlgo bot (`username` + `message`). If `username` is omitted, FlintTrade uses workspace `openalgo.telegram_username` when set; otherwise the call fails closed. That field is accepted and persisted by `GET`/`POST` `/v1/config/openalgo` or a `workspace.json` edit — not by the Setup/Settings connection form, which only writes `api_key`, `host`, `port`, and `ws_port`. Distinct from FlintTrade's native `POST /api/v1/telegram` (Automate → Settings Send Test). |
| `whatsapp/notify` | Upstream OpenAlgo endpoint. **Not wrapped by FlintTrade** — WhatsApp support was removed on 2026-07-26 (ruling D3); listed only so the OpenAlgo surface stays fully documented. |

### Broker management (session-authenticated, NOT under `/api/v1/`)

These endpoints were added in OpenAlgo 2.0.0.2 and live at a different
path because they require session auth, not API-key auth.

| Endpoint | Purpose |
|---|---|
| `/api/broker/capabilities` (**GET**) | Per-broker feature matrix. |
| `/api/broker/credentials` (**GET/POST**) | Read or write broker credentials. |
| `/leverage/api/current` (**GET**) | Current leverage settings. |

---

## 2. FlintTrade backend (`/ft-api/v1/*`)

Source of truth: `packages/core/core/src/flinttrade_core/app.py` and the `*_routes.py` files
under `packages/*/src/`. Externally clients call `/ft-api/v1/…`;
internally blueprints are registered at `/v1/…` (or `/api/v1/…` for the
OpenAlgo-style paths). Both shapes route to the same handler thanks to
the WSGI prefix-strip.

### Order submission

Four routes submit an order. Every order FlintTrade submits goes
through admission when it's placed. Nothing else does, including
`POST /api/v1/orders/place-smart`, `POST /api/v1/orders/open-position`,
and `POST /api/v1/orders/close-position`, which are not mounted. The
Practice book under `/v1/sandbox/` can cancel or modify a resting order.
It has no place route and no square-off route. Practice square-off is
an opposite order on `POST /api/v1/orders/place`. Settings → Practice
adjusts virtual capital and square-off times; it does not place.

| Route | What it does |
|---|---|
| `POST /api/v1/orders/place` | Practice and Live single-leg place. The server admits the body through Laya. A client flag cannot choose reduce-only. Practice then fills or rests in the sandbox and does not enter SafetySystem. Live then runs SafetySystem, `gate_order`, and `BrokerRouter`. `"variety": "gtt"` is HTTP 422 `gtt_unsupported` before that admission. Example data is HTTP 403 `mode_blocked`: `Orders are not available for Example. Switch to Practice or Live to trade.` |
| `POST /api/v1/orders/<broker>/place` | Live only. `<broker>` is the adapter id. The same dispatcher admits through Laya and then runs SafetySystem on that place. `"variety": "gtt"` is HTTP 422 `gtt_unsupported` before admission, including when the variety spelling differs only by case or separators. A non-Live session is HTTP 400 (`The routed order path serves live mode only. Use /api/v1/orders/place for explore/practice.`). |
| `POST /api/v1/positions/exit-all` | Live, PIN-unlocked. `"variety": "gtt"` is HTTP 422 `gtt_unsupported` before the live check, the reduce-only proof, and any broker call. Body must include boolean `"confirm": true` or the route returns HTTP 400. The server classifies every open contract and records a reduce-only proof before the gated `exit_all_positions` verb. A row that is not an exit stops the request with HTTP 409 and `Square-off stopped because a position is not a reduce-only exit.` An unreadable book still records one reduce-only proof. |
| `POST /api/v1/orders/bracket` | Live, PIN-unlocked. Entry plus exactly one of a stop-loss or a target. Each leg is admitted through Laya, then placed through SafetySystem, `gate_order`, and `BrokerRouter`. Success is HTTP 201. Practice is HTTP 403 `practice_unsupported`. `"variety": "gtt"` is HTTP 422 `gtt_unsupported` before that admission. A broker-held variety is HTTP 422 `broker_held_unsupported` (`Not placed. Broker-held bracket legs aren't supported. Use one stop-loss or one target.`). A stop-loss and a target together are HTTP 422 `oco_unsupported`. A trailing stop is HTTP 422 `trailing_unsupported`. |

`POST /api/v1/orders/cancel-all` cancels open orders. Practice cancels
pending sandbox orders. Live uses the gated `cancel_all_orders` verb and
does not place. A Live body with `strategy` set is HTTP 400, because that
verb cannot narrow by strategy.

Reduce-only is decided on the server. A close qualifies when it is the
same contract, the opposite side, and the quantity is no more than the
open quantity minus pending exits. On Live, pending exits include the
broker's open orders on that contract when that book can be read. When
the broker order book cannot be read, the cap is the open quantity minus
this desk's own pending exits, and the close can still qualify. When the
position book cannot be read, the place is not classified as a close.
A second exit on the same broker account, while one of this desk's exits
on that contract is still unfilled, is HTTP 409 `exit_pending`, with
`message` and `reason` both
`Not placed. An exit for <symbol> is already pending. Wait for it to fill, or cancel it and try again.`
Practice uses this code on the Practice book. On Live it is the code when
the broker order book can be read. The Live hold is for that broker
account. When that second exit is refused because
the broker order book cannot be read, the code is `exit_orders_unreadable`, and
`message` and `reason` are both
`Not placed. One exit at a time for <symbol> until your broker's orders load.`
The Positions row shows **Exit pending** for the unfilled exit. The
label is the symbol, or `this contract` when the symbol is empty.

While Laya is Down, a new order is paused and a qualifying close is still
admitted. Live still runs SafetySystem after that record. The desk line is
`Laya is Down. New orders are paused until it's Ready. You can still close positions.`
A filled reducing close can show `Closed. Exits are allowed while Laya is Down.`

A position whose sign flips after the broker book has loaded keeps its
row, tagged **Unexpected**, and the Positions book shows
`Position changed after your broker's orders loaded. You're now <long or short> <quantity> <symbol>. Close it if that wasn't intended.`
until dismissed.

Layer 5 (`POST /api/v1/safety/kill-switch`) and Ditto Kill All
(`POST /api/v1/ditto/kill-all`) cancel resting orders and then flatten.
They are not cancel-only, and they are not a fourth submit route: the
flatten runs as the emergency `exit_all_positions` verb after the cancel.

### Analysis (`/api/v1/*`; Vite proxy `/ft-api/api/v1/*`)

Powered by `packages/services/screener/`. The analysis blueprint mounts at
`/api/v1`, not `/v1`. POST endpoints expect a JSON body (`symbol`,
`exchange`, and `expiry` / `expiry_date` for option-chain tools). GET
endpoints are marked.

| Endpoint | Purpose |
|---|---|
| `gex` (**POST**) | FlintTrade analysis route: Gamma Exposure dashboard data, computed locally on historical chains. |
| `volsurface` (**POST**) | Volatility surface across strikes and expiries. |
| `ivsmile` (**POST**) | IV smile curve. |
| `straddlepnl` (**POST**) | Live straddle P&L for an at-the-money pair. |
| `oiprofile` (**POST**) | OI profile data. |
| `maxpain` (**POST**) | Max-pain calculation. |
| `gammadensity` (**POST**) | Gamma density surface across strikes and expiries. |
| `screener/fii-long-short` (**GET**) | FII long/short ratio from participant-wise derivative positions. |
| `screener/fii-dii` (**GET**) | FII/DII cash-market activity summary. |
| `screener/arbitrage` (**POST**) | Cash-future and cross-exchange arbitrage scan. |
| `candlestick-patterns` (**POST**) | Candlestick pattern detection over OHLCV history. |
| `/v1/index-contribution` (**GET**) | Index constituent contribution — `breadth_bp` at `/v1`, not `analysis_bp`. |

### Chart preferences (`/api/v1/chart`)

Source: `packages/core/core/src/flinttrade_core/chart_prefs_routes.py`.
FlintTrade-owned UI store — not an OpenAlgo passthrough.

| Endpoint | Purpose |
|---|---|
| `chart` (**GET/POST**) | Chart-preference get/set. |

### Legacy gateway accounts (`/v1/*`; Vite proxy `/ft-api/v1/*`)

Source: `packages/integrations/gateway/src/flinttrade_gateway/auth.py`.
The gateway blueprint mounts at `/v1` — there is no `/v1/broker/` segment.
Native-broker ids are rejected here and redirected to `/api/v1/native/*`.
Used by older OpenAlgo-bridge account flows. Catalogue and account-list
**GET**s remain metadata reads. Every production account-authority
**mutation** is frozen: authenticated callers receive a stable `503`
`{error: broker_account_cutover_unavailable}` from
`guard_broker_account_http` until Task 9D migrates the handlers and
removes that guard atomically. The terminal still calls these routes;
they do not create sessions. This is an accepted product decision —
native broker UX stays down on `main` until Task 9D and Task 7C.2.

| Endpoint | Current behaviour |
|---|---|
| `GET /v1/brokers` | Enumerate catalogued brokers with capability flags. |
| `GET /v1/accounts` | List linked (non-native) accounts (metadata only; not a restored native session). |
| `POST /v1/accounts` | Frozen. Returns `503` until Task 9D. |
| `DELETE /v1/accounts/<account_id>` | Frozen. Returns `503` until Task 9D. |
| `POST /v1/auth/credentials` | Frozen. Returns `503` until Task 9D. |
| `POST /v1/auth/otp/request` | Frozen. Returns `503` until Task 9D. |
| `POST /v1/auth/otp/verify` | Frozen. Returns `503` until Task 9D. |
| `POST /v1/auth/oauth/start` | Frozen. Returns `503` until Task 9D. |
| `GET /v1/auth/oauth/callback` | Frozen before state consumption. Returns `503` until Task 9D. |
| `POST /v1/accounts/<account_id>/reconnect` | Frozen. Returns `503` until Task 9D. |
| `POST /v1/accounts/<account_id>/set-primary` | Frozen. Returns `503` until Task 9D. |
| `GET /v1/rate-limits` | Read adapter rate-limit configuration. |
| `PUT /v1/rate-limits` | Frozen. Returns `503` until Task 9D. |

### Native broker connect and reads (`/api/v1/native/*`)

Source: `packages/core/core/src/flinttrade_core/native_account_routes.py`.

These endpoints are the first-party native broker HTTP surface the terminal
still calls from Setup → Brokers and Settings → Brokers. **They are not a working operator path
on this unreleased line.** Account-management writes
(POST / DELETE / PUT / PATCH, plus the GET OAuth callback) return `503`
`broker_account_cutover_unavailable` until Task 9D. Account and market-data reads
return `409` with zero provider calls until the Task 7C.2 / 8B
read-port cutover onto the in-process `BrokerReadPort`. Exact broker reads
that already exist are that in-process port, not this HTTP family and not
terminal UX. Brokers that are built but not cleared for activation stay
`connectable=false` while any declared `native_connect_blocker` remains.
Legacy gateway `/v1` account/auth mutations are likewise frozen (`503`) and
still reject native broker ids with `data.native_connect_blockers` when a
catalogued native broker is evidence-gated.

| Endpoint | Current behaviour |
|---|---|
| `native/brokers` (**GET**) | Native broker catalogue with connectability, native-connect blocker reasons, static-outbound-IP requirement, login-method schemas, OAuth/postback URLs, and MCP metadata. |
| `native/accounts` (**GET**) | Vault-backed native account list (metadata only). Not a live session refresh. |
| `native/accounts` (**POST**) | Frozen connect. Returns `503` until Task 9D. Body shape remains `{adapter_id, account_id, label?, credentials, is_primary?}`. |
| `native/oauth/start` (**POST**) | Frozen. Returns `503` until Task 9D. |
| `native/oauth/callback` (**GET**) | Frozen before state consumption. Returns `503` until Task 9D. |
| `native/postbacks/<adapter_id>` (**POST**) | Bounded, redacted broker postback intake for diagnostics/order-update evidence; not an order execution path. Not an account-mutation cutover route. |
| `native/accounts/<adapter>/<account>/login` (**POST**) | Frozen re-authentication. Returns `503` until Task 9D. |
| `native/accounts/<adapter>/<account>/<kind>` (**GET**) | Frozen native HTTP read. Returns `409` with zero provider calls until Task 7C.2. Documented kinds (`funds`, `limits`, `positions`, `holdings`, `profile`, `orders`, `orderstatus`, `orderhistory`, `ordertrades`, `trades`, `ltp`, `quotes`, `quote_details`, `ohlc`, `depth`, `margin`, `scrip_master`, `holidays`, `timings`, `optiongreeks`, `history`, `expiry`, `optionchain`, `search`, `search_scrip`) are the intended post-cutover surface, not a current live-session API. |
| `native/accounts/<adapter>/<account>/set-primary` (**POST**) | Frozen. Returns `503` until Task 9D. After Task 9D this remains the write-default gate for a connected, non-read-only native session. |
| `native/accounts/<adapter>/<account>` (**DELETE**) | Frozen removal. Returns `503` until Task 9D. |

### Broker capability metadata (`/api/v1/broker/*`, GET)

Source: `packages/integrations/gateway/src/flinttrade_gateway/capabilities_routes.py`.

| Endpoint | Purpose |
|---|---|
| `broker/capabilities` (**GET**) | Per-broker capability matrix (order types, segments, depth, rate limits), with native connectability, blocker reasons, and static-outbound-IP requirement where catalogued. |
| `broker/mcp` (**GET**) | Broker-hosted MCP setup catalogue for OpenAlgo, Dhan, Upstox, and Groww. Metadata only: URLs, client configs, read-only/trading flags, native-connect blocker reasons, static-outbound-IP requirement, login notes, use cases, and cautions. FlintTrade does not proxy MCP tool calls or create an MCP order path around its safety gate. |
| `broker/recommendations` (**GET**) | Filter broker capability metadata for an operator-selected use case, including display name, connectability, native-connect blocker reasons, and static-outbound-IP requirement. `?use_case=<id>` for one job (for example `low_cost_execution`, `market_depth`); `?brokers=a,b` restricts the response to connected brokers. |

`broker/mcp?broker=<id>` returns one MCP row. `openalgo` is accepted as the
primary bridge MCP entry. Unknown broker ids and catalogued brokers without
FlintTrade MCP metadata return `404` with `known_brokers`, so client typos do
not silently fall back to the full catalogue. Broker-hosted MCP trade tools,
where a broker offers them, remain external to FlintTrade's in-process
`gate_order` / `BrokerRouter` path.

### Service providers and connections (`/ft-api/v1/services/*`)

Source: `packages/core/core/src/flinttrade_core/service_provider_routes.py`,
`service_connection_routes.py`, `service_providers.py`, and
`service_connections.py`.

This is a static, non-invoking control plane. Listing a provider or persisting
a connection does not resolve, probe, authenticate to, or start that provider.

The catalogue is composed at app startup from the AI, historical, and gateway
contributor descriptors. Catalogue `service_kinds` values include
`broker_execution`, `market_data_live`, `market_data_historical`, `news`,
`llm`, `forecast`, `agent_runtime`, `embedding`, and `decision`.

`decision` entries are catalogue providers for place admission, not LLM chat
profiles. Their default evidence scope is offline qualification until a Live
qualification record exists. Listing them does not probe or start the host.

| Endpoint | Purpose |
|---|---|
| `services/providers` (**GET**) | Static provider catalogue, returned as `{"status": "success", "data": {"catalogue_digest": …, "count": …, "providers": […]}}`. Requires `admin.observability.read` on a session JWT; an API-key request with no session token is treated as holding every scope. Returns 503 if the catalogue is unavailable. |
| `services/connections` (**GET**) | List every redacted inert LLM connection. Loopback only. Session JWT with `admin.services.read`, or `X-API-Key` / Bearer API key for GET/HEAD. |
| `services/connections` (**POST**) | Persist one inert LLM connection (`provider_id`, `label`, optional `model`, and provider-dependent `endpoint` / `auth_mode` / `credential`). Authenticated profiles require a supported `auth_mode`; host-based profiles require `endpoint`, while fixed or managed profiles reject endpoint overrides. Unauthenticated profiles reject credentials. Does not call the provider. Session JWT with `admin.services.write` required — an API key cannot mutate. |
| `services/connections/<connection_id>` (**GET**) | One redacted connection by canonical UUID4. Same read auth as the collection. |
| `services/connections/<connection_id>` (**PATCH**) | Update label / model / endpoint / auth_mode (and optional credential rotation). `provider_id` is immutable. Same write auth as create. |
| `services/connections/<connection_id>` (**DELETE**) | Delete one inert connection. Same write auth as create. JSON body must be an empty object. |

Connection reads and writes are loopback-only. Non-loopback peers receive 403
`forbidden` before route dispatch. Mutations require `If-Match` (collection
ETag) and `Idempotency-Key` (UUID4); missing `If-Match` is 428
`connection_revision_required`. Mutation endpoints share a 10-per-minute
limit. Individual redacted connection objects include `schema_version`,
`provider_id`, `connection_id`, `label`, `model`, `endpoint`, `auth_mode`,
`credential_configured`, `created_at`, and `updated_at` — never the secret
material. The collection read wraps those objects in `connections`; a delete
returns only `{"deleted": true}`. Every service-connection-family response is
`Cache-Control: no-store`.

The in-process `BrokerReadPort` (quotes, depth, history, account books, and
related exact reads) is not this HTTP surface and is not terminal UX. Native
HTTP reads stay `409` until Task 7C.2 migrates callers onto that port. See
[ARCHITECTURE.md](ARCHITECTURE.md#broker-reads-versus-gated-writes).

### News (`/api/v1/news`)

Source: `packages/core/core/src/flinttrade_core/operations_routes.py`. The
operations blueprint mounts at `/api/v1`, so the Vite/dev-proxy form is
`/ft-api/api/v1/news`. The terminal News widget calls this route only.

| Endpoint | Purpose |
|---|---|
| `news` (**GET**) | Server-side fetch of the static RSS publisher profiles (MoneyControl, ET Markets, LiveMint). There is no browser-side RSS or CORS-proxy fallback. |

### AI (`/api/v1/advisor*`, `/api/v1/ai/*`, `/api/v1/signals/*`; Vite proxy `/ft-api/api/v1/…`)

Source: `packages/services/ai/`. Blueprints mount at `/api/v1`. GET unless
noted. Advisor Chat uses `/api/v1/advisor` (not `/ai/advisor`). Managed local
inference (`/v1/ai/local-runtime`) is the exception — that blueprint stays
under `/v1`.

| Endpoint | Purpose |
|---|---|
| `advisor/status` (**GET**) | LLM readiness for Chat Connected honesty. `data.source` is `env` (explicit `LLM_PROVIDER`), `stored` (Settings → AI), or `default` (empty→ollama implicit default — not Connected). `configured` is true only for `env` or `stored`. |
| `advisor` (**POST**) | Chat completion. Analysis only — does not place Live or Practice orders. Returns 503 when no explicit LLM is configured. |
| `advisor/stream` (**POST**) | SSE variant of `advisor`. Same body; tokens then `done: true`. |
| `signals/recent` (**GET**) | Recent ML/indicator signals (the live signal source). |
| `ai/sentiment/summary` (**GET**) | Market-wide sentiment summary; neutral when no feed is connected. |
| `ai/sentiment/tickers` (**GET**) | Per-ticker sentiment from news feeds. |
| `ai/regime?symbol=` (**GET**) | ADX/ATR/BB market regime for a symbol (requires connected market data). |
| `sentiment/analyse` (**POST**) | Sentiment for a text snippet or symbol (LLM, rule-based fallback). |
| `ai/refine-strategy` (**POST**) | AI improvement suggestions for a backtested strategy. |
| `rag/query` (**POST**) | Knowledge-base RAG query (when RAG is enabled). |

Managed local inference is controlled through authenticated, localhost-only
routes under `/ft-api/v1/ai/local-runtime`. Runtime and model downloads never
start at boot and require an explicit confirmation payload. Every mutating POST
except `stop` also requires a client-generated `admission_id` matching
`adm_[0-9a-f]{32}`. The status operation echoes that admission ID, so a caller
can retry the same request idempotently and reconcile an HTTP timeout. `stop`
instead accepts only the exact ID of a currently running operation; terminal
operation IDs are rejected. Detailed receipts are size- and count-bounded; IDs
compacted from the detailed journal remain fail-closed in a fixed-size spent-ID
filter. An `indeterminate` receipt means the mutation outcome cannot be proved:
clients must not issue a replacement admission ID. Further mutations remain
blocked until the operator explicitly acknowledges that exact operation and its
original admission ID through `operations/reconcile`. Acknowledgement does not
replay the mutation or change its outcome to success; it records only that the
unknown result was reviewed. The terminal validates every successful status,
model-list and direct-result payload before changing local state, and clears a
pending admission only when a direct receipt has the exact shape required by
that action.

| Endpoint | Purpose |
|---|---|
| `ai/local-runtime/status` (**GET**) | Report the managed release, target and rollback versions, ownership, readiness, integrity, progress and teardown state. |
| `ai/local-runtime/install` (**POST**) | Download, hash-verify and install the pinned Ollama release after confirmation. |
| `ai/local-runtime/update` (**POST**) | Stage the preferred release while stopped, then retain the previously active verified release for rollback. |
| `ai/local-runtime/repair` (**POST**) | Recover invalid version metadata or replace a corrupt managed release while no Ollama listener is active. |
| `ai/local-runtime/rollback` (**POST**) | Rehash and activate the retained previous release while stopped. |
| `ai/local-runtime/uninstall` (**POST**) | Remove recognised managed runtime releases while preserving models and model-trust metadata. |
| `ai/local-runtime/start` · `ai/local-runtime/stop` (**POST**) | Start or stop only the Ollama process owned by this backend. |
| `ai/local-runtime/operations/reconcile` (**POST**) | Explicitly acknowledge one indeterminate receipt using its exact operation and original admission IDs, without replaying it or inferring success. |
| `ai/local-runtime/models` (**GET**) | Return the live bounded model catalogue after reconciling FlintTrade trust metadata. |
| `ai/local-runtime/models/pull` (**POST**) | Download one validated model identifier after confirmation. |
| `ai/local-runtime/models/delete` (**POST**) | Delete one exact unselected model name after confirmation. |
| `ai/local-runtime/models/prune` (**POST**) | Delete only unreferenced `flinttrade/sha256-*:locked` aliases; never walk arbitrary model blobs. |
| `ai/local-runtime/models/digests/accept` (**POST**) | Confirm one exact live digest and create a digest-derived inference alias. |
| `ai/local-runtime/models/digests/reset` (**POST**) | Remove invalid FlintTrade trust metadata without deleting Ollama model data. |

### Sandbox / paper trading (`/ft-api/v1/sandbox/*`)

Native virtual-capital paper trading. Source: `packages/core/data/src/flinttrade_data/sandbox_routes.py`.

| Endpoint | Purpose |
|---|---|
| `sandbox/status` (**GET**) | Combined status: current + initial capital, P&L, trade count. |
| `sandbox/capital` (**GET**) | Full capital state (initial / current / available / used margin). |
| `sandbox/capital/adjust` (**POST**) | Add or remove virtual capital (`{amount}`). |
| `sandbox/positions` · `sandbox/orders` · `sandbox/trades` · `sandbox/pnl` (**GET**) | Book, fill, and P&L reads. Orders are placed through `POST /api/v1/orders/place`. |
| `sandbox/order/<order_id>` (**DELETE** / **PATCH**) | Cancel or modify one pending Practice order. |
| `sandbox/orders/cancel-all` (**POST**) | Cancel every pending Practice order. Does not place. |
| `sandbox/reset` (**POST**) | Clear all paper data (returns a backup). |
| `sandbox/export` (**GET**) · `sandbox/import` (**POST**) | Export sandbox state, or restore it. Restore requires a Practice session JWT. Any other session, including an API key, is HTTP 403 `Restore is available in Practice Mode only.` Restored fills are stored with strategy `Restored from backup`. They are not sent to a broker and do not re-enter the order path. The desk shows a **Restored** tag whose tooltip is `Restored from backup. Not sent to a broker or checked by Laya.` Laya, strategy, benchmark, and training readers omit them. P&L still counts them. Performance shows `Excludes 1 restored fill` or `Excludes N restored fills`, and hides that line when the count is 0. |

### Strategies (`/api/v1/strategies/*`; Vite proxy `/ft-api/api/v1/strategies/*`)

Source: `packages/services/engine/src/flinttrade_engine/strategy_routes.py`.
The blueprint mounts at `/api/v1/strategies`. Backed by the
`STRATEGY_RUNNER` + `CRON_SCHEDULER` wired at app creation.

| Endpoint | Purpose |
|---|---|
| `strategies` (**GET**) | List uploaded user strategies (engine runner). Lab also lists the same runner via `GET /api/v1/backtest/strategies/uploaded`. There is no `/api/v1/strategies/uploaded` route. |
| `strategies/upload` (**POST**) | Upload + validate a strategy. |
| `strategies/<id>/start` · `…/stop` (**POST**) | Start / stop a running strategy. |
| `strategies/<id>/logs` (**GET**) | Tail a strategy's logs. |
| `strategies/<id>/schedule` (**POST**) · `strategies/scheduled` (**GET**) | Cron-schedule a strategy. |

### Trade journal (`/ft-api/api/v1/trades/*`)

Source: `packages/core/core/src/flinttrade_core/operations_routes.py`. Every
executed live order is appended to a shared DuckDB store by the gated order
dispatch, so the journal populates in Live mode. (Live P&L is computed
client-side in the MTM Monitor widget from real positions; the previously
documented in-memory `pnl-tracker` endpoints were unfed and were removed.)

| Endpoint | Purpose |
|---|---|
| `trades/journal` (**GET**) | Recorded trades. No params → today; `start_date`+`end_date` → history window across all strategies; `+strategy` → that strategy only. `limit` defaults to 100 and caps at 1000 (oldest-first). `data.total` is the untruncated match count. Rows are keyed `timestamp` (ISO, IST), with `symbol`, `action`, `quantity`, `price`, `pnl`, `strategy`, `orderid`. |

### Safety (`/api/v1/safety/*`)

Source: `packages/core/core/src/flinttrade_core/operations_routes.py`.
The operations blueprint mounts at `/api/v1`, so the Vite/dev-proxy form is
`/ft-api/api/v1/safety/…` and a direct backend call is
`http://<host>:5100/api/v1/safety/…`. These are not under `/v1/`.

| Endpoint | Purpose |
|---|---|
| `safety/config` (**GET** / **POST**) | Read or update local safety parameters and the current kill-switch / Layer 4 pause state. |
| `safety/l4` (**DELETE**) | Clear one account's latched Layer 4 daily-loss pause or hard stop. Requires both `broker` and `account_id` (query string or JSON body); the backend builds the exact selector `{broker}:{account_id}`. A PIN-unlocked Live JWT is required, and that selector must be in the operator's account ACL. Missing selector → 400 `"L4 reset requires an exact account selector"`; unauthorised selector → 403. Does not activate or reset Layer 5. |
| `safety/kill-switch` (**POST**) | Latch Layer 5. Body `{ "reason": "…" }`. Cancels open orders and requests supported flatten. |
| `safety/kill-switch` (**DELETE**) | Reset Layer 5 after emergency actions complete. Incomplete flatten keeps the latch. |

### Cron / Schedules (`/api/v1/cron/*`)

Source: `packages/core/core/src/flinttrade_core/operations_routes.py`.
The operations blueprint mounts at `/api/v1`, so the Vite/dev-proxy form is
`/ft-api/api/v1/cron/…` and a direct backend call is
`http://<host>:5100/api/v1/cron/…`. These are not under `/v1/`.

| Endpoint | Purpose |
|---|---|
| `cron/jobs` (**GET**) | List registered cron jobs with status (`name`, `description`, `trigger_type`, `status`, `last_run`, `run_count`, `error_count`). |
| `cron/jobs/<name>/pause` (**POST**) | Pause a job by name. Sample-data writes (JWT `mode` claim or `X-FlintTrade-Mode: explore`) return HTTP 403 with `code: "mode_blocked"`. Operators see example data, not a Mode in the menu. Practice and Live are not blocked by this gate. CronManager missing → 503 (`CronManager not available`). Unknown name → 404 (`Job '<name>' not found`). |
| `cron/jobs/<name>/resume` (**POST**) | Resume a paused job by name. Same sample-data `mode_blocked` gate, 503, and 404 as pause. |

### Telegram (`/api/v1/telegram`)

Source: `packages/core/core/src/flinttrade_core/telegram_routes.py`.
The telegram blueprint mounts at `/api/v1`, so the Vite/dev-proxy form is
`/ft-api/api/v1/telegram` and a direct backend call is
`http://<host>:5100/api/v1/telegram`. This is FlintTrade's local automation
bot (terminal Automate → Settings **Send Test**), not OpenAlgo's
`telegram/notify`.

| Endpoint | Purpose |
|---|---|
| `telegram` (**POST**) | Send a Telegram test message. Body requires `message`. Optional one-shot `bot_token` and `chat_id` are accepted together and are never persisted. Otherwise the route uses env/workspace bot config; disabled config → 400. Send failure → 502. Sample-data sends (JWT `mode` claim or `X-FlintTrade-Mode: explore`) return HTTP 403 with `code: "mode_blocked"`. The desk helper is `Telegram tests are blocked for Example. Switch to Practice or Live with Telegram configured to send a real test.` |

### Ditto (`/api/v1/ditto/*`)

Source: `packages/core/core/src/flinttrade_core/operations_routes.py`.
The operations blueprint mounts at `/api/v1`, so the Vite/dev-proxy form is
`/ft-api/api/v1/ditto/…` and a direct backend call is
`http://<host>:5100/api/v1/ditto/…`.

| Endpoint | Purpose |
|---|---|
| `ditto/mirror/start` (**POST**) | Start position mirroring (Live-only, PIN-unlocked). Incomplete body (missing `source_account` / `target_accounts`) → 400. Sample-data starts (JWT `mode` claim or `X-FlintTrade-Mode: explore`) return HTTP 403 with `code: "mode_blocked"`. The desk helper is `Mirroring is blocked for Example. Switch to Practice or Live with broker accounts connected.` Practice (and any other non-Live session) is refused HTTP 403 after that gate: `Protected safety actions require an authenticated Live session` (no `mode_blocked`). A Live JWT without PIN unlock is 403 (`Live mode must be PIN-unlocked before changing protected safety state`). |
| `ditto/kill-all` (**POST**) | Flatten/cancel all managed accounts (emergency Kill All). Optional body `reason` (string, truncated server-side). Sample-data requests (JWT `mode` claim or `X-FlintTrade-Mode: explore`) return HTTP 403 with `code: "mode_blocked"` and message `Risk runtime unavailable — Kill All disabled.` before Live-session auth. Practice (and any other non-Live session) is refused HTTP 403 after that gate: `Protected safety actions require an authenticated Live session` (no `mode_blocked`). A Live JWT is enough; PIN unlock is not required. Missing `DITTO_RUNTIME` → HTTP 503 (`Ditto runtime unavailable`). Complete flatten → 200 with `status: success`; incomplete → 207 with `status: partial`. |
| `ditto/mirror/status` (**GET**) | Position-mirroring status across accounts. |
| `ditto/mirror/stop` (**POST**) | Stop position mirroring. |

### Auth (`/ft-api/v1/auth/*`)

JWT-based. Source: `packages/core/core/src/flinttrade_core/auth_routes.py`.

| Endpoint | Purpose |
|---|---|
| `GET auth/status` | First-run probe. Returns `is_setup`, `is_locked`, `has_pin`, and `totp_enabled`. `data.migration_blocked` is `two_operators` when more than one operator account is present, and null otherwise. |
| `POST auth/setup` | First-run enrolment (Create operator). Body `{ "username", "email", "password", "pin"? }`. The server generates TOTP and returns `totp_uri`, backup codes, and a setup-session JWT (`setup_session`) with `mode` `practice`. That token is a Practice session. It is what `POST auth/setup/vault` accepts. Authenticator enrolment is optional for example data and Practice; Live still needs a confirmed authenticator plus PIN. It does not accept a caller-supplied TOTP secret. A second create, including one that overlaps the first, raises `Account already set up` in the account service. The route answers HTTP 409 with `code: "operator_exists"` and message `Request conflicts with the current state`. The setup screen maps that code to **This machine already has an operator. Sign in to finish setup.** A 409 without `operator_exists` keeps the generic message. |
| `POST auth/setup/resume` | Public. A reload mid-setup drops the setup-session JWT that lived only in the browser tab, so this proves the password and mints a setup-session JWT again. It mints a Practice setup session, the same as `POST /v1/auth/setup` (`setup_session` true, Live not unlocked). Body `{ "password", "totp_code"? }`. Once an authenticator is enrolled, that code is required as well. No operator yet is HTTP 409 `Create an operator before continuing setup.` A finished setup is HTTP 409 `Setup is already complete. Sign in.` A wrong password is HTTP 401 `Invalid credentials.` It does not require a session that is already in the browser. |
| `POST auth/setup/vault` | Open the credential vault during first-run Setup. Requires the account-create setup-session JWT. Daily-login tokens are rejected. Body `{ "master_password" }` (at least 8 characters when the vault file is missing). Persists the secret when it is missing and leaves an existing secret untouched. Success is `{ "opened": true, "already_present": bool }` under `data`. The response never returns the secret. |
| `POST auth/setup/complete` | Session-bound. Records that first-run setup has finished. Requires the operator's session JWT; the setup-session JWT qualifies, and an API key does not. The operator must already exist and the vault must be open. Success is `{ "setup_finished": true }` under `data`. A missing session is HTTP 401 `Sign in to continue setup.` |
| `POST auth/setup/reset` | Wipe local enrolment so Setup can run again. Before authenticator enrolment, the account-create setup JWT can start over with an empty body, and a session plus the password can wipe the account. Once an authenticator is enrolled, recovery requires an active session, the password, and the current authenticator code (`totp_code`). An API key is not a session. A signed-out request on a finished account changes nothing. When an authenticator is enrolled the response is HTTP 403 `Sign in to reset this account. You'll need your password and authenticator code.` Otherwise it is HTTP 401 `Sign in to reset this account. You'll need your password.` The body includes `authenticator_enrolled`. A successful wipe bumps the account epoch, so other session tokens stop working. |
| `POST auth/setup/regenerate-2fa` | Rotate the login TOTP secret and clear `totp_enabled` until a live code is confirmed again. Before enrolment, a session and the password are enough. Once an authenticator is enrolled, the current authenticator code is required as well. A signed-out request on a finished account returns the same sign-in message as reset and changes nothing. |
| `POST auth/login` | Sign in with password (argon2id-hashed). `totp_code` (or a backup code) is required only after authenticator enrolment (`totp_enabled`). Issues a Practice JWT (`mode` `practice`). A fresh login opens Practice. When `migration_blocked` is `two_operators`, this returns HTTP 409 with message `FlintTrade couldn't finish updating.` and does not issue a token. |
| `POST auth/totp/enable` | Confirm optional authenticator enrolment. Session-bound. Body `{ "totp_code" }`. Sets `totp_enabled`; later logins then require a TOTP or backup code. |
| `POST auth/pin` | Quick Unlock with the 6-digit PIN. Requires an existing session JWT. Body `{ "pin" }`. Reopens the Mode already on that session and never changes it. Practice stays Practice. An Example (sample-data) session stays that session. A session that is already Live stays Live and keeps the authenticator enrolment check (403 `totp_required` until enrolled). Connected (read) is a broker status, not a session Mode. A successful unlock revokes the presented session and returns a new token. The previous token stops working. There is no `/auth/me`. |
| `POST auth/live` | Explicit Live switch, and the only route that enters Live. Requires an existing session JWT. Body `{ "pin" }`. Requires authenticator enrolment and mints a Live JWT with `live_mode_unlocked=true`, after revoking the presented session. Refuses 403 `totp_required` until the authenticator is enabled. |
| `POST auth/pin/set` | Set or change the PIN (password re-confirm). Requires an existing session JWT. Does not change Mode. |
| `POST auth/mode` | **Downgrade only** to `practice`. Requires an existing session JWT. A body of `{ "mode": "practice" }` issues a fresh JWT and revokes the old `jti`. Any other value, including `explore`, `live`, and a missing `mode`, returns HTTP 400 before the current session is revoked. The body is `{ "status": "error", "message": "Only a downgrade to practice is allowed here. Switch to Live via POST /v1/auth/live with PIN verification." }` with no `code`. Live is entered only through `POST /v1/auth/live`. |
| `POST auth/logout` | Revoke the current JWT by `jti`. Requires an existing session JWT. |
| `POST auth/forgot-password` | JWT-token email reset. Body `{ "email" }`. Reads Flask-Mail `MAIL` from the Flask app config. A normal backend start never assigns `MAIL` (only tests inject it), so this returns 503 (`Email service not configured.`) on a stock process. SMTP/SES env vars do not enable this pair. Missing email → 400. When `MAIL` is injected and `email` is present, always returns 200 (`If the email is registered, a reset link has been sent.`) so the address is not enumerated. Rate-limited to 3 requests per hour per client. |
| `POST auth/reset-password` | Consume a reset JWT from `forgot-password`. Body `{ "token", "new_password" }`. The token lasts 1 hour. Password minimum 8 characters. Missing fields or an invalid / expired token → 400. Rate-limited to 5 requests per minute per client. A stock backend never issues these tokens because `forgot-password` stays 503. |
| `POST auth/forgot-password-otp` | Welcome **Forgot your password?** path. Body `{ "email" }`. Sends a 6-digit OTP via `EmailTransport` (Amazon SES is tried first when `AWS_SES_REGION` or `AWS_DEFAULT_REGION` is set, then SMTP). Missing email → 400. When `email` is present, always returns 200 (`If the email is registered, a reset OTP has been sent.`) unless the per-email cap is hit (3 OTP requests per hour → 429). Also limited to 5 requests per minute per client. |
| `POST auth/reset-password-otp` | Welcome path. Body `{ "email", "otp", "new_password" }`. The OTP is 6 digits with a 10-minute TTL. Password minimum 8 characters. Missing fields or an invalid / expired OTP → 400. Rate-limited to 10 requests per minute per client. |

Welcome's **Forgot your password?** uses the OTP pair (`forgot-password-otp` /
`reset-password-otp`). The JWT-token pair (`forgot-password` /
`reset-password`) is present in the handler but is not a working operator
path until something injects Flask-Mail `MAIL`; SMTP/SES configure
`EmailTransport` only.

### Monitoring And Observability

GET endpoints. Source: `packages/core/core/src/flinttrade_core/monitoring_routes.py`,
`health_routes.py`, `infra_routes.py`, and the scoped audit/activity routes in
`packages/core/data/src/flinttrade_data`.

The terminal has two development proxy namespaces:

- backend `/api/v1/*` routes are requested as `/ft-api/api/v1/*`;
- backend `/v1/admin/*` routes are requested as `/ft-api/v1/admin/*`.

| Endpoint | Purpose |
|---|---|
| `/api/v1/health` | Aggregated backend health used by the Settings monitoring panel. |
| `/api/v1/traffic/stats` | Request count, request rate, error rate, average latency, and top paths. |
| `/api/v1/traffic/recent` | Recent request records for operator forensics. |
| `/api/v1/latency/stats` | Per-broker order latency percentiles. Fed by the gated order dispatch, which records each order's round-trip latency. |
| `/api/v1/latency/recent` | Recent latency records. |
| `/api/v1/reconciliation/outcomes` | Unresolved broker-write outcomes, including the exact selector, business date, non-secret persisted intent, fresh-snapshot evidence and any retryable `PENDING_AUDIT` or `PENDING_ROUTER_CLEAR` decision. Requires an authenticated session with `admin.observability.read`; results and remaining-outcome counts are filtered through the current router's account ACL. |
| `/api/v1/reconciliation/outcomes/<attempt_id>/resolve` (**POST**) | Record `confirmed_applied`, `confirmed_not_applied`, or basket-only `confirmed_partial` after broker verification. Requires an authenticated, PIN-unlocked Live JWT, session scope `admin.observability.run`, current-router selector ACL, exact `CONFIRM <APPLIED\|NOT_APPLIED\|PARTIAL> <broker>:<account>:<attempt>` confirmation, a newly adopted exact-selector reconciliation generation, and a durable hash-chained audit receipt. Snapshots are monotonic; same-time conflicts and malformed reports fail closed, and historical observations remain evidence. Applied placement IDs must be first observed after invocation and match every persisted material identity field; basket requests map applied IDs to `broker_order_item_indexes` and partition all remaining children in `not_applied_item_indexes`. Modify and cancel recovery require operation-specific evidence. A `PENDING_AUDIT` retry requires newer evidence, archives the prior revision and receives a new resolution ID; a `PENDING_ROUTER_CLEAR` retry resumes the committed decision without another broker read. Success and structured-error responses carry the exact attempt and canonical decision; the terminal runtime-validates identity, status and primitive types before updating state. Ambiguous and unsupported cases remain blocked; this route performs no broker write. |
| `/health`, `/health/detail` | Process health. Not public: a session JWT or `FLINTTRADE_API_KEY` is required. `/health` returns `status` (`healthy`, `degraded`, or `unhealthy`) and `timestamp`. `/health/detail` includes per-check detail. |
| `/healthz`, `/readyz` | Public process probes. The body is status only: `/healthz` is HTTP 200 `{"status": "ok"}`; `/readyz` is HTTP 200 `{"status": "ready"}` or HTTP 503 `{"status": "not_ready"}`. Signed-out probes use these, not `/health`. |
| `GET /api/v1/ping` | Process liveness. The body includes Live-facing `laya`, sidecar `laya_practice`, and `laya_live_qualified`. |
| `/v1/admin/system` | CPU, memory, disk, network, uptime, and process metrics for the Admin system panel. |
| `/v1/audit/*` | Scoped audit trail (`admin.audit.read` where required). |
| `/api/v1/admin/activity` | Operator activity feed. |
| `/api/v1/audit/logs` | Audit-log read on the operations blueprint (not `/v1/operations/…`). |

`GET /api/v1/ping` is the FlintTrade process probe, not the OpenAlgo
passthrough `ping` (POST). It is on the public allowlist. The
response is JSON
`{"status": "ok", "timestamp": "<ISO8601 IST>", "laya": "ready"|"degraded"|"down", "laya_practice": "ready"|"degraded"|"down", "laya_live_qualified": true|false, "laya_reason": "<code>|null", "laya_port": 8000, "laya_download_bytes": "<int>|null", "laya_download_total": "<int>|null"}`.
`laya` is the Live-facing status. `laya_practice` is the sidecar status the
Practice chip shows. `laya_live_qualified` is true only when a qualification
record covers the pin. `laya_reason` is one of `not_started`, `stopped`,
`port_in_use`, `still_loading`, `downloading`, `download_failed`,
`unreachable`, `wrong_revision`, `unverified`, `key_rejected`, or `key_missing`, or
`null` when Ready or Degraded has cleared it. `identity_absent` is not a
`laya_reason`. While `laya_reason` is `downloading`, `laya_download_bytes`
and `laya_download_total` are the live byte counts; otherwise both are
`null`. Chip labels are Not started, Stopped, `Port <n> in use`,
Still loading, Downloading the model · 1.2 of 3.4 GB, Can't download the
model, Unreachable, Can't verify the model, Wrong model version,
Can't reach Laya, and The Laya API key file is missing. A health check does not replace `key_missing` with Not started. `<n>` is `laya_port`. Tooltips for `not_started`,
`stopped`, `port_in_use`, `still_loading`, and `unreachable` are the label
followed by `. Next: python -m flinttrade_core.laya_runtime start`.
`downloading` has no tooltip and no Next line. Its status word is Down,
not Still loading, and the chip text is live progress such as
"Downloading the model · 1.2 of 3.4 GB". `download_failed` uses the same
status word Down. Orders for both are refused with
"Laya is Down. New orders are paused until it's Ready. You can still close positions." The `download_failed`
tooltip is "Check your connection, then Start Laya again." The
`unverified` tooltip is "The installed model couldn't be checked against
the pinned version. Restart Laya. If it keeps happening, reinstall it."
That code applies when this start did not download. A failed download,
including one over an older unverified snapshot, is `download_failed`
("Can't download the model").
The `wrong_revision` tooltip is "Laya is running a different model than
FlintTrade expects." That code is only a real mismatch: a complete
download whose files do not match the pin, a snapshot already on disk
that this start is not replacing, or a running sidecar that reports
another revision or digest. A dropped connection, a partial download, or
a failed download or swap, including one that puts the previous
checkpoint back, is `download_failed`, not this code. The `key_rejected`
tooltip is "Laya restarted with a new key. Reconnecting…" The chip stays
Down and orders are refused. When a place is refused because Laya cannot
be reached, or because it rejects the key, the chip updates on that same
order: Unreachable, or Can't reach Laya. Every chip-Down refusal reads
"Laya is Down. New orders are paused until it's Ready. You can still close positions." When the chip is Ready
and a single decision carries no proof, place returns `laya_unverified`
and "Not placed. Laya's decision couldn't be verified. Try again." On each
sidecar start FlintTrade hashes `model.safetensors` and each file in
`[checkpoint.manifest]` before launch. That manifest pins
`rl_agent_config.json`, `encoder/config.json`,
`tokenizer/tokenizer_config.json`, and `tokenizer/tokenizer.json` by
sha256, beside the `[checkpoint]` `revision` and weights sha256. The runtime record holds
the sha256, pid, and start token, and each file's inode, size, and
modification time (`<workspace>/runtime/laya/verification.json`, with the
token and pid also in `run.json`). When the files are already on disk and this start is not replacing them,
a missing pinned file, a shard index, or any extra weights file or other
file the launcher could read is `unverified` ("Can't verify the model")
and the sidecar does not start. A changed byte in a snapshot that this
start is not replacing is `wrong_revision` ("Wrong model version") and the
sidecar does not start. A changed byte in the runtime checkpoint starts
the download below; the sidecar does not start on that tree. Laya does
not reach Ready in these cases. `start` downloads the pinned revision
into `<workspace>/runtime/laya/staging` when the weights file or a
manifest file is not on disk, and when the runtime checkpoint is on disk
but its hashes are not the pin. The download asks for the commit in
`[checkpoint] revision`, not the default branch, and it does not start
the sidecar. That download sets `HF_HOME` to
`<workspace>/runtime/laya/hf-home` and `HF_HUB_DISABLE_XET=1`, so transfer
logs stay out of the shared cache. The model is about 2.37 GB, and that
size is reported once. While it runs,
including a pin change, the reason is
`downloading` ("Downloading the model · 1.2 of 3.4 GB"), the status word
is Down, and there is no Updating label. When no checkpoint is already
there, a full match renames staging onto `checkpoint`. When a checkpoint
is already there, the current copy stays in place until the new files
match. On a full match that checkpoint is renamed aside to
`checkpoint.old-<random>` in the same runtime directory, staging is
renamed onto `checkpoint`, then the old copy is deleted. The sidecar is
not started until the move, and that launch keeps hub access off. If that
second rename fails, the old checkpoint is renamed back and the reason is
`download_failed`, not `wrong_revision`. A complete download whose files
do not match the pin is `wrong_revision`, staging is deleted, and the
checkpoint already on disk stays. An extra loadable file in a complete
download is `unverified`. A dropped connection, a partial or missing
file, or a read error is `download_failed`. The sidecar does not start on
files that do not match the pin. If the download does not finish, the reason is `download_failed`, not
`wrong_revision` and not `unverified`, whatever older snapshot is on
disk. `unverified` stays when this start did not download. A snapshot
already on disk is `wrong_revision` only when this start did not
download. Those failures delete the staging directory and leave the
shared model cache alone. Leftover staging directories and
`checkpoint.old-*` copies are removed at the start of `start` once a
checkpoint is in place, with no chip change and no message. If
`checkpoint` is missing and one or more `checkpoint.old-*` copies remain,
the last `checkpoint.old-*` name is restored onto `checkpoint` and any
other aside copies are removed. If that restore fails, the aside copy stays where it is and
that cleanup is skipped. A copy that was restored is then checked against
the pin. If it does not
match, the sidecar does not start on it; the pinned download runs
instead, and a failed download leaves `download_failed` with that copy
still on disk.
The download log line is `laya download repo=<repo> revision=<revision>`.
A verified boot sets
`LAYA_WEIGHTS_PATH` to that hashed weights file. A model already in the
standard Hugging Face cache is accepted. When that file is the cache
symlink (`snapshots/<revision>/model.safetensors` into `blobs/`), the
launch path is the snapshot file, not the blob. A blob path is still
refused. The boot runs offline
(`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`). It does not pass a repo id
or a revision. When the sidecar health document leaves the revision empty,
FlintTrade fills the pinned revision from the verified manifest, so the
chip leaves Still loading. The launch log line is
`laya weights path=<path> sha256=<digest>`. Those identity values are
rechecked, without hashing again, when Laya reports Ready and on each
watch tick, about every 1.5 seconds. A mismatch is `unverified`
("Can't verify the model"). The log line is
`laya weights path=<path> changed=<field>`, and `<path>` is the file that
changed. The same watch reads the pid file (`runtime/laya/sidecar.pid`),
the key file (`runtime/laya/api.key`), and the runtime record, so a
command-line stop or start, or a key rotation, is reconciled by that
watch. The desk polls `GET /api/v1/ping` every 1.5 seconds. That ping
reconciles the pid, the key, and the runtime record the same way an
order does, so the chip and the order gate read the same state. A stop
or a start shows on the chip by the next 1.5-second check. After Start Laya,
until the ping confirms the new state, the chip says Checking in the
neutral colour and the popover says Checking Laya…. It does not show a
stale Ready during that wait. An admitted place while the chip is not
Ready or Degraded also shows Checking until the next ping. A confirmed first load still says Still
loading. A place refused with exactly "Laya is Down. New orders are paused until it's Ready. You can still close positions." sets the chip to Down on that response. A non-exit order is HTTP 403. The refusal
line is unchanged. Every `stop` deletes the runtime record, as does a start
that fails after it was written. A record from an earlier run is rejected.
A decision without `revision` or `sha256` is checked against that record
for both admitted and clamped orders. The decision log is
`<workspace>/runtime/laya/decisions.jsonl`. It stores `proof=decision` or
`proof=runtime`. An admitted Practice place with an empty note skips the
model and writes one line, `effect=clamp` with `failure=note_absent` and
no proof, including when the quantity already fits. When this run's
record stood in, each model allow keeps its own `effect=allow`
`proof=runtime` line. There is no dedupe. A model decision with no proof is still
refused. `laya_port` is the sidecar
port (`LAYA_PORT`, default 8000). Laya starts Down. A ping does not invent Ready.
`GET /health` records Ready, Degraded, or Down from the opt-in sidecar when
one is registered. With no sidecar, that probe leaves the stored status alone.
Live stays unqualified until a qualification record matches the pinned
revision and policy, so a Practice Ready probe still publishes `down` on
`laya` and `ready` on `laya_practice`. Clients must not treat a missing or
omitted `laya` as Ready; the desk uses `laya ?? "down"`. The chip tooltip
and the popover line are "Not qualified for Live" when
the sidecar is Ready or Degraded and Live is not qualified. During the
first load `laya_reason` is `still_loading` and the chip says "Still loading".
Orders stay refused with the Down sentence. A port clash is `port_in_use`.

### Errors (`/ft-api/v1/errors`, `/ft-api/v1/changelog`)

| Endpoint | Purpose |
|---|---|
| `errors` | Front-end error reporting sink. The terminal posts unhandled errors here. |
| `changelog` | Read the bundled changelog.md programmatically (used by the "What's new" widget). |

### Support diagnostics (`/ft-api/v1/support/*`)

Source: `packages/core/core/src/flinttrade_core/support_routes.py`. The route is
covered by the backend's global authentication and additionally requires the
`admin.errors.read` session scope. Responses use `Cache-Control: no-store`.

| Endpoint | Purpose |
|---|---|
| `support/diagnostics` (**GET**) | Return bounded app/runtime metadata plus at most 50 aggregated recent error groups. The DuckDB projection excludes raw bodies, messages, tracebacks, entry/user ids and account identifiers; concrete paths are reduced to registered route patterns or safe client-screen names. |

There are roughly 20 FlintTrade-specific endpoint families across the
13 Python packages. The complete list of registered Flask blueprints
appears in `packages/core/core/src/flinttrade_core/app.py` — search for `register_blueprint`.

---

## 3. WebSocket (port 8765)

The WebSocket runs on the OpenAlgo side. FlintTrade's terminal connects
via the Vite dev proxy (`/ws`) in development and via the configured
host in production.

### Modes

| Mode | Code | Payload shape |
|---|---|---|
| **LTP** | 1 | `ltp`, `timestamp`, `symbol`, `exchange` |
| **Quote** | 2 | LTP fields + `open`, `high`, `low`, `close`, `volume`, `oi` |
| **Depth** | 4 | Quote fields + `depth.bids[]`, `depth.asks[]` (50 levels in v2; was 5 in v1) |

> **Note.** OpenAlgo v1 used mode `3` for depth. v2 renamed it to `4`
> and increased the level count from 5 to 50. FlintTrade's client
> negotiates v2 by default.

### Handshake

```json
{ "action": "authenticate", "api_key": "<OPENALGO_API_KEY>" }
```

The server responds with `{"status":"ok"}` on success.

### Subscribe

```json
{
  "action": "subscribe",
  "symbols": [
    { "symbol": "NIFTY", "exchange": "NSE_INDEX" }
  ],
  "mode": "LTP"
}
```

### Tick frame

```json
{
  "type": "market_data",
  "data": {
    "symbol": "NIFTY",
    "exchange": "NSE_INDEX",
    "ltp": 24850.55,
    "timestamp": 1716180003.471
  }
}
```

### Heartbeat

The terminal WebSocket client
(`packages/apps/terminal/src/services/websocket.ts`) sends a `ping`
every 30 seconds and treats the connection as dead if no `pong` arrives
within **10 seconds**, then reconnects with exponential back-off. The
Python `OpenAlgoClient` is REST-only and does not implement this
heartbeat.

---

## 4. Authentication

### JWT (FlintTrade backend)

`require_auth` accepts a session JWT **or** an API key on every mounted
route that is not on the public allowlist in
`flinttrade_core.public_routes`. That allowlist is the only exemption, and
it is checked before the handler runs, so a new route is protected until
it is added there. `OPTIONS` is always public. `HEAD` follows `GET`. The
SPA shell (`/` and `/<path:path>`) is public only for a non-API path;
unknown `/v1/`, `/api/`, and `/ft-api/` paths that fall through stay
authenticated. Broker account-management writes still require the
operator's session JWT after that check.

A non-public route behaves as follows.

| Credential | Result |
|---|---|
| `Authorization: Bearer` session JWT (`type` `session`) | The global check allows the request. Handlers may still require a mode, a Live unlock, or an operator scope. |
| `X-FlintTrade-Token` session JWT (`type` `session`) | The global check allows the request. An API key in this header does not. Handlers may still require a mode, a Live unlock, or an operator scope. |
| `X-API-Key`, or the same Bearer value, matching `FLINTTRADE_API_KEY` | The global check allows the request. `OPENALGO_API_KEY` is the fallback when `FLINTTRADE_API_KEY` is unset. An API key is not a session: it has no mode and no account epoch. Order place still requires a JWT mode claim. Practice restore still requires a Practice session. Account recovery on a finished account still requires a session. |
| Missing, revoked, or non-matching credential | HTTP 401 `{"status": "error", "message": "Unauthorized"}`. When an API key is configured, a presented credential that fails is recorded as an auth failure. When no key is configured, a missing session is still HTTP 401 and is not recorded as a ban event. |

The public allowlist, method and rule, is exactly:

| Method | Rule |
|---|---|
| GET | `/healthz` |
| GET | `/readyz` |
| GET | `/api/v1/ping` |
| GET | `/v1/auth/status` |
| POST | `/v1/auth/login` |
| POST | `/v1/auth/setup` |
| POST | `/v1/auth/setup/resume` |
| POST | `/v1/auth/setup/vault` |
| POST | `/v1/auth/setup/reset` |
| POST | `/v1/auth/setup/regenerate-2fa` |
| POST | `/v1/auth/forgot-password` |
| POST | `/v1/auth/reset-password` |
| POST | `/v1/auth/forgot-password-otp` |
| POST | `/v1/auth/reset-password-otp` |
| POST | `/v1/errors` |
| POST | `/api/v1/errors` |
| GET | `/v1/changelog` |
| GET | `/v1/docs/search` |
| GET | `/v1/docs/document` |
| GET | `/v1/docs/changelog` |
| GET | `/v1/config/openalgo` |
| POST | `/v1/config/openalgo` |
| POST | `/v1/test-connection` |
| POST | `/v1/webhook/<source>` |
| POST | `/v1/webhook/<source>/<path:webhook_id>` |
| POST | `/csp-report` |
| GET | `/v1/auth/oauth/callback` |
| GET | `/api/v1/native/oauth/callback` |
| POST | `/api/v1/native/postbacks/<adapter_id>` |

`POST /v1/auth/setup/resume` is on that list. A reload mid-setup proves
the password (and the authenticator code once one is enrolled) and
receives a setup-session JWT. It does not require a session that is
already in the browser. `POST /v1/auth/setup/complete` is not on the
list: it needs the operator's session JWT. `POST /v1/auth/setup/vault`
is on that list so the setup wizard can reach it, and the handler still
requires the setup-session JWT and rejects a daily-login token. `POST /v1/auth/setup/reset` and `POST
/v1/auth/setup/regenerate-2fa` stay reachable during first-run. Once an
authenticator is enrolled, account recovery requires an active session,
the password, and the current authenticator code (`totp_code`). A
signed-out reset or authenticator change on a finished account returns
`Sign in to reset this account. You'll need your password and authenticator code.`
when an authenticator is enrolled, and `Sign in to reset this account. You'll need your password.`
when it is not. The body includes `authenticator_enrolled`.
A successful wipe bumps the account epoch. `POST /v1/auth/totp/enable`,
`/pin`, `/pin/set`, `/mode`, and `/logout` are not on the list: they need
an existing session JWT and return 401 without one. `POST /csp-report` is
public because the browser cannot attach a session. The shared
content-type gate accepts `application/csp-report` and
`application/reports+json` (and any type whose name contains `json`).
The handler reads a legacy `csp-report` object or a Reporting API list
and answers HTTP 204. A non-empty body of any other type is HTTP 415
`Content-Type must be application/json` before the handler runs.

`GET /healthz` and `GET /readyz` are public and return only a status.
`GET /api/v1/ping` is the desk liveness probe and stays public; its body
is status, timestamp, and Laya state, with no version, path, or config.
`GET /health`, `GET /health/detail`, and `GET /api/v1/health` stay behind
a session. A session is bound to the operator and an account epoch stored
with the account. Reset, and creating the operator again, issue a new
epoch, so earlier session tokens are refused on every route, including
the OpenAlgo connection. Coverage is not limited to `/ft-api/v1/*` — many
operator routes live under `/api/v1`.

```
Authorization: Bearer <jwt>
```

### Token claims

The JWT carries three claims you care about:

| Claim | Meaning |
|---|---|
| `sub` | User identifier. |
| `exp` | Expiry timestamp. **Every token expires at 8 AM IST the next day.** Refresh by signing in again. |
| `mode` | One of `explore` (example data; not a menu Mode), `practice`, `live`. Server-enforced on every order path. Password login and account setup default to `practice`. |
| `live_mode_unlocked` | `true` on a Live session issued by the Live switch `POST /v1/auth/live`. Required for live order paths. Quick Unlock (`POST /v1/auth/pin`) keeps it when that session is already Live, and leaves it false on every other session. Both calls revoke the presented `jti` and return a new token. |
| `oid`, `epoch` | Operator id and account epoch. Reset and operator re-creation bump the epoch, which ends other sessions. |

A `jti` (JWT ID) is included so the server can revoke individual tokens
when the user logs out or switches mode. The revocation blocklist lives
in `packages/core/core/src/flinttrade_core/auth_state.py`.

### Backend API Keys

FlintTrade backend routes accept `X-API-Key` against `FLINTTRADE_API_KEY`
when configured. `OPENALGO_API_KEY` is retained as a compatibility fallback,
but it is no longer required for native FlintTrade Practice or example-data flows.
When neither key exists, non-public routes still require a session JWT,
including on loopback. Setup, login, and the other allowlisted routes stay
reachable so a fresh install can finish first-run configuration. Broker
account-management **writes** (connect/remove/re-authenticate a broker,
credential capture, OAuth start, rate-limit and rotation config) additionally
require the operator's logged-in session JWT. After that JWT check, production
mutations still return `503` `broker_account_cutover_unavailable` until Task
9D. The PIN quick-unlock likewise requires an existing session (the PIN is a
re-authentication factor, never a standalone login).

The OpenAlgo-compatible passthrough still uses OpenAlgo's own API key. The app
reads that key from Setup/Settings-backed workspace config first, with
`OPENALGO_API_KEY` retained only as an advanced dev/server fallback, then
forwards it as the `X-API-KEY` header by `OpenAlgoClient` only for
OpenAlgo/live bridge calls.

---

## 5. Rate limits

Source: `packages/core/core/src/flinttrade_core/openalgo_client.py` (`_RateLimiter`).

| Category | Limit |
|---|---|
| **Orders** | 10 / second |
| **Smart orders** | 2 / second |
| **General API** | 50 / second |

Rate limits are enforced in the client before requests leave FlintTrade.
If you exceed a limit, `await client.place_order(...)` blocks until the
window opens; you do not get a 429 from the broker.

---

## 6. Mode system

`explore | practice | live` — server-side JWT-claim enforcement. The claim `explore` is example data. Operators see **Example**, not a Mode in the menu. The
guard lives at `packages/services/engine/src/flinttrade_engine/mode_guard.py`. Every order-path
endpoint asks the guard whether the current JWT permits live orders;
the guard returns one of three verdicts:

| Verdict | Behaviour |
|---|---|
| `explore` | Example data. `POST /api/v1/orders/place` and the shared order dispatcher both reject the order with HTTP 403 and `code: "mode_blocked"`. The message on both is `Orders are not available for Example. Switch to Practice or Live to trade.` No broker is contacted. |
| `practice` | Route supported single-leg order flows to the Practice fill path; never touch OpenAlgo or a broker. Practice **place** is admitted by `Laya.admit` before that path. A Down refusal or a quantity clamp returns before any fill. Advanced executor-direct routes that do not yet have Practice parity fail closed with `practice_unsupported`. A Practice close is an opposite order on `POST /api/v1/orders/place`. A Practice bracket is HTTP 403 `practice_unsupported`. |
| `live` | Require a JWT with `live_mode_unlocked=true`. The submit routes are `POST /api/v1/orders/place`, `POST /api/v1/orders/<broker>/place`, `POST /api/v1/positions/exit-all`, and `POST /api/v1/orders/bracket` when the body has exactly one stop-loss or one target. Both place routes, and each bracket leg, run `Laya.admit` before SafetySystem, then the gated `BrokerRouter`. Every order FlintTrade submits goes through admission when it's placed, except a GTT body (`"variety": "gtt"`, any case or separator spelling), which is HTTP 422 `gtt_unsupported` on those submit routes before Laya, SafetySystem, and any broker call. Exit-all records a server reduce-only proof before `exit_all_positions`. Modify and cancel go through the gated router without this place admission. `cancel-all` only cancels, through `cancel_all_orders`, and does not create an order. `POST /api/v1/orders/forever`, basket, split, options-strategy, and conditional-trigger place return HTTP 501 and do not place. `gtt-*` returns HTTP 501 and does not forward to OpenAlgo. |

`POST /v1/auth/mode` accepts **only** a downgrade to `practice`. That call
issues a fresh JWT and revokes the previous `jti`. Any other value,
including `explore`, `live`, and a missing `mode`, returns HTTP 400 before
the current session is revoked, with message `Only a downgrade to practice
is allowed here. Switch to Live via POST /v1/auth/live with PIN
verification.` Live is entered only through `POST /v1/auth/live`, with the
6-digit PIN, after the authenticator is enrolled (`totp_enabled`). Without
enrolment that call refuses 403 with `code: "totp_required"`. Quick Unlock
(`POST /v1/auth/pin`) reopens the Mode already on the session. Its body is
`{ "pin" }`. It keeps that Mode.

Authoritative coverage: `packages/core/core/tests/test_order_routes.py` asserts
Example-data rejection, Practice routing, and Live gate / fail-closed
behaviour. Engine routes that bypass the core order proxy use
`packages/services/engine/src/flinttrade_engine/mode_guard.py`.

---

## 7. Example request / response

The five most-used endpoints, each shown twice: a `curl` command for
bash/zsh, and an `Invoke-RestMethod` equivalent for Windows PowerShell
(where `curl` is an alias for `Invoke-WebRequest`, `\` is not a line
continuation, and environment variables are read as `$env:NAME`).

### 7.1 Exercise the practice order path

This example is for a locally issued **Practice-mode** FlintTrade session JWT.
Place is admitted before the sandbox. Laya starts **Down**, so a Practice
place while Down returns HTTP 403 `laya_denied` with "Laya is Down. New orders are paused until it's Ready. You can still close positions." and the sandbox is not called. That sentence
is the same in Live. A Live place while Laya is Ready or Degraded, with no
matching qualification record, returns "Laya isn't qualified for Live yet.
Practice orders are available." A Practice refusal never says Live. A quantity
greater than the allowed quantity returns HTTP 409 `laya_clamp` and places
neither size. The clamp message is "Not placed. Laya allows up to N."
Place N sends that quantity. On Order Pad, "Review Practice order" then
shows the placed quantity. Place 1 on "Not placed. Laya allows up to 1."
places, because that request
is already at the allowed quantity. A request that is already at the
allowed quantity is an allow. An empty note is
not a hard reject: Practice returns that clamp when the requested quantity
is greater than the tighter ceiling, and Live returns HTTP 403
`laya_denied` with "Laya is uncertain. Live stays closed." The sandbox body below is the response when admission allows the
requested quantity. The call does not send an order to OpenAlgo or any broker.
Do not use the OpenAlgo passthrough endpoint as an example for live broker
execution. Live operator place uses this order proxy after a Live-mode JWT
(`POST /api/v1/orders/place` and the routed place dispatcher). The server
admits that place through `Laya.admit` as source `operator`, then the
safety gate, the account ACL check, and BrokerRouter. Automate place uses
the same admit verdict before SafetySystem and `gate_order`, as source
`automate` on strategy dispatch and webhook place. It does not use this
HTTP place route. Example-data place stays `mode_blocked` and is not an
admission result.

```bash
curl -X POST http://127.0.0.1:5100/api/v1/orders/place \
  -H "Authorization: Bearer $FLINTTRADE_PRACTICE_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "NIFTY",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 50,
    "price": 0,
    "product": "MIS",
    "order_type": "MARKET"
  }'
```

```powershell
$params = @{
  Method      = "Post"
  Uri         = "http://127.0.0.1:5100/api/v1/orders/place"
  Headers     = @{ Authorization = "Bearer $env:FLINTTRADE_PRACTICE_JWT" }
  ContentType = "application/json"
  Body        = '{
    "symbol": "NIFTY",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 50,
    "price": 0,
    "product": "MIS",
    "order_type": "MARKET"
  }'
}
Invoke-RestMethod @params
```

Sandbox response shape — the handler returns the sandbox dict as-is
(`COMPLETE` / `PENDING`). A `REJECTED` sandbox result is HTTP 400 with
`status: "error"`. There is no `status: "success"` envelope on this path.

```json
{
  "order_id": "sandbox-...",
  "status": "COMPLETE",
  "message": "Paper order executed: BUY 50 NIFTY @ 0.00"
}
```

### 7.2 Get a quote

```bash
curl -X POST http://127.0.0.1:5000/api/v1/quotes \
  -H "X-API-KEY: $OPENALGO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "symbol": "NIFTY", "exchange": "NSE_INDEX" }'
```

```powershell
$params = @{
  Method      = "Post"
  Uri         = "http://127.0.0.1:5000/api/v1/quotes"
  Headers     = @{ "X-API-KEY" = $env:OPENALGO_API_KEY }
  ContentType = "application/json"
  Body        = '{ "symbol": "NIFTY", "exchange": "NSE_INDEX" }'
}
Invoke-RestMethod @params
```

Response:

```json
{
  "status": "success",
  "data": {
    "symbol": "NIFTY",
    "exchange": "NSE_INDEX",
    "ltp": 24850.55,
    "open": 24820.10,
    "high": 24895.25,
    "low": 24788.40,
    "close": 24850.55,
    "volume": 0,
    "timestamp": "2026-05-20T14:23:23+05:30"
  }
}
```

### 7.3 Read the position book

```bash
curl -X POST http://127.0.0.1:5000/api/v1/positionbook \
  -H "X-API-KEY: $OPENALGO_API_KEY"
```

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5000/api/v1/positionbook" -Headers @{ "X-API-KEY" = $env:OPENALGO_API_KEY }
```

Response is a list of `Position` records — symbol, exchange, product,
quantity, average price, last price, P&L.

### 7.4 Pull an option chain

OpenAlgo v2.0.2.2 requires `underlying`, `exchange`, and `expiry_date`
(`DDMMMYY`). FlintTrade's Python client and terminal helpers refuse a
missing `expiry_date` before posting. The raw HTTP examples below still
cross the network; OpenAlgo then rejects a body that omits `expiry_date`.

```bash
curl -X POST http://127.0.0.1:5000/api/v1/optionchain \
  -H "Content-Type: application/json" \
  -d "{\"apikey\": \"$OPENALGO_API_KEY\", \"underlying\": \"NIFTY\", \"exchange\": \"NFO\", \"expiry_date\": \"26MAR26\"}"
```

```powershell
$params = @{
  Method      = "Post"
  Uri         = "http://127.0.0.1:5000/api/v1/optionchain"
  ContentType = "application/json"
  Body        = (@{
    apikey = $env:OPENALGO_API_KEY
    underlying = "NIFTY"
    exchange = "NFO"
    expiry_date = "26MAR26"
  } | ConvertTo-Json)
}
Invoke-RestMethod @params
```

Response: nested object keyed by strike, with CE and PE legs each
containing LTP, OI, volume, IV, and Greeks.

### 7.5 Compute Gamma Exposure (FlintTrade-side)

```bash
curl -X POST http://127.0.0.1:5100/api/v1/gex \
  -H "Authorization: Bearer $FLINTTRADE_JWT" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"NIFTY","exchange":"NFO","expiry":"28MAY26"}'
```

```powershell
$params = @{
  Method      = "Post"
  Uri         = "http://127.0.0.1:5100/api/v1/gex"
  Headers     = @{ Authorization = "Bearer $env:FLINTTRADE_JWT" }
  ContentType = "application/json"
  Body        = '{"symbol":"NIFTY","exchange":"NFO","expiry":"28MAY26"}'
}
Invoke-RestMethod @params
```

Successful responses include `status`, `symbol`, `exchange`, `expiry`,
`spot`, `lot_size`, `is_sample_data`, and a `data` object with
`underlying`, `spot_price`, `atm_strike`, `strikes`, `net_gex`,
`total_call_gex`, `total_put_gex`, `dealer_zone`, and
`gamma_flip_strike` (the last is `null` unless a true flip level was
computed). Via the Vite proxy the same route is
`POST /ft-api/api/v1/gex`.

---

## 8. Error responses

Every endpoint returns one of two shapes.

**Success:**

```json
{ "status": "success", "data": { … } }
```

**Error:**

```json
{ "status": "error", "message": "Human-readable explanation.", "code": "optional_code" }
```

Most handlers return only `status` + `message`. The core
`/api/v1/orders/*` proxy rejects a sample-data session (`/orders/place`, modify,
cancel, `cancel-all`, and the other verbs that share that mode gate)
with HTTP 403 and `code: "mode_blocked"`. The message is
`Orders are not available for Example. Switch to Practice or Live to trade.`
That refusal runs before `Laya.admit`.
Core operator place, after the mode guard, admits before SafetySystem
and before the Practice sandbox. A client `source` field is ignored, so
the request cannot present itself as chat or as automate. A refusal is
HTTP 403 `laya_denied`. A quantity clamp is HTTP 409 `laya_clamp` and
places neither size. It applies only when the requested quantity is
greater than the allowed one. A decision with no proof, while the chip
can stay Ready, is HTTP 409 `laya_unverified`.
`http_status` is not part of the JSON body. A Live JWT without PIN unlock
on that same proxy is still message-only: HTTP 403 with "Live mode not unlocked —
verify PIN first". A `code` field is also emitted on
`mode_guard`-decorated engine routes (brackets and other
executor-direct paths), on `POST /api/v1/telegram` sample-data refusals,
on `POST /api/v1/ditto/mirror/start` and
`POST /api/v1/ditto/kill-all` sample-data refusals, and on
`POST /api/v1/cron/jobs/<name>/pause` and `…/resume` sample-data refusals.
Not every endpoint emits `code`:

| Code or status | Meaning |
|---|---|
| `mode_blocked` | A sample-data session (or another blocked session) tried a blocked action — HTTP 403. Covers the core `/api/v1/orders/*` proxy refusals, `mode_guard` order-capable engine routes, FlintTrade `POST /api/v1/telegram` when JWT `mode` or `X-FlintTrade-Mode` is `explore`, `POST /api/v1/ditto/mirror/start` and `POST /api/v1/ditto/kill-all` sample-data refusals, and `POST /api/v1/cron/jobs/<name>/pause` plus `…/resume` sample-data refusals (same header/claim gate). Example-data place stays on this code, with message `Orders are not available for Example. Switch to Practice or Live to trade.` |
| `laya_denied` | Operator place was refused by `Laya.admit` before SafetySystem or the Practice sandbox — HTTP 403. Body: `status: "error"`, `code: "laya_denied"`, `message` and `reason` (the same server text). The desk shows that `reason` under the denial on a line named Laya decision, inside one alert (`role="alert"`), the only live region. That line is not its own status. Down is "Laya is Down. New orders are paused until it's Ready. You can still close positions." and omits `limits`. Unqualified Live, while Ready or Degraded, is "Laya isn't qualified for Live yet. Practice orders are available." An empty Live note is "Laya is uncertain. Live stays closed." Other denials include `limits.max_quantity`. There is no `applied_quantity`. |
| `laya_unverified` | One decision carried no proof. The chip can stay Ready. This is not a chip reason — HTTP 409. Body: `status: "error"`, `code: "laya_unverified"`, `message` and `reason` both "Not placed. Laya's decision couldn't be verified. Try again." The decision log records `identity_absent` and does not store `proof`. There is no `limits` field. |
| `laya_clamp` | Operator place was not placed — HTTP 409. The requested quantity is greater than the allowed quantity. Body: `status: "error"`, `code: "laya_clamp"`, `message` (`Not placed. Laya allows up to <applied_quantity>.`), `reason`, `limits.max_quantity`, and `applied_quantity`. An empty Practice note that reduces the quantity sets `reason` to "Laya is uncertain. Quantity stays inside the tighter limit." A ceiling clamp can leave `reason` empty. Nothing is placed until the desk sends that quantity through admit again. Place 1 on "Not placed. Laya allows up to 1." is admitted, because that request is already at the allowed quantity. An allow then continues into SafetySystem and gate_order. A request already at the allowed quantity is an allow, including when an uncertain note tightened the ceiling without shrinking the number. Live uncertain, including an empty note, is `laya_denied`, not this code. |
| `exit_pending` | A second reduce-only exit on the same broker account while one of this desk's exits on that contract is still unfilled — HTTP 409. Practice uses this code on the Practice book. On Live it is the code when the broker order book can be read. The Live hold is for that broker account. `message` and `reason` are `Not placed. An exit for <symbol> is already pending. Wait for it to fill, or cancel it and try again.` The Positions row shows **Exit pending**. The label is the symbol, or `this contract` when the symbol is empty. |
| `exit_orders_unreadable` | On Live, that second exit on the same broker account while the broker order book cannot be read — HTTP 409. `message` and `reason` are `Not placed. One exit at a time for <symbol> until your broker's orders load.` The label is the symbol, or `this contract` when the symbol is empty. |
| `gtt_unsupported` | `"variety": "gtt"` (any case or separator spelling) on place, routed place, exit-all, or a bracket — HTTP 422. `message` is `Not placed. GTT orders aren't supported right now.` The refusal is before Laya, SafetySystem, and any broker call. |
| `practice_unsupported` | Practice JWT hit an executor-direct route with no sandbox parity — HTTP 403. |
| `live_locked` | A `mode_guard` Live path requires `live_mode_unlocked=true`, issued by the Live switch `POST /v1/auth/live`. |
| HTTP 429, message `Rate limit exceeded` | FlintTrade `@rate_limit` on the order proxy. No `RATE_LIMIT_EXCEEDED` enum. |
| Safety `message` | A safety layer rejected the order; the message names the layer. There is no `SAFETY_LAYER_BLOCK` code. Operator and automate place reach this only after `Laya.admit` allows the requested quantity. |

Automate place admits before SafetySystem with the same verdict. A webhook
place puts `code`, `reason`, `limits`, and (on a clamp) `applied_quantity`
on the dispatcher result; the webhook HTTP receiver wraps a dispatcher
error as HTTP 422 with that result under `data`. A strategy dispatch
raises the server `message` and does not place the reduced quantity.
Modify, cancel, and cancel-all are not admitted as place. Forever,
basket, split, and conditional-trigger place do not submit.
`POST /api/v1/orders/forever` returns HTTP 501
`Orders are placed through /api/v1/orders/place.` and does not call a
broker. A Live bracket with exactly one stop-loss or one target does
submit on `POST /api/v1/orders/bracket`. A GTT body on place, routed
place, exit-all, or that bracket is HTTP 422 `gtt_unsupported` before
that admission.
Chat is not an admission source.
Details of the place path are in [ORDER_SAFETY.md](ORDER_SAFETY.md).

Auth failures are typically HTTP 401 with a `message` (expired, revoked,
or missing token). Broker-session expiry arrives as the upstream
OpenAlgo/broker error text, not a FlintTrade enum.

---

## 9. Versioning

The HTTP surface uses URL-segment versioning (`/api/v1/`, `/ft-api/v1/`).
Breaking changes go to `/v2/` and the `/v1/` surface stays alive for at
least one minor release. The WebSocket protocol carries a `version` field
on the handshake; current value is `2`.

See [releases/](releases/) for per-version change notes.
