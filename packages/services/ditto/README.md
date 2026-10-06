# Ditto

> Native account metadata, analytics and position/stop monitors (AlgoMirror patterns absorbed in-process). Broker execution remains unavailable under the native runtime freeze.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Python

## Public surface

- `src/flinttrade_ditto/account_manager.py — non-secret native account metadata; sessions remain gateway-owned`
- `src/flinttrade_ditto/mirror.py — allocation and position-monitor primitives; native copy execution unavailable`
- `src/flinttrade_ditto/margin_calculator.py — margin calculations and estimates`
- `src/flinttrade_ditto/trailing_sl.py — trailing-stop calculations and monitor state`
- `src/flinttrade_ditto/risk_manager.py — exposure and drawdown checks`

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
