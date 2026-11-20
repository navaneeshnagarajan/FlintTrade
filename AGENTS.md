# FlintTrade contributor guide

FlintTrade `v0.0.1` is self-hosted trading software for Indian markets. It runs a native backend and a browser terminal, with an optional Electron desktop shell around the same backend.

The public roadmap is [ROADMAP.md](ROADMAP.md). Architecture is [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Contributor setup is [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md). Continuous integration is [docs/CI.md](docs/CI.md). Domain terms are [docs/GLOSSARY.md](docs/GLOSSARY.md).

## Commands

Python dependencies use `uv`. JavaScript uses `pnpm`. The cross-platform runner is `python scripts/ft.py`.

- `python scripts/ft.py test` runs pytest.
- `python scripts/ft.py lint` runs Ruff.
- `python scripts/ft.py check` runs affected checks. `python scripts/ft.py check --full` runs the exhaustive local gate.
- From `packages/apps/terminal`, `npx vitest run` runs the terminal tests and `npm run typecheck` runs the TypeScript check.

Put one command per line. Do not chain commands with `&&` in contributor instructions.

## Safety

Every order path mints a safety context through `gate_order` or `gate_broker_write`, then `BrokerRouter`. Do not add a path that reaches a broker adapter without that gate. `packages/integrations/gateway/tests/test_no_legacy_order_path.py` guards this.

A broker session cannot be started from the terminal today. Practice mode and example data work without a broker. Broker writes return 503 and broker reads return 409. Live order placement stays disabled unless it is explicitly unlocked and every safety layer passes.

Frontend live-order entry points stay closed until the native write target is ready. Broker selectors use composite `source:broker:account_id` keys.

Count pins: `BROKER_CATALOG` (6 brokers), 71 widgets, and 18 packages.

## Verification

When a change is visible in the running terminal or site, verify that flow with Reticle before calling it done. The procedure is [RETICLE.md](RETICLE.md) and [.cursor/commands/reticle.md](.cursor/commands/reticle.md). Report an unknown verdict as unknown.

## Issues and shipping

Report bugs and feature requests through GitHub Issues on `navaneeshnagarajan/FlintTrade`. Triage labels are listed in [contributing.md](contributing.md).

Shipped behaviour belongs in `changelog.md`. The public roadmap is `ROADMAP.md`.
