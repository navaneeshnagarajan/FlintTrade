# Ditto

> Multi-account orchestration: position mirror, margin calculator, trailing stop-loss, and risk manager (AlgoMirror patterns absorbed in-process).

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** Python

## Public surface

- `src/flinttrade_ditto/mirror.py — copy trades across accounts with size scaling`
- `src/flinttrade_ditto/margin_calculator.py — pre-trade margin checks`
- `src/flinttrade_ditto/trailing_sl.py — dynamic trailing stop-loss`
- `src/flinttrade_ditto/risk_manager.py — per-account exposure + drawdown limits`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/services/ditto
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
python -m pytest packages/services/ditto/tests/ -v --import-mode=importlib
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
