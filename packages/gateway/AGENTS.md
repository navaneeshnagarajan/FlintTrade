# FlintTrade — gateway

> Direct broker connections (33 brokers), adapter pattern, encrypted credentials, WebSocket bridge. Read `packages/gateway/CLAUDE.md` first.

## Absorbs
- openalgo broker/* modules → 33 broker adapter implementations (via `_resolve_openalgo_root()` in `adapter.py`)

## Depends on: core

## Path resolution
- OpenAlgo is an external test-dep, not bundled. `adapter.py:_resolve_openalgo_root()` looks for the broker tree at `.local/external/openalgo/` first (the canonical location since commit `3da42e4`, 2026-04-30), with a legacy fallback to `infra/openalgo/` for older checkouts.
- Contributors clone the upstream via `bash scripts/setup-test-deps.sh`.

## Rules
- Read root CLAUDE.md for project-wide rules.
- This package is the ONLY place that imports OpenAlgo's `broker.*` modules. All other FlintTrade code must talk to brokers through the gateway adapter layer.
- Never reference specific brokers in package-level code paths — broker selection happens at runtime via `BrokerRegistry`.
- Credentials are persisted via `CredentialStore` (Fernet-encrypted SQLite). Never log a credential payload, even at DEBUG.
- Tests are in `tests/`. Tests that need a real broker session must `pytest.skip` when `.local/external/openalgo/` is absent.
- Update root CHANGELOG.md for adapter-surface changes (new broker, auth-flow change, contract-normalisation change).
- Branch: main (pre-release, all commits to main).
