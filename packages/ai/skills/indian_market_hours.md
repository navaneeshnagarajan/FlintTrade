---
name: indian_market_hours
category: data
description: NSE/BSE/MCX/CDS trading hours, pre-market, post-market, holidays, and IST timezone
---
# Indian Market Trading Hours (IST = UTC+5:30)

## Equity (NSE / BSE)

| Session | Time (IST) | Notes |
|---|---|---|
| Pre-open call auction | 09:00–09:08 | Order entry only, no matching |
| Pre-open matching | 09:08–09:15 | Price discovery, block matching |
| Normal market | 09:15–15:30 | Continuous order matching |
| Closing price session | 15:30–15:40 | VWAP of last 30 min used |
| Post-market session | 15:40–16:00 | Only at closing price |

## F&O (NSE Futures & Options — NFO segment)

| Session | Time (IST) |
|---|---|
| Normal trading | 09:15–15:30 |
| Expiry auto-square-off | 15:20–15:25 on expiry Thursday |

**Weekly expiry:** Thursday (Nifty 50, BankNifty, FinNifty)
**Monthly expiry:** Last Thursday of the month

## Currency Derivatives (CDS)

- Trading hours: 09:00–17:00 IST (extended vs equity)
- USDINR, EURINR, GBPINR, JPYINR pairs

## Commodities (MCX)

| Commodity | Session (IST) |
|---|---|
| Agri (non-perishable) | 09:00–21:00 / 09:00–17:00 (Fridays) |
| Metals (Gold, Silver, Copper) | 09:00–23:30 |
| Energy (Crude, NG) | 09:00–23:30 |
| MCX iCOMDEX | 09:00–23:30 |

Note: MCX hours follow US/international market hours — crude oil and metals trade until 23:30 IST on weekdays.

## Market Holidays

NSE/BSE observe approximately 14–16 holidays per year. Key recurring holidays:
Republic Day (26 Jan), Holi, Good Friday, Ambedkar Jayanti, Maharashtra Day, Independence Day (15 Aug), Gandhi Jayanti (2 Oct), Dussehra, Diwali Laxmi Puja, Gurunanak Jayanti, Christmas (25 Dec).

Exact holiday list changes annually. Fetch programmatically:
```
POST /api/v1/holidays  → returns list of NSE/BSE holiday dates
```

## Time Zone Handling

Always store timestamps in UTC internally. Convert to IST for display.
```python
from zoneinfo import ZoneInfo
IST = ZoneInfo("Asia/Kolkata")
# UTC+5:30 — no DST
```

## Intraday Cutoffs

- Last entry for intraday (MIS) positions: 15:15 IST
- MIS auto-square-off by broker: typically 15:15–15:20 IST
- Always close before 15:10 IST to avoid slippage at auto-square-off
