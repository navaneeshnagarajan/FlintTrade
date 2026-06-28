# Webhooks

> TradingView webhooks, ChartInk integration, custom webhooks, flow builder, alerter, n8n bridge, and WhatsApp bridge.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source financial-market software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Python

## Public surface

- `src/flinttrade_webhooks/webhook_receiver.py — HMAC-validated webhook intake`
- `src/flinttrade_webhooks/tradingview.py — TradingView alert ingestion`
- `src/flinttrade_webhooks/chartink.py — ChartInk scanner integration`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/integrations/webhooks
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
python -m pytest packages/integrations/webhooks/tests/ -v --import-mode=importlib
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
