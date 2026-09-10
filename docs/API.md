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
upstream: Dhan + Zerodha. Other brokers respond with a clean 501 that
FlintTrade propagates unchanged.

| Endpoint | Purpose |
|---|---|
| `placegttorder` | Place a single-leg (SINGLE) or two-leg (OCO) GTT trigger. |
| `modifygttorder` | Full-replacement modify of an active trigger by `trigger_id`. |
| `cancelgttorder` | Cancel an active trigger by `trigger_id`. |
| `gttorderbook` | List all live (non-terminal) GTT triggers for the user. |

FlintTrade surfaces these through the safety proxy at
`/api/v1/orders/gtt-{place,modify,cancel}` so the mode gate
(explore / practice / live) and the live-mode JWT unlock are enforced
identically to regular orders.

### Accounts

| Endpoint | Purpose |
|---|---|
| `funds` | Available margin, used margin, cash balance. |
| `orderbook` | All orders for the trading day. |
| `tradebook` | All executed trades. |
| `positionbook` | Open positions (intraday and overnight). |
| `holdings` | Long-term holdings (CNC / delivery). |
| `margin` | Pre-trade margin estimate for a list of positions. |
| `ping` | Health check (POST). |
| `analyzer` | Read sandbox / analyzer mode status. |
| `analyzer/toggle` | Toggle sandbox / live mode. |
| `pnl/symbols` | P&L breakdown per symbol. |

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
| `gex` | Gamma Exposure curve. |
| `iv_smile` | Implied-volatility smile curve. |
| `max_pain` | Max-pain strike calculation. |
| `oi_profile` | Open-Interest profile by strike. |
| `chart` (**GET/POST**) | Chart-preference get/set. |

### Utilities

| Endpoint | Purpose |
|---|---|
| `market/holidays` | Holiday calendar. **POST** with `apikey` and `year` (2020–2050) in the JSON body. Do not call bare `holidays` as the current passthrough path. |
| `market/timings` | Exchange-timing windows. **POST** with `apikey` and `date` in the JSON body. Missing date fails closed. Do not call bare `timings` as the current passthrough path. |
| `telegram/notify` | Send a Telegram message via the OpenAlgo bot (`username` + `message`). If `username` is omitted, FlintTrade uses workspace `openalgo.telegram_username` when set; otherwise the call fails closed. That field is accepted and persisted by `GET`/`POST` `/v1/config/openalgo` or a `workspace.json` edit — not by the Setup/Settings connection form, which only writes `api_key`, `host`, `port`, and `ws_port`. |
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

### Analysis (`/api/v1/*`; Vite proxy `/ft-api/api/v1/*`)

Powered by `packages/services/screener/`. The analysis blueprint mounts at
`/api/v1`, not `/v1`. POST endpoints expect a JSON body (`symbol`,
`exchange`, and `expiry` / `expiry_date` for option-chain tools). GET
endpoints are marked.

| Endpoint | Purpose |
|---|---|
| `gex` (**POST**) | Gamma Exposure dashboard data (alternative to the OpenAlgo passthrough; computed locally on historical chains). |
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
`llm`, `forecast`, `agent_runtime`, and `embedding`.

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

### AI (`/api/v1/ai/*`, `/api/v1/signals/*`; Vite proxy `/ft-api/api/v1/…`)

Source: `packages/services/ai/`. Blueprints mount at `/api/v1`. GET unless
noted. Managed local inference (`/v1/ai/local-runtime`) is the exception —
that blueprint stays under `/v1`.

| Endpoint | Purpose |
|---|---|
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
| `sandbox/order` (**POST**) | Place a paper order. |
| `sandbox/positions` · `sandbox/orders` · `sandbox/pnl` (**GET**) | Book and P&L reads. |
| `sandbox/reset` (**POST**) | Clear all paper data (returns a backup). |
| `sandbox/export` (**GET**) · `sandbox/import` (**POST**) | Export / import sandbox state. |

### Strategies (`/api/v1/strategies/*`; Vite proxy `/ft-api/api/v1/strategies/*`)

Source: `packages/services/engine/src/flinttrade_engine/strategy_routes.py`.
The blueprint mounts at `/api/v1/strategies`. Backed by the
`STRATEGY_RUNNER` + `CRON_SCHEDULER` wired at app creation.

| Endpoint | Purpose |
|---|---|
| `strategies/uploaded` (**GET**) | List uploaded user strategies. |
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
| `trades/journal` (**GET**) | Recorded trades. No params → today; `start_date`+`end_date` → history window across all strategies; `+strategy` → that strategy only. Rows are keyed `timestamp` (ISO, IST), with `symbol`, `action`, `quantity`, `price`, `pnl`, `strategy`, `orderid`. |

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

### Auth (`/ft-api/v1/auth/*`)

JWT-based. Source: `packages/core/core/src/flinttrade_core/auth_routes.py`.

| Endpoint | Purpose |
|---|---|
| `GET auth/status` | First-run probe. Returns `is_setup`, `is_locked`, `has_pin`, and `totp_enabled`. |
| `POST auth/setup` | First-run enrolment. Body `{ "username", "email", "password", "pin"? }`. The server generates TOTP and returns `totp_uri` plus backup codes and an Explore JWT. Authenticator enrolment is optional for Explore and Practice; Live still needs a confirmed authenticator plus PIN. It does not accept a caller-supplied TOTP secret. |
| `POST auth/setup/reset` | Wipe local enrolment so Setup can run again. Body `{ "password" }`, or the account-create setup JWT (lost-QR start-over). Daily-login session JWTs are rejected. |
| `POST auth/setup/regenerate-2fa` | Rotate the login TOTP secret (password re-confirm) and clear `totp_enabled` until a live code is confirmed again. |
| `POST auth/login` | Sign in with password (argon2id-hashed). `totp_code` (or a backup code) is required only after authenticator enrolment (`totp_enabled`). Issues a JWT. |
| `POST auth/totp/enable` | Confirm optional authenticator enrolment. Session-bound. Body `{ "totp_code" }`. Sets `totp_enabled`; later logins then require a TOTP or backup code. |
| `POST auth/pin` | Re-authenticate with the 6-digit PIN. Requires an existing session JWT. Body `{ "pin", "mode"? }`. `mode: "live"` (default) mints a Live JWT with `live_mode_unlocked=true`, and refuses 403 `totp_required` when the authenticator is not enabled. `mode: "practice"` / `"explore"` unlocks that mode without the Live claim and does not require TOTP. There is no `/auth/me`. |
| `POST auth/pin/set` | Set or change the PIN (password re-confirm). Requires an existing session JWT. |
| `POST auth/mode` | **Downgrade only** to `practice` or `explore`. Requires an existing session JWT. Issues a fresh JWT and revokes the old `jti`. Live upgrades must use `POST /v1/auth/pin`. |
| `POST auth/logout` | Revoke the current JWT by `jti`. Requires an existing session JWT. |

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
| `/health`, `/health/detail`, `/healthz`, `/readyz`, `/api/v1/ping` | Process health and compatibility probes. |
| `/v1/admin/system` | CPU, memory, disk, network, uptime, and process metrics for the Admin system panel. |
| `/v1/audit/*` | Scoped audit trail (`admin.audit.read` where required). |
| `/api/v1/admin/activity` | Operator activity feed. |
| `/api/v1/audit/logs` | Audit-log read on the operations blueprint (not `/v1/operations/…`). |

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

`require_auth` accepts a session JWT **or** an `X-API-Key` header
(`FLINTTRADE_API_KEY`, with `OPENALGO_API_KEY` as a compatibility
fallback). When neither key is configured, loopback-only requests are
allowed so a fresh install can reach Setup and sandbox reads. Broker
account-management writes still require the operator's session JWT.

`/v1/auth/*` is exempt from the global API-key check so login and first-run
setup can run without `X-API-Key`. That is not session-free auth: `POST
/v1/auth/totp/enable`, `/pin`, `/pin/set`, `/mode`, and `/logout` still decode
an existing session JWT and return 401 without one. Truly unauthenticated prefixes
include `/v1/auth/setup`, `/v1/auth/login`, `/v1/auth/status`,
`/v1/errors`, `/api/v1/errors`, `/v1/changelog`, `/api/v1/ping`, and the
other entries in `_PUBLIC_V1_PREFIXES` in `app.py`.

When an API key is configured, the unauthenticated health surfaces are
`GET /api/v1/health` (`health_detail.health_aggregated`) and
`GET /api/v1/ping` (listed in `_PUBLIC_V1_PREFIXES`). `/health`,
`/health/detail`, `/healthz`, and `/readyz` then return 401 unless a
session JWT or API key is supplied — do not point Kubernetes or
load-balancer probes at those four paths. Coverage is not limited to
`/ft-api/v1/*` — many operator routes live under `/api/v1`.

```
Authorization: Bearer <jwt>
```

### Token claims

The JWT carries three claims you care about:

| Claim | Meaning |
|---|---|
| `sub` | User identifier. |
| `exp` | Expiry timestamp. **Every token expires at 8 AM IST the next day.** Refresh by signing in again. |
| `mode` | One of `explore`, `practice`, `live`. Server-enforced on every order path. |
| `live_mode_unlocked` | `true` only after `POST /v1/auth/pin` with `mode: "live"`. Required for live order paths. |

A `jti` (JWT ID) is included so the server can revoke individual tokens
when the user logs out or switches mode. The revocation blocklist lives
in `packages/core/core/src/flinttrade_core/auth_state.py`.

### Backend API Keys

FlintTrade backend routes accept `X-API-Key` against `FLINTTRADE_API_KEY`
when configured. `OPENALGO_API_KEY` is retained as a compatibility fallback,
but it is no longer required for native FlintTrade practice/explore flows.
When neither key exists, loopback-only local requests are allowed so a fresh
desktop/dev install can reach read-only setup and sandbox endpoints. Broker
account-management **writes** (connect/remove/re-authenticate a broker,
credential capture, OAuth start, rate-limit and rotation config) additionally
require the operator's logged-in session JWT — the loopback allowance alone is
not sufficient for them. After that JWT check, production mutations still
return `503` `broker_account_cutover_unavailable` until Task 9D. The PIN
quick-unlock likewise requires an existing session (the PIN is a
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

`explore | practice | live` — server-side JWT-claim enforcement. The
guard lives at `packages/services/engine/src/flinttrade_engine/mode_guard.py`. Every order-path
endpoint asks the guard whether the current JWT permits live orders;
the guard returns one of three verdicts:

| Verdict | Behaviour |
|---|---|
| `explore` | Reject order placement with HTTP 403. Explore is for reading, learning, and demo data only. |
| `practice` | Route supported single-leg order flows to FlintTrade's native `SandboxEngine`; never touch OpenAlgo or a broker. Advanced executor-direct routes that do not yet have sandbox parity fail closed with `practice_unsupported`. |
| `live` | Require a JWT with `live_mode_unlocked=true`. The core `/orders/place`, modify, cancel, and `cancel-all` paths go through the gated `BrokerRouter`. Other legacy write verbs (`open-position`, `close-position`, and similar) return HTTP 501 until they have a gated `BrokerRouter` verb — they do not forward ungated to OpenAlgo. |

`POST /v1/auth/mode` issues a fresh JWT and revokes the previous `jti`,
but it accepts **only** downgrades to `practice` or `explore`. Upgrading
to Live is `POST /v1/auth/pin` with the 6-digit PIN (`mode: "live"`), after
the authenticator is enrolled (`totp_enabled`). Without enrolment that call
refuses 403 with `code: "totp_required"`. There is no
`/auth/mode {mode:live}` shortcut.

Authoritative coverage: `packages/core/core/tests/test_order_routes.py` asserts
Explore rejection, Practice sandbox routing, and Live gate / fail-closed
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
It routes to FlintTrade's native sandbox and does not send an order to OpenAlgo
or any broker. Do not use the OpenAlgo passthrough endpoint as an example for
live broker execution. Live manual, automated, and agent-driven order workflows
use the same FlintTrade order proxy after a Live-mode JWT, safety gate, account
ACL check, and broker-router dispatch.

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

Sandbox response shape:

```json
{
  "status": "success",
  "order_id": "sandbox-...",
  "message": "Practice order filled by sandbox"
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
`/api/v1/orders/*` proxy is message-only: Explore is HTTP 403 with
"Orders are not available in Explore mode…", and a Live JWT without PIN
unlock is HTTP 403 with "Live mode not unlocked — verify PIN first". A
`code` field is emitted on `mode_guard`-decorated engine routes (brackets
and other executor-direct paths), not on that core proxy:

| Code or status | Meaning |
|---|---|
| `mode_blocked` | Explore (or another blocked mode) tried a `mode_guard` order-capable action — HTTP 403. |
| `practice_unsupported` | Practice JWT hit an executor-direct route with no sandbox parity — HTTP 403. |
| `live_locked` | A `mode_guard` Live path requires `live_mode_unlocked=true` (PIN unlock). |
| HTTP 429, message `Rate limit exceeded` | FlintTrade `@rate_limit` on the order proxy. No `RATE_LIMIT_EXCEEDED` enum. |
| Safety `message` | A safety layer rejected the order; the message names the layer. There is no `SAFETY_LAYER_BLOCK` code. |

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
