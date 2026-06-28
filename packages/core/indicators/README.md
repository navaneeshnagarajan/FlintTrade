# Indicators

> 43 indicator functions across 7 modules — TA-Lib batch indicators, Numba-accelerated streaming variants, and Pine Script conversion.

**Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade)** — the open-source financial-market software monorepo built with Python, React, TypeScript, and Rust.

**Language:** Python + Numba

## Public surface

- `src/flinttrade_indicators/trend.py — SMA, EMA, MACD, ADX`
- `src/flinttrade_indicators/momentum.py — RSI, Stochastic, ROC, MFI`
- `src/flinttrade_indicators/oscillators.py — CCI, Williams %R, TRIX`
- `src/flinttrade_indicators/volatility.py — ATR, Bollinger Bands, Keltner Channels`
- `src/flinttrade_indicators/volume.py — OBV, Chaikin, VWAP`

(See the source for the full surface.)

## Install

This package is part of the FlintTrade monorepo. Install via the workspace from the repo root:

```bash
uv pip install -e packages/core/indicators
```

If you only want to use the package in isolation, the package's `pyproject.toml`,
`Cargo.toml`, or `package.json` lists its dependencies. The supported path is the
root workspace.

## Tests

```bash
python -m pytest packages/core/indicators/tests/ -v --import-mode=importlib
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
