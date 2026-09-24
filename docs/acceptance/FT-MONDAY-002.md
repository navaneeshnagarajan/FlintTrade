# FT-MONDAY-002 — Native Dhan + Kotak Neo Connected (read) / API smoke

Product tip for GitHub issue [#253](https://github.com/navaneeshnagarajan/FlintTrade/issues/253)
on tracking PR #257. Native Dhan + Kotak Neo Connected (read) / API smoke
on the MSI static-IP host. Live place stays fail-closed. Native HTTP
cutover (Task 9D / Task 7C.2) is not lifted.

## Finding

Native Connected (read) path: native Dhan + Kotak Neo connected on the MSI
static-IP host with **non-funded** accounts → live REST API responses
(quotes / depth / historical / option chain where the SDK allows),
latency, and honest errors. This historical acceptance predates the v3 async
feed wiring and therefore proves REST reads only, not a live SFeed or order
feed.

## Locked behaviour

- Kotak Neo has **no sandbox**. Live read / API smoke only until funded
  Live unlock. Never offer “Neo Practice”. Operator copy is
  `Live read only until funded unlock.`
- Prefer **native** Dhan + Neo. OpenAlgo is Settings / fallback only —
  not the primary connect CTA.
- `dhanhq` stays on latest stable **2.2.0** (not RC).
- Neo v3 installs the `kotakneoapi` **3.0.7** distribution from exact
  upstream Git provenance. Runtime `main` is
  `5bb34fae39c4a52a0e6b59d7e2d17090cafc340c`; release tag `v3.0.7` peels
  to `53cccc45fe56a193b30ffce3c03c71c5c0378538`. The old
  `neo-api-client` distribution is prohibited, while imports intentionally
  remain `neo_api_client`. HS feed is retired. The async SFeed and order-feed
  lifecycle is wired and locally synthetic-tested; this tip's historical
  broker evidence covers REST reads only.

## Modes (UX lock)

| Mode | Meaning |
|---|---|
| **Explore** | Sample-only. No Live broker order authority. |
| **Practice** | FlintTrade `SandboxEngine` fills (primary paper). Not a broker sandbox. |
| **Live** | Fail-closed until MSI native read smoke is trusted **and** funded unlock. |

Dhan Sandbox remains optional paper via OpenAlgo only. It is not the
primary Practice fill path.

## MSI broker chrome

**Connected (read)** / **API smoke** paints only after successful
persisted REST smoke evidence (`read_smoke_ok`) — not login-only. A
failed login or read never fakes Connected. That chrome must never
imply placeable Live orders.

This native read smoke does **not** require funded Live unlock.

## OpenAlgo

Settings / fallback only. Not the primary connect CTA.

## AI (shared acceptance bar)

Chat may use live reads when an LLM is configured. Suggest stays
illustrative. Never paint green Connected without a real LLM
(FT-AI-004). AI-on-live-reads is the FT-MONDAY-003 / #256 product tip.

## Acceptance

- Both brokers connect without a fake Connected state.
  **Connected (read)** / **API smoke** paints only after successful
  persisted REST smoke evidence — never login-only. A failed login or
  read never fakes Connected.
- Live reads work or fail honestly (REST quotes / depth / historical /
  option chain where the SDK allows). Kotak Neo's recorded smoke covers only
  REST reads; a live SFeed / order-feed session was not required for this
  acceptance.
- No funded Live unlock required for this native read smoke.
- Neo never offered as Practice; copy stays
  `Live read only until funded unlock.`
- Prefer native; OpenAlgo remains fallback only.
- `dhanhq==2.2.0` (latest stable). `kotakneoapi==3.0.7` from the exact
  runtime Git commit, checked separately against the peeled v3.0.7 release.
- Live place stays fail-closed.

## Out of scope

- Native HTTP cutover (Task 9D / Task 7C.2) — freeze stays.
- Funded Live order placement.
- AI Chat on live reads (FT-MONDAY-003 / #256) — shipped on that tip.
- Live-account and market-hours SFeed/order-feed proof, Live catalogue
  promotion, and cross-platform v3 lifecycle proof. Broker sandbox proof is
  unavailable because Neo offers no sandbox.
