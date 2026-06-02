# FlintTrade API Reference

FlintTrade exposes two HTTP surfaces and one WebSocket channel.

| Surface | Base URL (production) | Base URL (Vite dev proxy) | Purpose |
|---|---|---|---|
| OpenAlgo passthrough | `http://<openalgo-host>:5000/api/v1/` | `/api/v1/` | Broker-facing endpoints — orders, positions, quotes, history, etc. |
| FlintTrade backend | `http://<flinttrade-host>:5100/v1/` | `/ft-api/v1/` | FlintTrade-specific endpoints — analysis, gateway management, auth, monitoring. |
| WebSocket | `ws://<openalgo-host>:8765` | `/ws` | Streaming market data (LTP, Quote, Depth). |

> **WSGI prefix strip.** The FlintTrade backend mounts its blueprints at
> `/v1/*` internally. The Vite dev proxy and the production reverse proxy
> add the `/ft-api` prefix before forwarding to the backend, and WSGI
> middleware strips it before URL dispatch. Routes documented below as
> `/ft-api/v1/X` are how clients see them; routes documented as `/v1/X`
> are the same endpoint as the backend sees them.

---

## 1. OpenAlgo passthrough (`/api/v1/*`)

Source of truth: `packages/core/core/src/openalgo_client.py`. All endpoints are
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
| `depth` | Level-2 market depth (5 or 20 levels depending on broker). |
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
| `whatsapp/notify` | Send a WhatsApp message via the OpenAlgo bot (added in 2.0.1.1). Public surface deliberately narrowed — pairing / start / stop are admin-only on OpenAlgo's `/whatsapp` web UI. |

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

Source of truth: `packages/core/core/src/app.py` and the `*_routes.py` files
under `packages/*/src/`. Externally clients call `/ft-api/v1/…`;
internally blueprints are registered at `/v1/…` (or `/api/v1/…` for the
OpenAlgo-style paths). Both shapes route to the same handler thanks to
the WSGI prefix-strip.

### Analysis (`/ft-api/v1/gex` etc.)

GET endpoints. Powered by `packages/services/screener/`.

| Endpoint | Purpose |
|---|---|
| `gex` | Gamma Exposure dashboard data (alternative to the OpenAlgo passthrough; computed locally on historical chains). |
| `volsurface` | Volatility surface across strikes and expiries. |
| `ivsmile` | IV smile curve. |
| `straddlepnl` | Live straddle P&L for an at-the-money pair. |
| `oiprofile` | OI profile data. |
| `maxpain` | Max-pain calculation. |

### Gateway (`/ft-api/v1/broker/*`)

POST endpoints. Powered by `packages/integrations/gateway/`. Used by the
`/setup-account` wizard and by the connection-status indicator.

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

### Auth (`/ft-api/v1/auth/*`)

JWT-based. Source: `packages/core/core/src/auth_routes.py`.

| Endpoint | Purpose |
|---|---|
| `auth/login` | Sign in with username + password (argon2id-hashed) and receive a JWT. |
| `auth/logout` | Revoke the current JWT by `jti`. |
| `auth/mode` | Switch mode (Explore / Practice / Live) — issues a fresh JWT with the new mode claim and revokes the old `jti`. |
| `auth/me` | Decode the current JWT and return user info. |
| `auth/setup-2fa` | Enrol TOTP for the FlintTrade login (separate from broker TOTP). |
| `auth/verify-2fa` | Verify a TOTP code during login. |

### Monitoring And Observability

GET endpoints. Source: `packages/core/core/src/monitoring_routes.py`,
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
| `/api/v1/latency/stats` | Per-broker order latency percentiles. |
| `/api/v1/latency/recent` | Recent latency records. |
| `/health`, `/health/detail`, `/healthz`, `/readyz`, `/api/v1/ping` | Process health and compatibility probes. |
| `/v1/admin/system` | CPU, memory, disk, network, uptime, and process metrics for the Admin system panel. |
| `/v1/audit/*`, `/v1/activity/*`, `/v1/operations/audit/logs` | Scoped audit/activity views; admin audit endpoints require `admin.audit.read`. |

### Errors (`/ft-api/v1/errors`, `/ft-api/v1/changelog`)

| Endpoint | Purpose |
|---|---|
| `errors` | Front-end error reporting sink. The terminal posts unhandled errors here. |
| `changelog` | Read the bundled changelog.md programmatically (used by the "What's new" widget). |

There are roughly 20 FlintTrade-specific endpoint families across the
13 Python packages. The complete list of registered Flask blueprints
appears in `packages/core/core/src/app.py` — search for `register_blueprint`.

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
in `packages/core/core/src/auth_state.py`.

### Backend API Keys

FlintTrade backend routes accept `X-API-Key` against `FLINTTRADE_API_KEY`
when configured. `OPENALGO_API_KEY` is retained as a compatibility fallback,
but it is no longer required for native FlintTrade practice/explore flows.
When neither key exists, loopback-only local requests are allowed so a fresh
desktop/dev install can reach native setup and sandbox endpoints.

The OpenAlgo-compatible passthrough still uses OpenAlgo's own API key. That
key is read from `.env` (`OPENALGO_API_KEY`) and forwarded as the `X-API-KEY`
header by `OpenAlgoClient` only for OpenAlgo/live bridge calls.

---

## 5. Rate limits

Source: `packages/core/core/src/openalgo_client.py` (`_RateLimiter`).

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
guard lives at `packages/services/engine/src/mode_guard.py`. Every order-path
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

The five most-used endpoints, with cURL.

### 7.1 Place an order

```bash
curl -X POST http://127.0.0.1:5000/api/v1/placeorder \
  -H "X-API-KEY: $OPENALGO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "strategy": "Flint",
    "symbol": "NIFTY28MAY24850CE",
    "exchange": "NFO",
    "action": "BUY",
    "quantity": "50",
    "pricetype": "MARKET",
    "product": "MIS"
  }'
```

Successful response:

```json
{
  "status": "success",
  "orderid": "240520000001234"
}
```

### 7.2 Get a quote

```bash
curl -X POST http://127.0.0.1:5000/api/v1/quotes \
  -H "X-API-KEY: $OPENALGO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "symbol": "NIFTY", "exchange": "NSE_INDEX" }'
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

Response is a list of `Position` records — symbol, exchange, product,
quantity, average price, last price, P&L.

### 7.4 Pull an option chain

```bash
curl -X POST http://127.0.0.1:5000/api/v1/optionchain \
  -H "X-API-KEY: $OPENALGO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "symbol": "NIFTY", "exchange": "NFO" }'
```

Response: nested object keyed by strike, with CE and PE legs each
containing LTP, OI, volume, IV, and Greeks.

### 7.5 Compute Gamma Exposure (FlintTrade-side)

```bash
curl http://127.0.0.1:5100/ft-api/v1/gex?symbol=NIFTY&expiry=2026-05-28 \
  -H "Authorization: Bearer $FLINTTRADE_JWT"
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
