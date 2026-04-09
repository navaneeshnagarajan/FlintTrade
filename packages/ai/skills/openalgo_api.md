---
name: openalgo_api
category: execution
description: OpenAlgo REST API reference for orders, accounts, and market data endpoints
---
# OpenAlgo API Reference

FlintTrade routes all broker operations through OpenAlgo (port 5000). Never call broker APIs directly.

## Order Endpoints (POST /api/v1/)

| Endpoint | Key Parameters |
|---|---|
| `placeorder` | symbol, exchange, action (BUY/SELL), product (MIS/CNC/NRML), quantity, price_type (MARKET/LIMIT/SL/SL-M) |
| `placesmartorder` | same as placeorder + position_size for auto-quantity |
| `modifyorder` | orderid, quantity, price_type, price |
| `cancelorder` | orderid |
| `cancelallorder` | — cancels all open orders |
| `closeposition` | — squares off all net positions |
| `basketorder` | orders: list of order dicts |

### Product Types
- `MIS` — Intraday margin (NSE/BSE/MCX)
- `CNC` — Delivery / long-term hold (equity only)
- `NRML` — Overnight futures/options position

### Price Types
- `MARKET` — execute at best available price
- `LIMIT` — execute only at specified price or better
- `SL` — stop-loss limit order
- `SL-M` — stop-loss market order

## Account Endpoints

| Endpoint | Returns |
|---|---|
| `funds` | Available margin, used margin, net liquidating value |
| `orderbook` | All orders with status (open, complete, rejected) |
| `tradebook` | All executed trades today |
| `positionbook` | All open positions (intraday + overnight) |
| `holdings` | Long-term equity holdings |
| `margin` | Margin required for a hypothetical order |

## Data Endpoints (POST)

| Endpoint | Use Case |
|---|---|
| `quotes` | Live LTP, OHLC, volume for a single symbol |
| `multiquotes` | Live quotes for up to 50 symbols |
| `depth` | Level 2 order book (bid/ask 5 levels) |
| `history` | OHLCV candles — specify symbol, exchange, interval, start_date, end_date |
| `optionchain` | Full option chain for an underlying — specify expiry |
| `optiongreeks` | Delta, gamma, theta, vega for an option |
| `search` | Fuzzy symbol search |

## WebSocket (port 8765)
```json
{ "action": "authenticate", "api_key": "<key>" }
{ "action": "subscribe", "symbols": [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}], "mode": "LTP" }
```
Modes: `LTP` (1), `Quote` (2), `Depth` (4)

## Rate Limits
- Orders: 10/s | Smart orders: 2/s | General: 50/s

## Common Exchanges
`NSE` (equity), `BSE` (equity), `NFO` (F&O), `MCX` (commodities), `CDS` (currency), `NSE_INDEX` (indices)
