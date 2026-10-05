# Historical

> Synchronous OHLCV helpers, local DuckDB storage and independent OpenChart/yfinance downloads. Native broker history remains unavailable under the read freeze.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source self-hosted trading software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Python

## Public surface

- `src/flinttrade_historical/downloader.py — synchronous date chunking; default native broker history unavailable`
- `src/flinttrade_historical/free_data.py — independent OpenChart + yfinance free-data downloads`
- `src/flinttrade_historical/pipeline.py — local DuckDB storage for supplied and free-data bars`
- `src/flinttrade_historical/expiry_tracker.py — monthly + weekly expiry calendar for NSE F&O / MCX`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/core/historical
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
python -m pytest packages/core/historical/tests/ -v --import-mode=importlib
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
