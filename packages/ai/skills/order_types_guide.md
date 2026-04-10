---
name: order_types_guide
category: execution
description: When to use each order type — MARKET, LIMIT, SL, SL-M, IOC, GTC, AMO, bracket, cover
---
# Order Types Guide

## MARKET vs LIMIT

| Order Type | Use When | Risk |
|------------|----------|------|
| MARKET | Immediate fill is critical (stop triggered, news reaction) | Slippage — you get the best available price, not a specific one |
| LIMIT | You have a target entry/exit price and can afford to wait | May not fill if price never reaches your level |

In illiquid instruments (mid-cap options, MCX contracts), always prefer LIMIT orders. MARKET orders in illiquid contracts can suffer 2–5% slippage.

## SL and SL-M (Stop Loss)

- **SL (Stop-Limit):** Triggers at the trigger price, then places a LIMIT order. Safer in liquid markets — ensures you do not get filled at an unreasonable price.
- **SL-M (Stop-Market):** Triggers at the trigger price, then places a MARKET order. Guarantees a fill but not the price. Use only in highly liquid instruments (Nifty/BankNifty options, large-cap equities).

Rule: **SL-M for indices and large-caps; SL for everything else.**

## Slippage Considerations

- Nifty ATM options: typical slippage 0.5–1 tick (0.05–0.10 Rs)
- BankNifty ATM options: 1–2 ticks
- Mid-cap stocks: 0.1–0.5% of price
- MCX contracts: 1–3 ticks depending on time of day

Include estimated slippage in all P&L projections. Adjust limit prices 1–2 ticks beyond the current market to improve fill probability.

## Bracket Orders

A bracket order places a main order with a simultaneous target and stop-loss leg. When one leg fills, the other is cancelled automatically.

- Ideal for intraday scalping where you know your R:R before entry.
- Not all brokers support bracket orders via OpenAlgo — check broker capabilities.

## Cover Orders

A cover order pairs a MARKET entry with a mandatory stop-loss. Lower margin requirement than a naked position. Available intraday only (MIS).

## AMO (After Market Orders)

AMO orders are placed after market hours (15:30–09:00 IST) and queued for the next session's opening.

- Placed as LIMIT orders at a price you are comfortable with at open.
- Useful for delivery (CNC) trades based on end-of-day analysis.
- Do **not** use AMO for F&O — premium values at open will differ from your analysis.

## IOC vs GTC (Day vs Good Till Cancelled)

- **IOC (Immediate or Cancel):** Fills what it can immediately; cancels the rest. Use for partial fills in large quantity orders.
- **Day order (default):** Expires at end of session if unfilled.
- **GTC:** Remains active until filled or manually cancelled. Useful for CNC target orders in delivery portfolios. Verify your broker supports GTC via OpenAlgo.
