# Tick Engine

> High-performance tick-processing engine — Rust core with Python bindings.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** Rust + PyO3

## Public surface

- `src/lib.rs — PyO3 module entry`
- `src/types.rs — core Tick / Signal / BacktestResult types`
- `Cargo.toml — crate metadata and dependencies`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/core/ticks
cd packages/core/ticks && cargo test
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
cd packages/core/ticks && cargo test
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
