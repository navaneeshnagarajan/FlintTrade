# Engine

> Five-layer safety system, order router, scheduler, base strategy class, AST-guarded sandbox executor, bracket-order engine, mode guard, and reconciliation.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source financial-market software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Python

## Public surface

- `src/flinttrade_engine/safety.py — kill switches across 5 layers`
- `src/flinttrade_engine/router.py — broker-agnostic order routing`
- `src/flinttrade_engine/strategy.py — base class for live strategies`
- `src/flinttrade_engine/sandbox_executor.py — user-strategy execution with AST guard`
- `src/flinttrade_engine/mode_guard.py — server-side Explore / Practice / Live enforcement`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/services/engine
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
python -m pytest packages/services/engine/tests/ -v --import-mode=importlib
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
