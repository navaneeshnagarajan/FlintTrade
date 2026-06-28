# Gateway

> FlintTrade's own native broker gateway — the BrokerAdapter Protocol, safety-gated BrokerRouter, per-broker adapters for 32 brokers, an encrypted credential vault, and the WebSocket bridge. OpenAlgo is one optional bridge adapter, not the primary path.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source financial-market software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Python

## Public surface

- `src/flinttrade_gateway/adapter.py — BrokerAdapter Protocol + BROKER_CATALOG`
- `src/flinttrade_gateway/router.py — BrokerRouter: dispatches broker writes only after SafetyContext verification`
- `src/flinttrade_gateway/registry.py — BrokerRegistry over the 32-broker catalogue`
- `src/flinttrade_gateway/brokers/ — native per-broker adapters (Dhan, OpenAlgo bridge, …) against the BrokerAdapter ABC`
- `src/flinttrade_gateway/credentials.py — Fernet-encrypted credential vault`
- `src/flinttrade_gateway/ws_bridge.py — broker WebSocket fan-in to FlintTrade clients`

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

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in
[docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see
[docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.
