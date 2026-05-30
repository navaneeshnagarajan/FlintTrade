---
name: sebi_compliance
category: compliance
description: SEBI regulations for algorithmic trading, audit trails, and reporting obligations
---
# SEBI Compliance for Algorithmic Trading

## Algorithmic Trading Registration

For Indian markets, algorithmic trading is routed through a SEBI-registered broker with algo approval. Retail clients cannot send orders directly to exchanges — all orders go through a broker's risk management system (RMS).

FlintTrade routes all orders through OpenAlgo, which connects to registered brokers. FlintTrade itself does not connect to exchanges directly.

## Audit Trail (operator records)

For personal-use algo trading it is good practice to keep a complete local audit trail:
- Timestamp of order generation (millisecond precision)
- Order parameters (symbol, exchange, quantity, price, side)
- Strategy identifier
- Modification and cancellation history
- Execution details and fills

FlintTrade's `data` package (append-only audit logger) keeps this as daily JSONL files under `~/.flinttrade/archive/audit/`. Retention is operator-controlled — FlintTrade does not delete entries, and how long they are kept is up to the operator.

## Order-to-Trade Ratio

Exchanges monitor the order-to-trade ratio (OTR). Excessive order cancellations can trigger scrutiny.
- Recommended OTR < 20 for liquid stocks
- Never place orders with intent to cancel immediately

## Kill Switch

A kill switch that immediately cancels all open orders and prevents new orders is good practice for algo trading. Implemented in FlintTrade's Telegram bot (`/kill` command) and risk panel widget.

## Risk Controls (NSE RMS)

Exchange-level checks (automatic):
- Price bands: Circuit limits (2%, 5%, 10%, 20%) freeze trading temporarily
- Quantity limits: Max order quantity per symbol enforced by broker RMS
- Margin: Orders rejected if insufficient margin

FlintTrade-level checks:
- Daily loss limit (configurable in workspace.json)
- Max position size per symbol
- Max concurrent open orders

## Reporting Obligations

Brokers report to SEBI; retail traders must:
- File ITR with capital gains — F&O is business income (not STCG/LTCG)
- F&O P&L: all profits taxable at slab rate; losses can be carried forward 8 years
- Maintain trade records — FlintTrade's tradebook exports serve as supporting documents

## Privacy

Never log or store: PAN, Aadhaar, bank account details, demat account numbers, or broker credentials in FlintTrade's database. These remain in OpenAlgo's encrypted credential store only.
