# Broker-specific order mapping plans

These six plans describe the mapping-only stage of FT-GTT-001. Draft PR #308 now publishes foundation code and six standalone pure companions. They are not operational broker features or evidence of live readiness; repairs to the legacy interfaces named in several plans remain separate unfinished work.

| Broker | Plan focus |
|---|---|
| [Dhan](2026-10-06-dhan-order-mappings.md) | Forever creation/modification distinctions, resource readback, Super trailing edits and remaining quantities |
| [Upstox](2026-10-06-upstox-order-mappings.md) | Market protection, GTT rule states, batch outcomes and correct cancellation selectors |
| [Kotak Neo](2026-10-06-kotak-order-mappings.md) | Current v3 contracts, exact identity/quantity/status evidence and explicit SDK parity gaps |
| [INDstocks](2026-10-06-indstocks-order-mappings.md) | Native field names, trigger exclusions, mirrored protection legs and market-to-limit semantics |
| [Groww](2026-10-06-groww-order-mappings.md) | Resource-specific GTT/OCO create/read/modify/cancel mapping |
| [Delta](2026-10-06-delta-order-mappings.md) | Native conditional options, reduce-only, quantity precision and distinct bracket contracts |

All plans require the [offline verification prerequisite](offline-mapping-verification.md). That reusable runner specification is not itself an implemented runner. Standard integration suites remain unverified.

Native broker features are preserved as requirements. Runtime adapter wiring, durable recovery, authoritative readback and actual broker verification remain separate prerequisites. Mapping tests alone do not establish readiness or authorise order execution.

## Current foundation checkpoint

The first five foundation tasks and six standalone companions were published for inspection at `4239f32a`, based on main `e658b50ab6753d63e64df250dfefabb91cc4630d`. The earlier 683-test foundation run remains historical scoped evidence, not full-runtime acceptance. Full suites, declared-toolchain CI, rendered UI and broker/runtime integration remain unverified.

## Research and local verification checkpoint: 2026-10-07

- **Kotak:** retain companion MTF parameters supported by [pinned placement documentation](https://github.com/Kotak-Neo/kotak-neo-python/blob/9a37488d77dc96442ee2a90ef78462e688cf4856/docs/functions/orders/place_order.md); the legacy mapper's MTF gap remains. Reject contradictory order fill quantities without applying order-total checks to independently documented trade rows.
- **Groww:** preserve the [GTT-specific](https://groww.in/trade-api/docs/python-sdk/smart-orders) CASH/CNC and FNO/NRML request pairs. Reject other pairs as unverified; preserve historical reads and independent OCO semantics.
- **Upstox:** preserve explicit modification-rule protection represented by the [pinned SDK rule model](https://github.com/upstox/upstox-python/blob/d88a12ef5738a4c8d71f3b88eb7b79a359277c9d/upstox_client/models/gtt_rule.py). The HTTP modification table omits it, so server acceptance and effectiveness remain unverified.
- **Dhan:** the published REST companion does not complete the named legacy Forever, Super or quantity repairs. Those tasks remain unfinished.

The latest local run passed 3,173 product test items across nine independent Python files, plus four separate Kotak subtests and three separate isolation sentinels. This used the maintainer-approved existing Python 3.13 environment, startup-free source loading, a hash-bound import allow-list and OS-enforced network isolation. Python 3.12 remains unverified. No repository initialisers/conftests, SDKs or runtime/account paths were executed. Scoped Ruff and whitespace checks passed.

This checkpoint authorises no push, merge, release, runtime wiring or broker activity. Normal repository suites, the order-path guard, durable recovery, authoritative book coherence and end-to-end acceptance remain outstanding.
