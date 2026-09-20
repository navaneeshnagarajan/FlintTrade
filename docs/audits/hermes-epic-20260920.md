# Hermes epic backlog — 2026-09-20

**Epic ID:** `FT-HERMES-001`
**Status:** Backlog lock only. No product or implementation code in this
document's landing PR. Product spikes stay parked until the Pass 9
honesty pack clears; each spike then opens as its own PR.

This is the public umbrella for **Hermes**, an always-on, session-aware
research and execution harness for Indian index F&O. It is a tracking
lock, not a shipped product and not a capability claim.

## Naming (do not collapse)

Two different things already share the word Hermes in this repo:

| Name | What it is | Status |
|---|---|---|
| **Hermes (LLM / ACP)** | Catalogue entry in Settings → AI and the `agent_backends` Hermes ACP session | Existing, unrelated |
| **Hermes (this epic)** | Always-on Indian index F&O harness (`FT-HERMES-001`) | Not shipped |

Settings → AI **Hermes** is a model / agent-backend profile. This epic
does not extend that catalogue entry, does not claim that profile can
trade, and does not rename it.

## Honest framing

- **Always-on process ≠ 24×7 fills.** NSE and BSE have session hours.
  An always-on harness stays session-aware: it may research, watch, and
  refuse outside hours. It does not place fills when the matching
  engine is closed.
- **NIFTY + SENSEX first.** BankNifty and single-stock F&O wait until
  P0–P1 are honest.
- **OpenAlgo Analyzer / Practice first.** Live stays fail-closed until
  a later, evidence-gated phase.
- **Typed gates stay local.** Steal useful *patterns* from Jev (typed
  allow / size / flatten, memoize, causal journal). Do **not** import a
  closed TypeSafe core. Do **not** make Cua the execution core.
- **No chrome.** Do not write "never mistakes", "never forgets", or
  similar infallibility copy in product UI, docs, or PR titles.

Gated execution still applies if any later spike grows an order path:
`SafetySystem` L1–L5 → `gate_order` / `gate_broker_write` →
`BrokerRouter`. This epic does not create a bypass.

## Phases

| Phase | Name | Honest exit (tracking only) |
|---|---|---|
| **P0** | Practice paper | Paper path on OpenAlgo Analyzer / FlintTrade Practice. No Live fills. |
| **P1** | Overnight R9700 eval | Offline evaluation harness on the R9700 target. Report Brier score and ECE. Not a Live promotion. |
| **P2** | Live fail-closed | Live remains refused unless SEBI-derived broker rules and static-IP evidence clear. Default is still fail-closed. |
| **P3** | Memoize + causal journal | Self-hosted decision memoize and a causal journal (jevcache-pattern). No third-party cache SaaS. |

Pass 9 honesty pack ships first. These phases are ordered intent, not
a schedule and not a claim that any phase has started.

## Spikes (priority order — future tracking)

Do **not** implement these in the umbrella PR. Each spike is a later,
separate PR after Pass 9.

1. **Dual session clock + expiry calendar.**
   NIFTY weekly expiry Tuesday; SENSEX weekly expiry Thursday.
   NSE equity F&O continuous runs to 15:40 IST; BSE to 15:30 IST.
   CAS is a **cash** phase, not an index-F&O halt (see FT-CORE-001).
   A dual clock must not treat cash CAS as "index closed".
2. **OpenAlgo Analyzer hard-gate before every order skill.**
   Read Analyzer / sandbox status before any skill that can mint an
   order. Refuse when Analyzer is off or the session is not Practice.
   Live stays out of this spike.
3. **Instrument pack v0.**
   NIFTY + SENSEX masters plus spot, futures, options, OI, PCR, and
   India VIX. No BankNifty or stock F&O in v0.
4. **Laya / stub typed gate adapter.**
   Local typed verbs only: `allow_entry`, `size_bucket`, `flatten`.
   Stub is acceptable while Laya is unspecified. Not a closed TypeSafe
   core and not a Cua execution loop.
5. **Fail ladder + chaos tests.**
   `late → hold → rules → flatten`, with chaos tests that prove the
   ladder, not a demo script.
6. **SEBI retail-algo compliance spike (before Live).**
   Evidence only: broker static-IP allow-list, ≤10 orders per second,
   and April 2026+ broker algo rules that actually bind the operator
   path. This is an evidence gate, not a vendor-SEBI ceremony and not
   a Live switch. See [static-ip-setup.md](../setup/static-ip-setup.md).
7. **Overnight eval harness on R9700.**
   P1 vehicle. Brier and ECE are the honesty metrics. Hardware detail
   stays out of the public tree.
8. **Decision memoize + causal journal.**
   jevcache-pattern, self-hosted only. P3 vehicle. No hosted cache
   product.

## Non-goals

- HFT or co-location claims.
- Overnight Live fills (session closed means no Live matching).
- BankNifty or stock F&O until P0–P1 are honest.
- Cua as the execution core.
- Closed TypeSafe core, or any dependency that pulls one in.
- "Never mistakes / never forgets" product chrome.
- Implementing any spike in this umbrella PR.
- Treating Settings → AI Hermes (LLM / ACP) as this harness.

## How later PRs should attach

- Title prefix `feat(ai):` / `test(ai):` / `docs(ai):` with
  `FT-HERMES-001` and the spike number (for example `spike 2`).
- Keep Live fail-closed until P2 evidence exists.
- Do not open product spikes until Pass 9 is on `main`.
- Maintainer squash-merges this docs lock when review is done.
  Docs-only is squash-ready once CI is green; leave merge to the
  maintainer.

## Related docs

- [User Guide — AI Centre](../USER_GUIDE.md#9-ai-centre-walkthrough)
- [User Guide — Automation Hub](../USER_GUIDE.md#8-automation-hub-walkthrough)
- [Architecture — market session clock (FT-CORE-001)](../ARCHITECTURE.md#market-session-clock-ft-core-001)
- [Static IP setup](../setup/static-ip-setup.md)
- [Order safety](../ORDER_SAFETY.md)
- [PLAN.md](../../PLAN.md) — public phase tracker (Hermes is not a
  PLAN.md phase close; it parks under AI / Practice work)

No order-path bypass. No release. No lockfile churn.
