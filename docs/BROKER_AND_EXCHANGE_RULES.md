# Broker and Exchange Order Rules

FlintTrade checks every order against a dated table of exchange, broker, and
product rules before it is sent. The same table drives the order ticket, the
Scalper preset, the option chain, the server order routes, the Practice
sandbox, and backtests.

- **Block** rules stop the order. The ticket shows the message on its reserved
  line and Place stays disabled. The server refuses the same order with HTTP 400
  (`order_rule_blocked`), or HTTP 429 when an order-rate window is full.
- **Warn** rules keep Place enabled and show the message on the same line.
- **Info** is shown, never blocks.
- A rule applies from its effective date. A rule with an end date stops applying
  after it.
- FlintTrade never changes a price the user entered. Option orders opened as a
  market or stop-market order move to a limit or stop-limit order once, when the
  contract is chosen.
- A stop-loss or target is placed as a separate order. Practice does not place
  a stop-loss or target.

The table below is generated from
`packages/core/core/src/flinttrade_core/data/order_rules.json`. Regenerate it
after editing that file:

```bash
python scripts/order_rules_table.py            # print the table
python scripts/order_rules_table.py --check docs/BROKER_AND_EXCHANGE_RULES.md
```

`{name}` in a message is filled in from the order (for example the price band
or the wait before the next order).

| Rule id | Level | Scope | Effective from | Description | Message |
|---|---|---|---|---|---|
| `options-stop-market-not-sent` | Blocks | all exchanges · all brokers · options · SL-M | 2025-08-04 | FlintTrade never sends a stop-loss market order on an option, on any exchange. | Stop-market orders aren't accepted on options. Use stop-limit. |
| `options-market-order-not-sent` | Blocks | all exchanges · all brokers · options · MARKET | 2025-08-04 | FlintTrade never sends a plain market order on an option. Every option order carries a limit price. | Market orders aren't accepted on options. Use a limit price. |
| `algo-market-orders-fo-rejected` | Blocks | NSE · all brokers · futures · MARKET, SL-M · not Dhan, Kotak Neo, Practice | 2025-08-04 | NSE rejects API market orders in F&O. Brokers convert them to limit orders with price protection, which may not fill in a fast market. | Market orders in F&O aren't accepted. Use a limit price. |
| `market-order-needs-trade-today` | Blocks | NSE · all brokers · futures and options · MARKET, SL-M | 2026-04-28 | Market orders are allowed only on contracts that have traded during the day. | This contract hasn't traded today. Use a limit price. |
| `bse-stop-limit-gap` | Blocks | BSE · all brokers · options · SL | 2026-02-09 | On BSE the stop-loss limit price must be within a set gap of the trigger price. | Stop-loss limit must be within ₹{max_gap} of trigger. |
| `nse-options-operating-range` | Warns | NSE · all brokers · options · LIMIT, SL | 2026-04-28 | NSE options trade within a daily operating range taken from the contract's exchange circuit limits. Prices outside it are rejected. | Price may be outside the exchange band (₹{low}–₹{high}). |
| `bse-lpp-sensex-expiry-day` | Warns | BSE · all brokers · options · LIMIT, SL · SENSEX · expiry day | 2026-03-12 | On SENSEX expiry day the price protection range for low-priced options narrows to ₹10. | Price may be outside the exchange band (₹{low}–₹{high}). |
| `bse-limit-price-protection` | Warns | BSE · all brokers · options · LIMIT, SL | 2025-12-01 | BSE rejects limit orders outside its price protection range. | Price may be outside the exchange band (₹{low}–₹{high}). |
| `nse-limit-price-protection-options` | Warns | NSE · all brokers · options · LIMIT, SL | 2026-04-28 | NSE rejects option limit orders priced too far from the last traded price. | Price may be outside the exchange band (₹{low}–₹{high}). |
| `order-rate-threshold` | Blocks | all exchanges · all brokers · all instruments | 2026-04-01 | Up to 10 orders per second per exchange. Higher rates need exchange registration. | Not placed. Limit is 10 orders per second per exchange. Retry in 1 second. |
| `self-built-algo-undertaking` | Warns | all exchanges · all brokers · all instruments | 2026-11-20 | Live API trading requires a client undertaking to the broker that the strategy is self-built. Losses from its logic are outside the exchange grievance process. | Orders will be sent from this computer through your broker account. Losses from your own strategy or automation aren't covered by the exchange grievance process. |
| `kotak-market-order-no-ltp` | Blocks | all exchanges · Kotak Neo · options · MARKET | 2026-04-01 | Kotak rejects market orders on contracts with no traded price for the day. | This contract hasn't traded today. Use a limit price. |
| `dhan-order-rate-limits` | Blocks | all exchanges · Dhan · all instruments | 2026-04-01 | Dhan limits orders to 10 per second, 250 per minute, 1,000 per hour and 7,000 per day, with 25 modifications per order. | Not placed. Limit is {limit} orders per {window}. Retry in {wait}. |
| `dhan-modifications-per-order` | Blocks | all exchanges · Dhan · all instruments | 2026-04-01 | Dhan accepts at most 25 changes to one order. | This order has been modified {limit} times. Place a new order. |
| `dhan-market-price-protection` | Info | all exchanges · Dhan · futures and options · MARKET | 2026-04-01 | Dhan sends API market orders as limit orders with market price protection. The band depends on the instrument and time of day. | Market orders are sent as limits near the last price and may not fill. |
| `kotak-market-price-protection` | Warns | all exchanges · Kotak Neo · all instruments · MARKET | 2026-04-01 | Kotak sends market orders as limit orders within a protection band of the last price. | Market orders are sent as limits within {band} of the last price and may not fill. |
| `dhan-intraday-square-off` | Warns | all exchanges · Dhan · futures and options · MIS | 2026-04-01 | Dhan squares off open intraday F&O positions from 15:25. | Intraday F&O positions are closed from 15:25. Exit before then. |
| `practice-market-price-cap` | Info | all exchanges · Practice · all instruments · MARKET, SL-M | 2025-08-04 | Practice and backtests fill a market order only within 3% of the last price. A market order on an option in a backtest becomes a limit at that cap. | Market orders fill within 3% of the last price. |
| `practice-bracket-unsupported` | Blocks | all exchanges · Practice · all instruments | 2025-08-04 | Practice does not place a stop-loss or target. A Practice bracket is refused. | Not placed. Remove SL and Target for Practice orders. |
| `broker-separate-stop-loss-target` | Info | all exchanges · all brokers · all instruments | 2025-08-04 | A stop-loss and target are placed as separate orders. | Stop-loss and target are placed as separate orders with this broker. |
| `stop-loss-limit-at-trigger` | Warns | all exchanges · all brokers · all instruments · SL | 2025-08-04 | A stop-loss limit equal to its trigger leaves no room to fill once the trigger is hit. FlintTrade places its own stop-loss legs past the trigger, as far as the exchange gap and price band allow, or by the default buffer where no exchange limit applies. | Limit equals the trigger and may not fill. Set it past the trigger. |
| `exit-position-closed` | Blocks | all exchanges · all brokers · all instruments | 2025-08-04 | An exit ticket only reduces an open position. The position is read again just before sending, and when it is already flat the exit is not sent. | Position is closed. Order not sent. |
| `exit-quantity-capped` | Warns | all exchanges · all brokers · all instruments | 2025-08-04 | An exit ticket never opens a new position. A quantity above the open position is reduced to the open quantity before sending. | Quantity reduced to {qty}, the open position. |
