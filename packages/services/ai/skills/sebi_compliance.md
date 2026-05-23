---
name: sebi_compliance
category: compliance
description: SEBI regulations for algorithmic trading, audit trails, and reporting obligations
---
# SEBI Compliance for Algorithmic Trading

## Algorithmic Trading Registration

SEBI requires all algorithmic trading to be routed through a SEBI-registered broker with algo approval. Retail clients cannot send orders directly to exchanges — all orders must go through a broker's risk management system (RMS).

FlintTrade routes all orders through OpenAlgo, which connects to registered brokers. FlintTrade itself does not connect to exchanges directly.

## Audit Trail Requirements (SEBI Circular SEBI/HO/MRD2/PoD-2/P/CIR/2021/6)

Every algorithmic trade must maintain a complete audit trail for **5 years**:
- Timestamp of order generation (millisecond precision)
- Order parameters (symbol, exchange, quantity, price, side)
- Strategy identifier
- Modification and cancellation history
- Execution details and fills

FlintTrade's `data` package (audit logger) handles this via DuckDB at `~/.flinttrade/data/audit.duckdb`.

## Order-to-Trade Ratio

SEBI monitors order-to-trade ratio (OTR). Excessive order cancellations trigger scrutiny.
- Recommended OTR < 20 for liquid stocks
- Never place orders with intent to cancel immediately

## Mandatory Kill Switch

SEBI mandates a kill switch that immediately cancels all open orders and prevents new orders. Implemented in FlintTrade's Telegram bot (`/kill` command) and risk panel widget.

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
