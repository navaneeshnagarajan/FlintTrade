# Static IP Setup

Many Indian broker APIs require an allow-listed static public IP before live
orders are accepted. FlintTrade does not apply for this on your behalf; you do
it directly in your broker's developer console.

## Checklist

1. Get a static public IP from your ISP, cloud VM, VPN provider, or office
   network.
2. Confirm the IP from the exact machine or network that will run FlintTrade.
3. Add that IP in the broker developer console.
4. Wait for the broker's activation window to complete.
5. Test in Explore and Practice first, then unlock Live only after the broker
   dashboard shows the IP as active.

## Broker Notes

| Broker | Where to configure | Notes |
|---|---|---|
| Dhan | DhanHQ / profile API settings | Dhan API access is typically tied to an API token and IP allow-list. Re-check the broker UI after token rotation. |
| Zerodha | Kite Connect developer console | Keep app callback URLs and IP entries aligned with the deployed backend. |
| Upstox | Upstox developer console | Verify whether the app is in sandbox or production before enabling Live mode. |
| Kotak Neo | Kotak developer console / Neo API onboarding | Follow the broker's current onboarding email or console instructions. Neo has no sandbox — live read / API smoke only until funded unlock. |
| IndMoney | Broker/API onboarding channel | Confirm production access and IP rules directly with the broker. |

## Monday dual-broker smoke (FT-MONDAY-002)

The locked Monday path is **native** Dhan + Kotak Neo on the MSI host
whose public IP is allow-listed at both brokers. Smoke uses **non-funded**
accounts and live REST API reads (quotes / depth / hist / chain where the
SDK allows). Live SFeed / `create_websocket` is not wired for Neo in this
tip. That is REST API smoke, not funded Live unlock.

When those reads succeed (not login-only), chrome is **Connected (read)**
/ **API smoke** — never imply placeable Live orders. Neo copy is
`Live read only until funded unlock.` Prefer native; OpenAlgo is
Settings / fallback only. Keep personal IPs out of this repository.

See [FT-MONDAY-002](../acceptance/FT-MONDAY-002.md).

## FlintTrade Boundary

FlintTrade stores no personal public IP in committed docs or examples. Keep IPs
in your broker console and local `.env` or deployment configuration only.
Changing networks without updating the broker allow-list should make live
orders fail closed.
