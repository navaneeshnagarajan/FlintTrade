# Gateway

> Native gateway with five broker adapters, a safety-gated router, encrypted credentials and local tick dispatch. Native broker HTTP and network capture remain unavailable.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Python

## Public surface

- `src/flinttrade_gateway/adapter.py — BrokerAdapter Protocol + BROKER_CATALOG`
- `src/flinttrade_gateway/router.py — BrokerRouter: dispatches broker writes only after SafetyContext verification`
- `src/flinttrade_gateway/registry.py — native account and session registry over the 5-broker catalogue`
- `src/flinttrade_gateway/brokers/ — native per-broker adapters (Dhan, Upstox, Kotak Neo, INDmoney, Groww) against the BrokerAdapter ABC`
- `src/flinttrade_gateway/credentials.py — Fernet-encrypted credential vault`
- `src/flinttrade_gateway/ws_bridge.py — local TickDispatcher queues and latest-tick cache; no network server`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/integrations/gateway
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
python -m pytest packages/integrations/gateway/tests/ -v --import-mode=importlib
```

Run one command per line. They work unchanged in bash, zsh and Windows
PowerShell — do not join them with `&&`, which Windows PowerShell 5.1 does not
support.

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in
[docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see
[docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.
