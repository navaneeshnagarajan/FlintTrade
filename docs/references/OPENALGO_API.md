# OpenAlgo API Reference — Quick Guide for FlintTrade Developers

> This is a condensed reference of OpenAlgo's REST API and WebSocket.
> Full docs: https://docs.openalgo.in/api-documentation/v1
> FlintTrade communicates with OpenAlgo ONLY through these endpoints.

## OpenAlgo Version

This reference is for OpenAlgo v2.0.0.1 (released Feb 24, 2026).
Run `git subtree pull` in infra/openalgo/ to stay current.

## Authentication

Every request requires an API key in the JSON body:
```json
{ "apikey": "your_openalgo_api_key" }
```

## Base URLs

```
REST API:   http://{host}:5000/api/v1/{endpoint}
WebSocket:  ws://{host}:8765
Webhooks:   http://{host}:5000/strategy/webhook/{webhook_id}
```

---

## Order APIs

### PlaceOrder
```
POST /api/v1/placeorder
{
  "apikey": "key", "strategy": "Flint", "symbol": "RELIANCE",
  "action": "BUY",           // BUY | SELL
  "exchange": "NSE",         // NSE | BSE | NFO | BFO | MCX | CDS
  "pricetype": "MARKET",     // MARKET | LIMIT | SL | SL-M
  "product": "MIS",          // MIS | CNC | NRML
  "quantity": "1",
  "price": "0",              // Required for LIMIT/SL
  "trigger_price": "0",      // Required for SL/SL-M
  "disclosed_quantity": "0"
}
→ {"status": "success", "orderid": "123456"}
```

### PlaceSmartOrder
```
POST /api/v1/placesmartorder
Same as PlaceOrder + "position_size": "5"
Automatically adjusts quantity based on current open position.
```

### OptionsOrder
```
POST /api/v1/optionsorder
{
  "apikey": "key", "strategy": "Flint", "underlying": "NIFTY",
  "exchange": "NFO", "expiry_date": "260326",  // YYMMDD
  "offset": "0",         // 0=ATM, 1=OTM1, -1=ITM1
  "option_type": "CE",   // CE | PE
  "action": "BUY", "quantity": "75",
  "pricetype": "MARKET", "product": "MIS", "splitsize": "75"
}
→ {"status": "success", "orderid": "123", "symbol": "NIFTY26MAR2524000CE"}
```

### OptionsMultiOrder (multi-leg)
```
POST /api/v1/optionsmultiorder
{
  "apikey": "key", "strategy": "Flint", "underlying": "NIFTY",
  "exchange": "NFO", "expiry_date": "260326",
  "legs": [
    {"offset": "0", "option_type": "CE", "action": "SELL", "quantity": "75"},
    {"offset": "0", "option_type": "PE", "action": "SELL", "quantity": "75"}
  ],
  "pricetype": "MARKET", "product": "NRML"
}
```

### BasketOrder
```
POST /api/v1/basketorder
{
  "apikey": "key", "strategy": "Flint",
  "orders": [
    {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": "1", "pricetype": "MARKET", "product": "MIS"},
    {"symbol": "TCS", "exchange": "NSE", "action": "BUY", "quantity": "1", "pricetype": "MARKET", "product": "MIS"}
  ]
}
```

### SplitOrder
```
POST /api/v1/splitorder
Same as PlaceOrder + "splitsize": "25"
Splits large orders into chunks to avoid slippage.
```

### ModifyOrder
```
POST /api/v1/modifyorder
{"apikey": "key", "strategy": "Flint", "orderid": "123", "symbol": "RELIANCE",
 "exchange": "NSE", "action": "BUY", "pricetype": "LIMIT", "product": "MIS",
 "quantity": "1", "price": "2550"}
```

### CancelOrder / CancelAllOrder / ClosePosition
```
POST /api/v1/cancelorder      {"apikey": "key", "strategy": "Flint", "orderid": "123"}
POST /api/v1/cancelallorder   {"apikey": "key", "strategy": "Flint"}
POST /api/v1/closeposition    {"apikey": "key", "strategy": "Flint"}
```

### OrderStatus / OpenPosition
```
POST /api/v1/orderstatus      {"apikey": "key", "strategy": "Flint", "orderid": "123"}
POST /api/v1/openposition     {"apikey": "key", "strategy": "Flint", "symbol": "RELIANCE", "exchange": "NSE", "product": "MIS"}
```

---

## Data APIs

### Quotes / MultiQuotes
```
POST /api/v1/quotes       {"apikey": "key", "symbol": "RELIANCE", "exchange": "NSE"}
POST /api/v1/multiquotes  {"apikey": "key", "symbols": [{"symbol": "RELIANCE", "exchange": "NSE"}, ...]}
→ {"ltp", "open", "high", "low", "close", "volume", "bid", "ask", "prev_close", "oi"}
```

### Depth (Market Depth / Order Book)
```
POST /api/v1/depth  {"apikey": "key", "symbol": "RELIANCE", "exchange": "NSE"}
→ Top 5 bid/ask levels with qty, price, orders
```

### History (OHLCV)
```
POST /api/v1/history
{"apikey": "key", "symbol": "RELIANCE", "exchange": "NSE",
 "interval": "5m",          // 1m|5m|15m|30m|1h|D
 "start_date": "2026-01-01", "end_date": "2026-03-14"}
→ [{"timestamp", "open", "high", "low", "close", "volume"}, ...]
```

### Intervals
```
POST /api/v1/intervals  {"apikey": "key"}
→ ["1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h", "D"]
```

### OptionChain
```
POST /api/v1/optionchain  {"apikey": "key", "symbol": "NIFTY", "exchange": "NFO"}
→ All strikes with CE/PE: LTP, OI, volume, bid/ask, IV, Greeks
```

### OptionGreeks / MultiOptionGreeks
```
POST /api/v1/optiongreeks  {"apikey": "key", "symbol": "NIFTY26MAR2524000CE", "exchange": "NFO"}
→ {"delta", "gamma", "theta", "vega", "iv"}
```

### OptionSymbol / SyntheticFuture / Expiry
```
POST /api/v1/optionsymbol    {"apikey": "key", "symbol": "NIFTY", "exchange": "NFO", "expiry_date": "260326", "offset": "0", "option_type": "CE"}
POST /api/v1/syntheticfuture {"apikey": "key", "symbol": "NIFTY", "exchange": "NFO", "expiry_date": "260326"}
POST /api/v1/expiry          {"apikey": "key", "symbol": "NIFTY", "exchange": "NFO"}
```

### Symbol / Search
```
POST /api/v1/symbol  {"apikey": "key", "symbol": "RELIANCE", "exchange": "NSE"}
POST /api/v1/search  {"apikey": "key", "query": "RELIANCE"}
```

### Ticker (GET endpoint)
```
GET /api/v1/ticker/{exchange}:{symbol}?interval=5m&from=2026-01-01&to=2026-03-14
Header: X-API-KEY: your_key
```

---

## Account APIs

```
POST /api/v1/funds         {"apikey": "key"}
POST /api/v1/margin        {"apikey": "key", "positions": [{...}]}   // margin calculator
POST /api/v1/orderbook     {"apikey": "key"}
POST /api/v1/tradebook     {"apikey": "key"}
POST /api/v1/positionbook  {"apikey": "key"}
POST /api/v1/holdings      {"apikey": "key"}
```

---

## Utility APIs

```
POST /api/v1/ping          {"apikey": "key"}               // health check
POST /api/v1/holidays      {"apikey": "key", "year": "2026"}
POST /api/v1/timings       {"apikey": "key", "date": "2026-03-14"}
POST /api/v1/telegram      {"apikey": "key", "message": "text"}
POST /api/v1/instruments   {"apikey": "key", "exchange": "NSE"}
POST /api/v1/analyzer/status  {"apikey": "key"}
POST /api/v1/analyzer/toggle  {"apikey": "key"}
```

---

## WebSocket Streaming

```javascript
const ws = new WebSocket('ws://host:8765');

// Subscribe LTP
ws.send(JSON.stringify({
  action: 'subscribe_ltp',
  instruments: [
    { exchange: 'NSE', symbol: 'NIFTY' },
    { exchange: 'NFO', symbol: 'NIFTY26MAR2524000CE' }
  ]
}));

// Subscribe Quote (LTP + bid/ask + volume + OI)
ws.send(JSON.stringify({
  action: 'subscribe_quote',
  instruments: [{ exchange: 'NSE', symbol: 'RELIANCE' }]
}));

// Subscribe Depth (full order book)
ws.send(JSON.stringify({
  action: 'subscribe_depth',
  instruments: [{ exchange: 'NSE', symbol: 'RELIANCE' }]
}));

// Unsubscribe
ws.send(JSON.stringify({ action: 'unsubscribe_ltp', instruments: [...] }));
```

Max: 5000 instruments per connection, 5 connections.

---

## Rate Limits (OpenAlgo-side)

| Type | Limit |
|---|---|
| Order APIs (place/modify/cancel) | 10/second |
| Smart orders | 2/second |
| General APIs (data/account) | 50/second |
| Webhooks | 100/minute |
| Login | 5/minute, 25/hour |

## Common Symbol Format

OpenAlgo uses unified symbols across all brokers:
- Equity: `RELIANCE`, `TCS`, `INFY`
- Futures: `NIFTY26MARFUT`, `BANKNIFTY26MARFUT`
- Options: `NIFTY26MAR2524000CE`, `BANKNIFTY26MAR2551000PE`
- MCX: `GOLDPETAL30MAY25FUT`, `CRUDEOIL20MAR25FUT`

## Order Constants

| Field | Values |
|---|---|
| action | `BUY`, `SELL` |
| exchange | `NSE`, `BSE`, `NFO`, `BFO`, `MCX`, `CDS`, `BCD`, `NCDEX`, `DELTA` |
| pricetype | `MARKET`, `LIMIT`, `SL`, `SL-M` |
| product | `MIS` (intraday), `CNC` (delivery), `NRML` (F&O overnight) |

---

## v2.0.0.1 New Endpoints

### System Health Monitor
```
GET /api/v1/health
→ {"cpu_percent", "memory_percent", "disk_usage", "process_count", "uptime_seconds", ...}
```

### Gamma Exposure Dashboard (GEX)
```
POST /api/v1/data/gex
{"apikey": "key", "symbol": "NIFTY", "expiry": "260326"}
→ Per-strike gamma exposure data for charting
```

### IV Smile
```
POST /api/v1/data/ivsmile
{"apikey": "key", "symbol": "NIFTY", "expiry": "260326"}
→ Implied volatility by strike for smile/skew visualization
```

### OI Profile
```
POST /api/v1/data/oiprofile
{"apikey": "key", "symbol": "NIFTY", "expiry": "260326"}
→ Open interest distribution across strikes
```

### Max Pain
```
POST /api/v1/data/maxpain
{"apikey": "key", "symbol": "NIFTY", "expiry": "260326"}
→ Max pain strike price calculation
```

### WebSocket 50-Level Depth
```javascript
// mode=4 for 50-level depth (broker-dependent: Dhan supports mode=3 max 20-level)
ws.send(JSON.stringify({
  action: 'subscribe_depth',
  instruments: [{ exchange: 'NSE', symbol: 'RELIANCE' }],
  mode: 4
}));
```
