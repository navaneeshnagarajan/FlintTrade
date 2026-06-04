# Screener

> Option chain, OI analysis, PCR, max-pain, futures quadrant, portfolio Greeks, IV smile, fundamental screener, FII / DII tracker, and RRG calculator.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source modular trading platform for Indian F&O, commodities, and crypto.

**Language:** Python

## Public surface

- `src/flinttrade_screener/option_chain.py — strike-by-strike chain with Greeks`
- `src/flinttrade_screener/oi_analysis.py — OI analysis, PCR, and max-pain`
- `src/flinttrade_screener/rrg.py — Relative Rotation Graph`
- `src/flinttrade_screener/fundamental_screener.py — Screener.in-style fundamentals`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/services/screener
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
python -m pytest packages/services/screener/tests/ -v --import-mode=importlib
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
