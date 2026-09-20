# FT-MONDAY-002 — Native Dhan + Kotak Neo dual-broker smoke

Maintainer tracking lock (docs/acceptance only). This page is the Monday
PASS bar for GitHub issue [#253](https://github.com/navaneeshnagarajan/FlintTrade/issues/253).
It does **not** ship product connect, broker chrome, or the Neo v3 SDK bump.

## Finding

Parallel Monday path: native Dhan + Kotak Neo connected on the MSI host
(static IP) with **non-funded** accounts → live API responses (ticks /
depth / hist / chain where the SDK allows), latency, and honest errors —
fix during the Monday session.

## Locked (2026-09-20)

- Kotak Neo has **no sandbox**. Live read / API smoke only until funded
  Live unlock. Never offer “Neo Practice”. Operator copy is
  `Live read only until funded unlock.`
- Prefer **native** Dhan + Neo. OpenAlgo is Settings / fallback only —
  not the Monday primary connect CTA.
- Keep `dhanhq` stable. Neo v3 bump (`kotakneoapi` 3.x) is in scope for
  the product PR, not this tracking change.

## Modes (UX lock)

| Mode | Meaning |
|---|---|
| **Explore** | Sample-only. No Live broker order authority. |
| **Practice** | FlintTrade `SandboxEngine` fills (primary paper). Not a broker sandbox. |
| **Live** | Fail-closed until MSI native smoke is trusted **and** funded unlock. |

Dhan Sandbox remains optional paper via OpenAlgo only. It is not the
Monday primary fill path.

## MSI broker chrome

When non-funded live reads work, Dhan and Neo show **Connected (read)**
or **API smoke**. That chrome must never imply placeable Live orders.
A failed read fails honestly — never a fake Connected.

Monday smoke does **not** require funded Live unlock.

## OpenAlgo

Settings / fallback only. Not the Monday primary connect CTA.

## AI (shared PASS bar)

Chat may use live reads when an LLM is configured. Suggest stays
illustrative. Never paint green Connected without a real LLM
(FT-AI-004).

## Acceptance

- Both brokers connect without a fake Connected state.
- Live reads work or fail honestly (ticks / depth / hist / chain where
  the SDK allows).
- No funded Live unlock required for Monday smoke.
- Neo never offered as Practice; copy stays
  `Live read only until funded unlock.`
- Prefer native; OpenAlgo remains fallback only.
- `dhanhq` stays on the current pin; `kotakneoapi` 3.x is the in-scope
  Neo v3 bump for the product PR.

## Out of scope for this tracking PR

- Native HTTP cutover (Task 9D / Task 7C.2), adapter activation, or
  Brokers UX implementation.
- `kotakneoapi` 3.x / `uv.lock` / `brokers.lock` edits.
- Funded Live order placement.
- Changing Learn → Practice Trading product chrome (follow-on product
  PR must drop any “Kotak Neo Sandbox” / “Neo Practice” offer).
