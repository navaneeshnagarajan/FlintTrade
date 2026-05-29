# Engine

> Five-layer safety system, order router, scheduler, base strategy class, AST-guarded sandbox executor, bracket-order engine, mode guard, and reconciliation.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** Python

## Public surface

- `src/safety.py — kill switches across 5 layers`
- `src/router.py — broker-agnostic order routing`
- `src/strategy.py — base class for live strategies`
- `src/sandbox_executor.py — user-strategy execution with AST guard`
- `src/mode_guard.py — server-side Explore / Practice / Live enforcement`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
# Python packages
uv pip install -e packages/services/engine
```

If you only want to use the package in isolation, the project's `pyproject.toml` (or `Cargo.toml` / `package.json`) lists its dependencies.

## Tests

```bash
python -m pytest packages/services/engine/tests/ -v
```

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see [docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.
