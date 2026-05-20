# Desktop

> Tauri-based native desktop wrapper around the terminal package (scaffolded).

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** TypeScript + Rust

## Public surface

- `src-tauri/Cargo.toml — Tauri shell configuration`
- `src-tauri/tauri.conf.json — window + permissions`
- `src/ — TypeScript renderer entry`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
# Python packages
uv pip install -e packages/desktop
```

If you only want to use the package in isolation, the project's `pyproject.toml` (or `Cargo.toml` / `package.json`) lists its dependencies.

## Tests

```bash
cd packages/desktop && npm test  # plus `cargo test` in src-tauri/
```

For the full test matrix, see the contributor guide at [docs/DEVELOPER_GUIDE.md](../../docs/DEVELOPER_GUIDE.md).

## How this fits in

This package's role in the wider FlintTrade architecture is documented in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md). For end-user features it powers, see [docs/USER_GUIDE.md](../../docs/USER_GUIDE.md).

## Contributing

Contributions welcome. Please read [`CONTRIBUTING.md`](../../CONTRIBUTING.md) at the repo root before opening a pull request.

## License

AGPL-3.0 — same as the parent repository. See [`LICENSE`](../../LICENSE) for the full text.
