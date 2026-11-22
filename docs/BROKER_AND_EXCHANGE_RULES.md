# Broker and Exchange Order Rules

FlintTrade checks every order against a dated table of exchange, broker, and
product rules before it is sent. The same table drives the order ticket, the
Scalper preset, the option chain, the server order routes, the Practice
sandbox, and backtests.

- **Block** rules stop the order. The ticket shows the message on its reserved
  line and Place stays disabled. The server refuses the same order with HTTP 400
  (`order_rule_blocked`), or HTTP 429 when a broker order-rate window is full.
- **Warn** rules keep Place enabled and show the message on the same line.
- A rule applies from its effective date. A rule with an end date stops applying
  after it.
- FlintTrade never changes a price the user entered. Option orders opened as a
  market or stop-market order move to a limit or stop-limit order once, when the
  contract is chosen.
- Stop-loss and target are attached to the entry order with Dhan and Practice.
  Other brokers place them as separate orders.

The table below is generated from
`packages/core/core/src/flinttrade_core/data/order_rules.json`. Regenerate it
after editing that file:

```bash
python scripts/order_rules_table.py            # print the table
python scripts/order_rules_table.py --check docs/BROKER_AND_EXCHANGE_RULES.md
```

`{name}` in a message is filled in from the order (for example the price band
or the wait before the next order).

| Rule id | Scope | Effective from | Description | Message |
|---|---|---|---|---|
| `sl-m-not-allowed-options` | NSE · all brokers · options · SL-M | 2026-04-28 | Stop-loss market orders are not allowed on options. Use stop-loss limit. | Stop-market isn't available for options; use stop-limit. |
| `options-stop-market-not-sent` | all exchanges · all brokers · options · SL-M | 2025-08-04 | FlintTrade never sends a stop-loss market order on an option, on any exchange. | Stop-market isn't available for options; use stop-limit. |
| `options-market-order-not-sent` | all exchanges · all brokers · options · MARKET | 2025-08-04 | FlintTrade never sends a plain market order on an option. Every option order carries a limit price. | Market orders aren't accepted on options. Use a limit price. |
| `algo-market-orders-fo-rejected` | NSE · all brokers · futures · MARKET, SL-M · not Dhan, Kotak Neo, Practice | 2025-08-04 | API market orders in F&O are sent as limit orders with price protection and may not fill in a fast market. | Market orders in F&O are not accepted — use a limit price. |
| `market-order-needs-trade-today` | NSE · all brokers · futures and options · MARKET, SL-M | 2026-04-28 | Market orders are allowed only on contracts that have traded during the day. | This contract hasn't traded today — use a limit price. |
| `bse-stop-limit-gap` | BSE · all brokers · options · SL | 2026-02-09 | On BSE the stop-loss limit price must be within a set gap of the trigger price. | Stop-loss limit must be within ₹{max_gap} of trigger. |
| `nse-options-operating-range` | NSE · all brokers · options · LIMIT, SL | 2026-04-28 | NSE options trade within a daily operating range. Prices outside it are rejected. | Enter a price within ₹{low}–₹{high}. |
| `bse-lpp-sensex-expiry-day` | BSE · all brokers · options · LIMIT, SL · SENSEX · expiry day | 2026-03-12 | On SENSEX expiry day the price protection range for low-priced options narrows to ₹10. | Price may be outside the exchange band (₹{low}–₹{high}). |
| `bse-limit-price-protection` | BSE · all brokers · options · LIMIT, SL | 2025-12-01 | BSE rejects limit orders outside its price protection range. | Price may be outside the exchange band (₹{low}–₹{high}). |
| `nse-limit-price-protection-options` | NSE · all brokers · options · LIMIT, SL | 2026-04-28 | NSE rejects option limit orders priced too far from the last traded price. | Price may be outside the exchange band (₹{low}–₹{high}). |
| `order-rate-threshold` | all exchanges · all brokers · all instruments | 2026-04-01 | Up to 10 orders per second per exchange. Higher rates need exchange registration. | Wait a moment — the limit is 10 orders per second per exchange. |
| `self-built-algo-undertaking` | all exchanges · all brokers · all instruments | 2026-11-20 | Live API trading requires a client undertaking to the broker that the strategy is self-built. Losses from its logic are outside the exchange grievance process. | Orders will be sent from this computer through your broker account. Losses from your own strategy or automation aren't covered by the exchange grievance process. |
| `kotak-market-order-no-ltp` | all exchanges · Kotak Neo · options · MARKET | 2026-04-01 | Kotak rejects market orders on contracts with no traded price for the day. | This contract hasn't traded today — use a limit price. |
| `dhan-order-rate-limits` | all exchanges · Dhan · all instruments | 2026-04-01 | Dhan limits orders to 10 per second, 250 per minute, 1,000 per hour and 7,000 per day, with 25 modifications per order. | Wait {wait} — the limit is {limit} orders per {window}. |
| `dhan-modifications-per-order` | all exchanges · Dhan · all instruments | 2026-04-01 | Dhan accepts at most 25 changes to one order. | This order has already been modified {limit} times — place a new order. |
| `dhan-market-price-protection` | all exchanges · Dhan · futures and options · MARKET, SL-M | 2026-04-01 | Dhan sends API market orders as limit orders with market price protection. The band depends on the instrument and time of day. | Market orders are sent as limits near the last price and may not fill. |
| `kotak-market-price-protection` | all exchanges · Kotak Neo · all instruments · MARKET, SL-M | 2026-04-01 | Kotak sends market orders as limit orders within a protection band of the last price. | Market orders are sent as limits within about {band} of the last price and may not fill. |
| `dhan-intraday-square-off` | all exchanges · Dhan · futures and options · MIS | 2026-04-01 | Dhan squares off open intraday F&O positions from 15:25. | Intraday F&O positions are closed from 15:25 — exit before then. |
| `practice-market-price-cap` | all exchanges · Practice · all instruments · MARKET, SL-M | 2025-08-04 | Practice and backtests fill a market order only within 3% of the last price. A market order on an option in a backtest becomes a limit at that cap. | Practice fills a market order only within 3% of the last price. |
| `broker-separate-stop-loss-target` | all exchanges · all brokers · all instruments | 2025-08-04 | Brokers without attached orders get the stop-loss and target as separate orders. | Stop-loss and target are placed as separate orders with this broker. |
