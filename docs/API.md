# FlintTrade API Reference

FlintTrade owns the terminal’s authenticated HTTP transport. Native broker
reads and account mutations remain frozen; Practice uses the local sandbox.

| Surface | Base URL (production) | Base URL (Vite dev proxy) | Purpose |
|---|---|---|---|
| FlintTrade backend | `http://<flinttrade-host>:5100/v1/` and `http://<flinttrade-host>:5100/api/v1/` | `/ft-api/v1/` and `/ft-api/api/v1/` | FlintTrade-specific endpoints. Blueprints mount at `/v1` *or* `/api/v1` — match the prefix the frontend uses. Operations, native brokers, and orders live under `/api/v1`. |

> **WSGI prefix strip.** Blueprints mount at `/v1/*` *or* `/api/v1/*` —
> match the prefix the frontend uses. The Vite dev proxy and a production
> reverse proxy add `/ft-api` before forwarding, and WSGI middleware strips
> that prefix before URL dispatch. A client path `/ft-api/v1/X` is `/v1/X`
> inside the backend; `/ft-api/api/v1/X` is `/api/v1/X`. Never double-prefix.

---

## 2. FlintTrade backend (`/ft-api/v1/*`)

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
| `POST /api/v1/orders/place` | Practice and Live single-leg place. The server admits the body through Laya. A client flag cannot choose reduce-only. Practice then fills or rests in the sandbox and does not enter SafetySystem. Live then runs SafetySystem, `gate_order`, and `BrokerRouter`. `"variety": "gtt"` is HTTP 422 `gtt_unsupported` before that admission. Example data that calls this route is HTTP 403 `mode_blocked`: `Orders are not available for Example. Switch to Practice or Live to trade.` The `/trade` Order Pad records `Example order placed` (id starting `SAMPLE-`) on the client for that click. |
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

Layer 5 (`POST /api/v1/safety/kill-switch`) cancels resting orders and then
flattens through the emergency `exit_all_positions` verb. Ditto execution
endpoints, including `/api/v1/ditto/kill-all`, remain unavailable until
native cutover.

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

| Endpoint | Purpose |
|---|---|
| `chart` (**GET/POST**) | Chart-preference get/set. |

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

Broker-hosted MCP setup catalogue: `broker/mcp` (**GET**). Metadata only; FlintTrade does not proxy MCP tool calls.

### Broker capability metadata (`/api/v1/broker/*`, GET)

Source: `packages/integrations/gateway/src/flinttrade_gateway/capabilities_routes.py`.

| Endpoint | Purpose |
|---|---|
| `broker/capabilities` (**GET**) | Per-broker capability matrix (order types, segments, depth, rate limits), with native connectability, blocker reasons, and static-outbound-IP requirement where catalogued. |
| `broker/recommendations` (**GET**) | Filter broker capability metadata for an operator-selected use case, including display name, connectability, native-connect blocker reasons, and static-outbound-IP requirement. `?use_case=<id>` for one job (for example `low_cost_execution`, `market_depth`); `?brokers=a,b` restricts the response to connected brokers. |

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

| Endpoint | Purpose |
|---|---|
| `telegram` (**POST**) | Send a Telegram test message. Body requires `message`. Optional one-shot `bot_token` and `chat_id` are accepted together and are never persisted. Otherwise the route uses env/workspace bot config; disabled config → 400. Send failure → 502. Sample-data sends (JWT `mode` claim or `X-FlintTrade-Mode: explore`) return HTTP 403 with `code: "mode_blocked"`. The desk helper is `Telegram tests are blocked for Example. Switch to Practice or Live with Telegram configured to send a real test.` |

### Ditto (`/api/v1/ditto/*`)

Source: `packages/core/core/src/flinttrade_core/operations_routes.py`.
The operations blueprint mounts at `/api/v1`, so the Vite/dev-proxy form is
`/ft-api/api/v1/ditto/…` and a direct backend call is
`http://<host>:5100/api/v1/ditto/…`.

Native copy trading is unavailable pending its native safety design. Linking
returns 501; the default factory creates no copy runtime. Runtime operations
return 503 after their authentication, body and mode checks. These routes do
not enable a broker bridge or Live mirroring.

| Endpoint | Contract |
|---|---|
| `ditto/accounts` (**GET**) | Read non-secret native copy-account references, including both `adapter_id` and `account_id`. |
| `ditto/accounts` (**POST**) | Account linking unavailable (501). |
| `ditto/accounts/<adapter_id>/<account_id>/enable` · `…/disable` (**POST**) | Session-authenticated account metadata only. Select the exact native broker/account pair. Disable drains any participating runtime generation before changing metadata; a failed drain returns 503. These routes do not start copying or place orders. |
| `ditto/accounts/<adapter_id>/<account_id>` (**DELETE**) | Requires a session; native account HTTP mutations remain unavailable (503) by default. |
| `ditto/mirror/status` (**GET**) | Runtime unavailable (503). |
| `ditto/mirror/start` (**POST**) | Requires a complete body, Live session and PIN; runtime unavailable (503). Example is refused (403). |
| `ditto/mirror/stop` (**POST**) | Requires a session; runtime unavailable (503). |
| `ditto/risk` (**GET**) | Runtime unavailable (503). |
| `ditto/kill-all` (**POST**) | Requires a Live session; runtime unavailable (503). Example is refused (403). |

Legacy account-only metadata routes accept only an unambiguous account ID.
If two native brokers share that ID, they return HTTP 400
`account_selector_required` and change neither account. An explicit adapter never
falls back to an account at another broker; malformed selectors return HTTP 400
`account_selector_invalid`.

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

---

## 5. Rate limits

Native broker throttles are applied by `BrokerRouter` using each adapter’s
capabilities and workspace overrides. Every Live write still needs a one-shot
`SafetyContext` from `gate_order` or `gate_broker_write`.


---

## 6. Mode system

`explore | practice | live` — server-side JWT-claim enforcement. The claim `explore` is example data. Operators see **Example**, not a Mode in the menu. The
guard lives at `packages/services/engine/src/flinttrade_engine/mode_guard.py`. Every order-path
endpoint asks the guard whether the current JWT permits live orders;
the guard returns one of three verdicts:

| Verdict | Behaviour |
|---|---|
| `explore` | Example data. `POST /api/v1/orders/place` and the shared order dispatcher both reject the order with HTTP 403 and `code: "mode_blocked"`. The message on both is `Orders are not available for Example. Switch to Practice or Live to trade.` No broker is contacted. The `/trade` Order Pad records a sample fill on the client for that click (`Example order placed`, id starting `SAMPLE-`). This HTTP refusal is what the route returns when a client calls it. |
| `practice` | Admitted orders execute in the local sandbox. Practice never calls a broker adapter. |
| `live` | Requires a PIN-unlocked Live session, an exact native account target, safety admission and `BrokerRouter`. Evidence-gated native availability still applies; choosing this mode does not activate a broker. |

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

---

## 9. Versioning

The HTTP surface uses URL-segment versioning (`/api/v1/`, `/ft-api/v1/`).
Breaking changes go to `/v2/` and the `/v1/` surface stays alive for at
least one minor release. The WebSocket protocol carries a `version` field
on the handshake; current value is `2`.

See [releases/](releases/) for per-version change notes.
