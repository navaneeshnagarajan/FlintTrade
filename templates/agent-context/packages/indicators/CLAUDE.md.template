# FlintTrade — indicators

> Technical analysis indicators — pure Python/NumPy, TA-Lib optional

## Purpose

Provides all technical indicators used by strategies, backtests, and the terminal
chart widget. Every function is pure Python + NumPy — no C library required.

## Indicators (43 functions across 4 core modules + 4 support modules)

- **Trend (14):** EMA, SMA, DEMA, TEMA, WMA, Hull MA, Supertrend, VWAP, Ichimoku, Parabolic SAR, KAMA, ADX, DMI, Linear Regression
- **Momentum (14):** RSI, MACD, Stochastic, Williams %R, CCI, ROC, CMO, TRIX, StochRSI, BOP, Momentum, Awesome Oscillator, Squeeze Momentum, DPO
- **Volatility (8):** ATR, Bollinger Bands, Keltner Channels, Donchian Channels, NATR, Historical Volatility, Williams VIX Fix, Chaikin Volatility
- **Volume (7):** OBV, AD, CMF, MFI, VWMA, Elder Force Index, Price Volume Trend
- **Signals (7):** Crossover, crossunder, pivot high/low, exrem, flip, valuewhen
- **Streaming:** Incremental indicator updates for real-time data
- **Numba Kernels (3):** JIT-compiled EMA, RSI, ATR hot-path kernels
- **Pipeline:** Indicator chaining and composition
- **Pine Converter:** Pine Script to Python translation

## Rules

- Read root CLAUDE.md for project-wide rules
- Pure Python/NumPy — no TA-Lib dependency required (optional speed boost can be added later)
- All functions take `NDArray[np.float64]`, return `NDArray[np.float64]`
- NaN for insufficient data points — never forward-fill
- Type hints on all function signatures (PEP 604 union style)
- Google-style docstrings
- Import with absolute paths: `from packages.indicators.src.trend import ema`

## Depends on: nothing (stdlib + numpy only)

## Testing

```bash
python -m pytest packages/indicators/tests/ -v --import-mode=importlib
```

## Adding a new indicator

1. Add to the appropriate module (`trend.py`, `momentum.py`, `volatility.py`, `volume.py`)
2. Export from `src/__init__.py`
3. Add at least 3 tests covering: shape, NaN boundary, known numeric result
4. Run ruff: `ruff check packages/indicators/src/`
