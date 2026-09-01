# FlintTrade API Reference

FlintTrade exposes two HTTP surfaces and one WebSocket channel.

| Surface | Base URL (production) | Base URL (Vite dev proxy) | Purpose |
|---|---|---|---|
| OpenAlgo passthrough | `http://<openalgo-host>:5000/api/v1/` | `/api/v1/` | Broker-facing endpoints — orders, positions, quotes, history, etc. |
| FlintTrade backend | `http://<flinttrade-host>:5100/v1/` and `http://<flinttrade-host>:5100/api/v1/` | `/ft-api/v1/` and `/ft-api/api/v1/` | FlintTrade-specific endpoints. Blueprints mount at `/v1` *or* `/api/v1` — match the prefix the frontend uses. Operations, native brokers, and orders live under `/api/v1`. |
| WebSocket | `ws://<openalgo-host>:8765` | `/ws` | Streaming market data (LTP, Quote, Depth). |

> **WSGI prefix strip.** The FlintTrade backend mounts its blueprints at
> `/v1/*` internally. The Vite dev proxy and the production reverse proxy
> add the `/ft-api` prefix before forwarding to the backend, and WSGI
> middleware strips it before URL dispatch. Routes documented below as
> `/ft-api/v1/X` are how clients see them; routes documented as `/v1/X`
> are the same endpoint as the backend sees them.

---

## 1. OpenAlgo passthrough (`/api/v1/*`)

Source of truth: `packages/core/core/src/flinttrade_core/openalgo_client.py`. All endpoints are
POST unless explicitly marked **GET**.

### Orders

| Endpoint | Purpose |
|---|---|
| `placeorder` | Place a standard order (MARKET / LIMIT / SL / SL-M). |
| `placesmartorder` | Conditional / multi-leg / target-position smart order. |
| `modifyorder` | Modify price / quantity / order type of a pending order. |
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
| `quotes` | Single-symbol quote (LTP, OHLC, OI). |
| `multiquotes` | Quote for a list of symbols in one request. |
| `depth` | Level-2 market depth from brokers with a wired FlintTrade snapshot read; documented feed-only depth is not exposed here until the adapter bridge is wired. |
| `history` | Historical OHLCV bars. |
| `optionchain` | Full option chain for a symbol and expiry. |
| `optiongreeks` | Greeks for a specific strike. |
| `multioptiongreeks` | Greeks for a list of strikes in one request. |
| `optionsymbol` | Resolve human-readable expiry / strike / type to a tradeable symbol. |
| `symbol` | Symbol metadata lookup. |
| `search` | Symbol search by name / partial match. |
| `expiry` | List of available expiries for a symbol. |
| `intervals` (**GET**) | Supported chart intervals for the active broker. |
| `syntheticfuture` | Synthetic future from CE - PE + strike. |
| `ticker` (**GET**) | OHLCV ticker stream via header auth. |
| `instruments` (**GET**) | Instrument master CSV for an exchange. |
| `gex` | Gamma Exposure curve. |
| `iv_smile` | Implied-volatility smile curve. |
| `max_pain` | Max-pain strike calculation. |
| `oi_profile` | Open-Interest profile by strike. |
| `chart` (**GET/POST**) | Chart-preference get/set. |

### Utilities

| Endpoint | Purpose |
|---|---|
| `holidays` | Exchange holiday list. |
| `timings` | Exchange-timing windows for a date. |
| `telegram` | Send a Telegram message via the OpenAlgo bot. |
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

### Analysis (`/ft-api/v1/gex` etc.)

GET endpoints unless marked otherwise. Powered by `packages/services/screener/`.

| Endpoint | Purpose |
|---|---|
| `gex` | Gamma Exposure dashboard data (alternative to the OpenAlgo passthrough; computed locally on historical chains). |
| `volsurface` | Volatility surface across strikes and expiries. |
| `ivsmile` | IV smile curve. |
| `straddlepnl` | Live straddle P&L for an at-the-money pair. |
| `oiprofile` | OI profile data. |
| `maxpain` | Max-pain calculation. |
| `gammadensity` (**POST**) | Gamma density surface across strikes and expiries. |
| `screener/fii-long-short` | FII long/short ratio from participant-wise derivative positions. |
| `screener/arbitrage` (**POST**) | Cash-future and cross-exchange arbitrage scan. |
| `candlestick-patterns` (**POST**) | Candlestick pattern detection over OHLCV history. |
| `index-contribution` | Index constituent contribution decomposition. |

### Gateway (`/ft-api/v1/broker/*`)

POST endpoints. Powered by `packages/integrations/gateway/`. Used by the
canonical `/setup` wizard (`/setup-account` is a compatibility alias) and by
the connection-status indicator.

| Endpoint | Purpose |
|---|---|
| `broker/catalog` | Enumerate every supported broker with capability flags. |
| `broker/accounts` | List linked accounts. |
| `broker/connect` | Create a new broker session. |
| `broker/disconnect` | Tear down an existing session. |
| `broker/auth/apikey` | Submit API-key + secret authentication. |
| `broker/auth/totp` | Submit TOTP code for two-factor brokers. |
| `broker/auth/oauth` | Initiate the OAuth flow. |
| `broker/auth/otp` | Submit a one-time-password challenge. |
| `broker/auth/callback` | Receive an OAuth callback. |
| `broker/reconnect` | Re-authenticate an existing session that has expired. |

### Native broker connect and reads (`/api/v1/native/*`)

Source: `packages/core/core/src/flinttrade_core/native_account_routes.py`.

These endpoints are the first-party native broker path used by Setup →
Brokers and Settings → Brokers. Connect writes store credentials in the
encrypted gateway vault, register a workspace selector, rebuild the broker
router, and attempt login transactionally. Brokers that are built but not
cleared for activation stay `connectable=false` while any declared
`native_connect_blocker` remains; their connect/re-login routes return "coming
soon" rather than creating sessions. Account and market-data reads
require a live native session but do not create an order safety context.
Legacy gateway `/v1` account/auth routes reject native broker ids and include
the same `data.native_connect_blockers` payload when a catalogued native broker
is still evidence-gated.

| Endpoint | Purpose |
|---|---|
| `native/brokers` (**GET**) | Native broker catalogue with connectability, native-connect blocker reasons, static-outbound-IP requirement, login-method schemas, OAuth/postback URLs, and MCP metadata. |
| `native/accounts` (**GET**) | Vault-backed native account list with live session status, expiry, read-only flag, and `needs_relogin` / retryable login state. |
| `native/accounts` (**POST**) | Direct native connect: `{adapter_id, account_id, label?, credentials, is_primary?}`. |
| `native/oauth/start` (**POST**) | Start an OAuth/app-consent login and return the broker authorisation URL, loopback redirect URI, state, and optional postback URI. |
| `native/oauth/callback` (**GET**) | Loopback OAuth callback that exchanges a broker `code` or Dhan `tokenId` and then runs the native connect transaction. |
| `native/postbacks/<adapter_id>` (**POST**) | Bounded, redacted broker postback intake for diagnostics/order-update evidence; not an order execution path. |
| `native/accounts/<adapter>/<account>/login` (**POST**) | Re-authenticate a native account, optionally with fresh credentials; stale single-use material surfaces `needs_relogin`. |
| `native/accounts/<adapter>/<account>/<kind>` (**GET**) | Read account or market data from a live native session. Supported kinds include `funds`, `limits`, `positions`, `holdings`, `profile`, `orders`, `orderstatus`, `orderhistory`, `ordertrades`, `trades`, `ltp`, `quotes`, `quote_details`, `ohlc`, `depth`, `margin`, `scrip_master`, `holidays`, `timings`, `optiongreeks`, `history`, `expiry`, `optionchain`, `search`, and `search_scrip`. |
| `native/accounts/<adapter>/<account>/set-primary` (**POST**) | Promote a connected, non-read-only native session to the live write default. |
| `native/accounts/<adapter>/<account>` (**DELETE**) | Remove a native account, drop its session, delete credentials, deregister the workspace selector, and stop stale refresh state. |

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

### AI (`/ft-api/v1/ai/*`, `/ft-api/v1/signals/*`)

Source: `packages/services/ai/`. GET unless noted.

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

### Strategies (`/ft-api/v1/strategies/*`)

Source: `packages/services/engine/src/flinttrade_engine/strategy_routes.py`. Backed by the
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
| `auth/login` | Sign in with username + password (argon2id-hashed) and receive a JWT. |
| `auth/logout` | Revoke the current JWT by `jti`. |
| `auth/mode` | Switch mode (Explore / Practice / Live) — issues a fresh JWT with the new mode claim and revokes the old `jti`. |
| `auth/me` | Decode the current JWT and return user info. |
| `auth/setup-2fa` | Enrol TOTP for the FlintTrade login (separate from broker TOTP). |
| `auth/verify-2fa` | Verify a TOTP code during login. |

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
| `/api/v1/reconciliation/outcomes/<attempt_id>/resolve` (**POST**) | Record `confirmed_applied`, `confirmed_not_applied`, or basket-only `confirmed_partial` after broker verification. Requires an authenticated, PIN-unlocked Live JWT, current-router selector ACL, exact `CONFIRM <APPLIED\|NOT_APPLIED\|PARTIAL> <broker>:<account>:<attempt>` confirmation, a newly adopted exact-selector reconciliation generation, and a durable hash-chained audit receipt. Snapshots are monotonic; same-time conflicts and malformed reports fail closed, and historical observations remain evidence. Applied placement IDs must be first observed after invocation and match every persisted material identity field; basket requests map applied IDs to `broker_order_item_indexes` and partition all remaining children in `not_applied_item_indexes`. Modify and cancel recovery require operation-specific evidence. A `PENDING_AUDIT` retry requires newer evidence, archives the prior revision and receives a new resolution ID; a `PENDING_ROUTER_CLEAR` retry resumes the committed decision without another broker read. Success and structured-error responses carry the exact attempt and canonical decision; the terminal runtime-validates identity, status and primitive types before updating state. Ambiguous and unsupported cases remain blocked; this route performs no broker write. |
| `/health`, `/health/detail`, `/healthz`, `/readyz`, `/api/v1/ping` | Process health and compatibility probes. |
| `/v1/admin/system` | CPU, memory, disk, network, uptime, and process metrics for the Admin system panel. |
| `/v1/audit/*`, `/v1/activity/*`, `/v1/operations/audit/logs` | Scoped audit/activity views; admin audit endpoints require `admin.audit.read`. |

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

The client sends a `ping` frame every 30 seconds and expects a `pong`
within five seconds. The FlintTrade client (`openalgo_client.py`)
auto-reconnects with exponential back-off if either side stops
responding.

---

## 4. Authentication

### JWT (FlintTrade backend)

Every `/ft-api/v1/*` endpoint (except `/auth/login` and `/health`)
requires a Bearer token in the `Authorization` header:

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
not sufficient for them. The PIN quick-unlock likewise requires an existing
session (the PIN is a re-authentication factor, never a standalone login).

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
| `live` | Require a JWT with `live_mode_unlocked=true`. The core `/orders/place`, modify, and cancel paths go through the gated `BrokerRouter`; remaining legacy-compatible live actions forward to the configured OpenAlgo-compatible endpoint until native parity is complete. |

Mode switching is a deliberate, audited step. `/ft-api/v1/auth/mode`
issues a fresh JWT with the new mode and revokes the previous `jti`,
so the old token cannot be replayed.

Authoritative coverage: `packages/core/core/tests/test_order_routes.py` asserts
Explore rejection, Practice sandbox routing, and Live gate/forward behaviour.
Engine routes that bypass the core order proxy use
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

```bash
curl -X POST http://127.0.0.1:5000/api/v1/optionchain \
  -H "X-API-KEY: $OPENALGO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "symbol": "NIFTY", "exchange": "NFO" }'
```

```powershell
$params = @{
  Method      = "Post"
  Uri         = "http://127.0.0.1:5000/api/v1/optionchain"
  Headers     = @{ "X-API-KEY" = $env:OPENALGO_API_KEY }
  ContentType = "application/json"
  Body        = '{ "symbol": "NIFTY", "exchange": "NFO" }'
}
Invoke-RestMethod @params
```

Response: nested object keyed by strike, with CE and PE legs each
containing LTP, OI, volume, IV, and Greeks.

### 7.5 Compute Gamma Exposure (FlintTrade-side)

```bash
curl "http://127.0.0.1:5100/ft-api/v1/gex?symbol=NIFTY&expiry=2026-05-28" \
  -H "Authorization: Bearer $FLINTTRADE_JWT"
```

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5100/ft-api/v1/gex?symbol=NIFTY&expiry=2026-05-28" -Headers @{ Authorization = "Bearer $env:FLINTTRADE_JWT" }
```

Response:

```json
{
  "status": "success",
  "data": {
    "symbol": "NIFTY",
    "expiry": "2026-05-28",
    "spot": 24850.55,
    "gex_total": 1.24e9,
    "gex_by_strike": [
      { "strike": 24700, "gex": -3.1e8 },
      { "strike": 24800, "gex":  4.8e8 },
      { "strike": 24900, "gex":  9.4e8 },
      { "strike": 25000, "gex": -2.3e8 }
    ],
    "zero_gamma": 24820.5
  }
}
```

---

## 8. Error responses

Every endpoint returns one of two shapes.

**Success:**

```json
{ "status": "success", "data": { … } }
```

**Error:**

```json
{ "status": "error", "message": "Human-readable explanation.", "code": "ENUM_CODE" }
```

Common error codes:

| Code | Meaning |
|---|---|
| `AUTH_TOKEN_EXPIRED` | JWT past its `exp`. Sign in again. |
| `AUTH_TOKEN_REVOKED` | `jti` is on the revocation list. |
| `MODE_NOT_ALLOWED` | Caller tried a live action while in Explore. |
| `RATE_LIMIT_EXCEEDED` | Request rate exceeded the bucket for this category. |
| `BROKER_SESSION_EXPIRED` | OpenAlgo says the broker session is gone. Re-authenticate at the OpenAlgo dashboard. |
| `SAFETY_LAYER_BLOCK` | One of the 5 safety layers rejected the order. The `message` field names the layer. |
| `VALIDATION_ERROR` | Request body failed schema validation. |

---

## 9. Versioning

The HTTP surface uses URL-segment versioning (`/api/v1/`, `/ft-api/v1/`).
Breaking changes go to `/v2/` and the `/v1/` surface stays alive for at
least one minor release. The WebSocket protocol carries a `version` field
on the handshake; current value is `2`.

See [releases/](releases/) for per-version change notes.
