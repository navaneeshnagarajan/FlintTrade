# SEBI Algo Trading Compliance (effective April 1, 2026)

| Requirement | FlintTrade Implementation |
|---|---|
| Static IP | Configured in broker dashboard (dual WAN IPs) |
| Max 10 OPS | Rate limiter in engine + OpenAlgo built-in |
| Kill switch | Telegram /killswitch + UI + auto P&L trigger |
| 5-year audit logs | Append-only on /data partition (5TB HDD) |
| Algo registration | Strategy configs exported for broker |
| Daily session management | TOTP auto-login cron in infra/cron/ |

## Exchange-Specific Considerations

| Exchange | Expiry time | Notes |
|---|---|---|
| NFO | 3:30 PM | Standard equity options |
| BFO | 3:30 PM | BSE options |
| CDS | 12:30 PM | Currency options expire EARLIER |
| MCX | 11:30 PM (varies) | Each commodity has different expiry time |

MCX commodities: GOLD/SILVER expiry at 11:30 PM, CRUDEOIL at 11:30 PM, NATURALGAS at 11:30 PM.
Always check per-commodity expiry via OpenAlgo's /api/v1/expiry endpoint.

## Crypto (Delta Exchange)
- Delta Exchange is FIU-India registered (AML/KYC compliant)
- INR settlement — derivatives classified as speculative business income
- NOT subject to 30% crypto capital gains tax or 1% TDS (derivatives exemption)
- SEBI does not regulate crypto — FIU-India does. Different compliance framework.
- API key + IP whitelisting required (same as equity brokers)
