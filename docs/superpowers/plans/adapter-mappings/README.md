# Broker-specific order mapping plans

These six reviewed proposals are the next mapping-only stage of FT-GTT-001. They are not implemented broker features or evidence of live readiness. Review them before implementation.

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

The first five foundation tasks have been implemented and reviewed locally. After rebasing onto main `e658b50ab6753d63e64df250dfefabb91cc4630d`, 683 focused isolated tests passed, along with scoped lint and whitespace checks. Production code is not pushed or merged by this documentation PR; full suites, declared-toolchain CI and broker/runtime integration remain unverified.
