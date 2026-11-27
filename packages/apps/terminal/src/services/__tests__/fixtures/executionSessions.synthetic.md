# Synthetic v1 execution-session responses

The adjacent `executionSessions*.synthetic.json` files contain actual JSON responses from the Core execution-session HTTP handlers through Flask's in-process test client. They are **synthetic transport fixtures, not broker, production-qualification, or release evidence**. No listener, real broker, provider or model job was started.

The existing inert NativeAutonomy fixture provided signed synthetic operator sessions, a real safety/gate/router/lifecycle stack, synthetic independent attestation, and external broker I/O doubles. Paper creation used the real sandbox ledger without starting its worker. The public TypeScript tests replace only `fetch`; they exercise the exported execution-session client and mounted `ForwardTestSection`/`ExecutionSessionsPanel` with the real stores and query lifecycle.

Captured source identity (v1 remediation snapshot, before the subsequent R1 finalisation repair):

| Source | SHA-256 |
| --- | --- |
| `packages/core/core/src/flinttrade_core/native_autonomy.py` | `344eccd4a6b45ef3a469e44333ce6bb40f6fdf198fa17065ac31703d90d13359` |
| `packages/core/core/src/flinttrade_core/execution_sessions.py` | `dcebc5f8cd245a88fd37214c783395a54156449dd310aaefdc447711f47e238f` |
| `packages/core/core/src/flinttrade_core/execution_sessions_routes.py` | `b4b5e86a32328eb6afd53241453a0449f022df1c9d861c875f1c3fd78c7f43ec` |
| `packages/core/core/src/flinttrade_core/order_routes.py` | `302fd44e6aca35ae3e7cd2edfce30bc1989319d97f7b86a163499531291b0fdc` |
| `packages/core/core/tests/test_native_autonomy.py` | `702fa8e53670cb8829a7acb38e7915ae49de7dd387a9dcddd77cd7eece6e48ed` |

Correspondence includes Paper, legacy Live without projection, configured native, granted/readable native, ACK, partial fills, canonical Stop ACK and readback, cancellation request, kill-blocked effective authority, repeated qualification, uncertain dispatch, stale qualification and restart reconciliation. The captured operator hash is a synthetic identity. No token or credential is included.

Single-field negative fixtures in the tests intentionally alter these captured observations; they are not purported Core outputs. Historical expiry values and runtime fingerprints are retained unchanged. The UI labels effective authority/readiness as the last Core observation, not a fresh client-issued permission. Grant revocation, requested actions, qualification, admission blockers, receipt state and known fills remain distinct. The decoder rejects incomplete/contradictory entire censuses rather than filtering rows, and cannot promote terminal receipts with known fills to ready.

This is a manually maintained strict v1 read contract. It is not the proposed v2 model/code-generation system. A producer change requires a new source-bound serializer correspondence check; these historical fixtures alone do not certify a later Core revision.
