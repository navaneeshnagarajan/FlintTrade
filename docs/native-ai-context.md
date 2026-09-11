# Configured broker inputs for AI team analysis

The existing JSON and streaming team-analysis endpoints can collect their own
authorised broker inputs instead of accepting caller-supplied market data:

- `POST /api/v1/ai/team/analyse`
- `POST /api/v1/ai/team/analyse/stream`

**Availability:** this integration requires authorised, already-published broker
sessions. The current native account-mutation/reconnect cutover guard on `main`
still blocks normal native account setup. This change does not remove that guard
or restore Setup → Brokers. Fresh-install native use remains unavailable until
the account-lifecycle cutover lands. Local verification uses synthetic sessions
and SDK responses; it is not live-provider verification.

Send a full FlintTrade operator-session JWT and this request:

```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": "flat",
  "context_source": "configured_brokers"
}
```

The operator needs `admin.accounts.read` and access to **each** selected broker
account. The request does not grant permissions, connect accounts or unlock
Live mode. Native accounts do not require an OpenAlgo login: broker reads reuse
FlintTrade's existing gateway and app-owned event loop. An explicitly configured
OpenAlgo bridge still requires its own valid connection.

## What the model receives

FlintTrade reads the configured quote account for quote and optional depth, the historical
account for five-minute bars over the preceding three calendar days, and the
exact execution account for balances. Execution-account selection honours the
instrument's configured segment override. These can be different accounts and
different brokers.

The input contains the requests, copied values, account/version provenance and
observation times. Depth is limited to five levels per side and history to the
latest 128 returned bars; omitted counts are included. Unavailable balance
fields remain unknown, not zero. Quote, depth and balance observation times are
**not** market-source timestamps or freshness guarantees. History retains its
provided candle timestamps. This is analysis context, not a backtest dataset.

If the quote adapter does not implement the read-port depth capability, the
depth record explicitly contains `error_code: "unsupported"` with null value,
provenance and source timestamp. This is not an empty order book. Native
adapters' separate depth-stream and `market_depth` interfaces are not adapted
by this feature. All other depth failures still prevent model invocation.

Before invoking the model, FlintTrade durably appends the exact input to its
existing hash-chained audit log as `AI_BROKER_ANALYSIS_INPUT`. Successful JSON
results and SSE `result` frames include:

```json
{
  "input_receipt": {
    "event_id": "<audit-event-uuid>",
    "input_digest": "<sha256-of-canonical-market-data>"
  }
}
```

The receipt sits beside the existing `analysis` and `recommendation` fields.
Its digest uses UTF-8 JSON with sorted keys, compact separators, unescaped
Unicode and no NaN/Infinity. It identifies the recorded input, not the model
version, trading performance or a strategy approval.

## Failure and compatibility

Missing or revoked sessions, account denials, unavailable/stale connections,
invalid required data, timeout and audit-write failure prevent model invocation.
Public failures use fixed `broker_context_*` codes; raw provider errors and
credentials are not returned. Grants are revoked after collection.

Do not combine `configured_brokers` with a `market_data` field, including `null`.
Sequential mode is refused for this source because its current chain does not
consume the market-context argument. Flat, DAG and debate retain their existing
team behaviour. Omitting `context_source` (or setting it to `supplied`) preserves
the existing caller-supplied-context API and does not create an input receipt.

This feature is read-only. It does not start an autonomous Practice session,
place orders, qualify a strategy or promote it to Live trading. Those workflows
still require their separate safety and evidence gates.
