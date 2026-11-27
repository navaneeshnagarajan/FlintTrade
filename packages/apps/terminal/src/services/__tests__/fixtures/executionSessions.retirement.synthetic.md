# Synthetic blocked-grant retirement responses

`executionSessions.retirement.synthetic.json` contains unmodified public HTTP response objects from two fresh disposable synthetic runs. It is not operator evidence, broker qualification, production readiness or a live-execution grant. The three earlier synthetic JSON fixtures and their provenance remain historical and unchanged.

Each scenario uses the real execution-session HTTP routes and native registry with an inert broker and synthetic independent qualification evidence. No command is submitted. After a real grant is issued, `kill` activates the canonical kill latch; `stale` expires the synthetic provider's qualification evidence. Both exact reads report false effective entry authority and false readiness while retaining a non-revoked grant. The exact canonical Stop POST retires the grant and clears qualification; `stopAck` and the subsequent exact `stopped` GET are retained without alteration. No broker writes occur. Foreign-operator, wrong-account, wrong-generation and stale-generation replay requests are refused.

`qualifiedWithoutGrant` is a separate real public GET from a fresh qualified run in which no grant was issued; it makes no broker writes and supplies the distinct no-grant refusal control.

The fixture does not demonstrate that clearing a gate permits an order, does not treat Stop as liquidation and does not establish broker flatness.

Source SHA-256 identities:

- `packages/core/core/src/flinttrade_core/native_autonomy.py`: `974de9625a55f291b85114802d8eaaf14918b9f1038e9fd2684e8ecaa2137a60`
- `packages/core/core/src/flinttrade_core/execution_sessions.py`: `dcebc5f8cd245a88fd37214c783395a54156449dd310aaefdc447711f47e238f`
- `packages/core/core/src/flinttrade_core/execution_sessions_routes.py`: `b4b5e86a32328eb6afd53241453a0449f022df1c9d861c875f1c3fd78c7f43ec`
- `packages/core/core/tests/test_native_autonomy.py`: `702fa8e53670cb8829a7acb38e7915ae49de7dd387a9dcddd77cd7eece6e48ed`
- Fixture JSON: `464a2ff56601a2beea45ea4090f31317c1c3c8b245bb37b1b383b06c91a813f4`

The capture ran on Python 3.13.15 with fresh filesystem/HOME/network/PID state, hidden host state, cleared environment, zero capabilities, NoNewPrivs and denied network/process sentinels before imports. This is conditional public-route diagnostic evidence, not normal-factory/listener, cross-platform or funded-broker acceptance.
