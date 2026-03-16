# FlintTrade Operations

## Market Hours (IST)

| Exchange | Open | Close | Deploy safe after |
|---|---|---|---|
| NSE/BSE/NFO/BFO | 9:15 AM | 3:30 PM | 3:45 PM |
| CDS/BCD | 9:00 AM | 5:00 PM | 5:15 PM |
| MCX | 9:00 AM | 11:55 PM | 12:00 AM (midnight) |

## Deploy Freeze

**If you trade equity/F&O only:** No deploys 9:15 AM - 3:30 PM
**If you trade MCX commodities:** No deploys 9:00 AM - 11:55 PM

## Daily Timeline (equity/F&O trader)

| Time | Action |
|---|---|
| 8:30 AM | Auto-login cron fires |
| 9:15-3:30 | MARKET HOURS — deploy freeze |
| 3:45-6:00 PM | Maintenance window |
| 6:00 PM+ | Development |

## Daily Timeline (MCX trader)

| Time | Action |
|---|---|
| 8:30 AM | Auto-login cron fires |
| 9:00 AM-11:55 PM | MARKET HOURS — deploy freeze |
| 12:00 AM-8:30 AM | Maintenance + development window |

## Emergency: OpenAlgo Action Center → disable strategy. NEVER restart with open positions.

## Crypto Trading (Delta Exchange)

Delta Exchange trades 24/7. If you hold crypto positions:
- Check all positions before ANY deploy: `make health`
- Crypto has no market close — there is no safe deploy window
- Use blue-green deployment (infra/nginx/) to avoid downtime
- INR settlement — no stablecoin needed
- Derivatives = speculative income (not 30% crypto tax)
