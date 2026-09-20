# FT-MONDAY-002 — Native Dhan + Kotak Neo dual-broker smoke

Product tip for GitHub issue [#253](https://github.com/navaneeshnagarajan/FlintTrade/issues/253)
on tracking PR #257. Native Dhan + Kotak Neo Connected (read) / API smoke
on the MSI static-IP host. Live place stays fail-closed. Native HTTP
cutover (Task 9D / Task 7C.2) is not lifted.

## Finding

Parallel Monday path: native Dhan + Kotak Neo connected on the MSI host
(static IP) with **non-funded** accounts → live REST API responses
(quotes / depth / historical / option chain where the SDK allows),
latency, and honest errors — fix during the Monday session. Live SFeed /
`create_websocket` is not wired in this tip.

## Locked (2026-09-20)

- Kotak Neo has **no sandbox**. Live read / API smoke only until funded
  Live unlock. Never offer “Neo Practice”. Operator copy is
  `Live read only until funded unlock.`
- Prefer **native** Dhan + Neo. OpenAlgo is Settings / fallback only —
  not the Monday primary connect CTA.
- `dhanhq` stays on latest stable **2.2.0** (not RC).
- Neo v3 is PyPI `kotakneoapi` **3.0.7**. The v2 `neo-api-client` git
  pin is gone. HS feed is retired. Monday Neo path is **REST-only**
  (quotes / depth / historical / option chain where the SDK allows).
  Live SFeed / `create_websocket` is **not** wired in this tip (out of
  scope / deferred).

## Modes (UX lock)

| Mode | Meaning |
|---|---|
| **Explore** | Sample-only. No Live broker order authority. |
| **Practice** | FlintTrade `SandboxEngine` fills (primary paper). Not a broker sandbox. |
| **Live** | Fail-closed until MSI native smoke is trusted **and** funded unlock. |

Dhan Sandbox remains optional paper via OpenAlgo only. It is not the
Monday primary fill path.

## MSI broker chrome

**Connected (read)** / **API smoke** paints only after successful
persisted REST smoke evidence (`read_smoke_ok`) — not login-only. A
failed login or read never fakes Connected. That chrome must never
imply placeable Live orders.

Monday smoke does **not** require funded Live unlock.

## OpenAlgo

Settings / fallback only. Not the Monday primary connect CTA.

## AI (shared PASS bar)

Chat may use live reads when an LLM is configured. Suggest stays
illustrative. Never paint green Connected without a real LLM
(FT-AI-004). This tip does **not** implement AI-on-live-reads
(FT-MONDAY-003 / #256).

## Acceptance

- Both brokers connect without a fake Connected state.
  **Connected (read)** / **API smoke** paints only after successful
  persisted REST smoke evidence — never login-only. A failed login or
  read never fakes Connected.
- Live reads work or fail honestly (REST quotes / depth / historical /
  option chain where the SDK allows). Monday Neo smoke is REST-only;
  live SFeed / `create_websocket` is not wired and is not required for
  Monday PASS.
- No funded Live unlock required for Monday smoke.
- Neo never offered as Practice; copy stays
  `Live read only until funded unlock.`
- Prefer native; OpenAlgo remains fallback only.
- `dhanhq==2.2.0` (latest stable). `kotakneoapi==3.0.7` from PyPI.
- Live place stays fail-closed.

## Out of scope

- Native HTTP cutover (Task 9D / Task 7C.2) — freeze stays.
- Funded Live order placement.
- AI Suggest on live reads (FT-MONDAY-003 / #256).
- Live SFeed / `create_websocket` — not wired; deferred.
