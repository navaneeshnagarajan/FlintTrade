---
name: indian_market_hours
category: data
description: NSE/BSE/MCX/CDS trading hours, pre-market, post-market, holidays, and IST timezone
---
# Indian Market Trading Hours (IST = UTC+5:30)

## Equity (NSE / BSE)

SEBI Closing Auction Session (CAS) has been live from 3 Aug 2026 for
F&O underlyings. Hours below are as of Aug 2026. Cash is never green
"open" (continuous) after 15:15 on CAS names; CAS is not closed.
Non-CAS cash still trades continuous to 15:30. The September 2026
consultation is not product UI. Closing price is the CAS auction, not
a VWAP of the last 30 minutes.

| Session | Time (IST) | Notes |
|---|---|---|
| Pre-open call auction | 09:00–09:08 | Order entry only, no matching |
| Pre-open matching | 09:08–09:15 | Price discovery, block matching |
| Continuous | ~09:15–15:15 | Continuous matching on CAS names |
| CAS | 15:15–15:35 | Closing Auction Session (F&O underlyings) |
| Matching | ~15:35–15:50 | Auction match; not continuous, not closed |
| Post-close | 15:50–16:00 | Post-close session |
| Closed | after 16:00 | Day session over |
| Non-CAS cash continuous | 09:15–15:30 | Names not in CAS still CTS to 15:30 |

TopBar shows one active chip — Continuous · CAS · Matching · Post-close ·
Closed — with tooltip/title as the window (for example
`CAS · 15:15–15:35 (as of Aug 2026)`). Market Clock follows the same
timeline. Never emit flat "Market open until 15:30" or "VWAP last 30 min"
closing-price copy.

## F&O (NSE Futures & Options — NFO segment)

| Session | Time (IST) |
|---|---|
| Continuous | 09:15–15:40 |
| Expiry auto-square-off | 15:20–15:25 on expiry Thursday |

Equity F&O remains open until 15:40 while cash CAS runs. UI may show a
secondary `F&O open · till 15:40` chip after cash continuous ends.

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
