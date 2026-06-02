# Data

> Tick recorder, append-only audit logger, trade logger, SQLite sandbox state, DuckDB analytics storage, QuestDB writer, and Excel bridge.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** Python

## Public surface

- `src/tick_recorder.py — real-time tick capture to DuckDB / QuestDB`
- `src/sandbox_engine.py — practice-mode paper trading backed by SQLite state.sqlite`
- `src/audit_logger.py — append-only local audit trail (operator-controlled retention)`
- `src/questdb_writer.py — ILP-based ingestion`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
# Python packages
uv pip install -e packages/core/data
```

If you only want to use the package in isolation, the project's `pyproject.toml` (or `Cargo.toml` / `package.json`) lists its dependencies.

## Tests

```bash
python -m pytest packages/core/data/tests/ -v
```

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md). For end-user features it powers, see [docs/USER_GUIDE.md](../../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`contributing.md`](../../../contributing.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../../LICENSE) for the full text.
