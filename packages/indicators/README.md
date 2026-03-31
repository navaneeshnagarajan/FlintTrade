# flint-indicators
Technical analysis indicator library — pure NumPy implementation for batch use.
Part of [FlintTrade](https://github.com/navaneeshnagarajan/FlintTrade). See CLAUDE.md for dev context.

## Indicators (43 functions across 7 modules)

| Category | Indicators |
|----------|-----------|
| Trend | EMA, SMA, DEMA, TEMA, WMA, Hull MA, Supertrend, VWAP, Ichimoku, Parabolic SAR |
| Momentum | RSI, MACD, Stochastic, Williams %R, CCI, ROC, CMO, TRIX, StochRSI, BOP |
| Volatility | ATR, Bollinger Bands, Keltner Channels, Donchian Channels, NATR, Historical Volatility |
| Volume | OBV, AD, CMF, MFI, VWMA |

## Usage

```python
import numpy as np
from packages.indicators.src.trend import ema, sma, dema, tema, wma, hull, supertrend, vwap, ichimoku, parabolic_sar
from packages.indicators.src.momentum import rsi, macd, stochastic, williams_r, cci, roc, cmo, trix, stoch_rsi, bop
from packages.indicators.src.volatility import atr, bollinger_bands, keltner_channels, donchian_channels, natr, historical_volatility
from packages.indicators.src.volume import obv, ad, cmf, mfi, vwma

close  = np.array([...], dtype=np.float64)
high   = np.array([...], dtype=np.float64)
low    = np.array([...], dtype=np.float64)
volume = np.array([...], dtype=np.float64)

# Trend
ema20 = ema(close, period=20)
st, direction = supertrend(high, low, close, period=10, multiplier=3.0)
tenkan, kijun, span_a, span_b, chikou = ichimoku(high, low, close)
sar, uptrend = parabolic_sar(high, low)

# Momentum
rsi14 = rsi(close, period=14)
macd_line, signal_line, histogram = macd(close, fast=12, slow=26, signal=9)
k, d = stoch_rsi(close)

# Volatility
atr14 = atr(high, low, close, period=14)
upper, middle, lower = bollinger_bands(close, period=20, std_dev=2.0)
dc_upper, dc_mid, dc_lower = donchian_channels(high, low, period=20)

# Volume
obv_vals = obv(close, volume)
mfi14 = mfi(high, low, close, volume, period=14)
```

## Additional Modules

- `signals.py` — Signal generation from indicator crossovers and thresholds
- `streaming.py` — Streaming (incremental) indicator updates for real-time data
- `numba_kernels.py` — Numba JIT-compiled kernels for hot-path indicators
- `pipeline.py` — Indicator pipeline chaining and composition
- `utils.py` — Shared utility functions

## Design rules

- All inputs: `NDArray[np.float64]`
- All outputs: `NDArray[np.float64]` (or tuples thereof)
- NaN is returned for bars with insufficient history — never forward-filled
- Wilder smoothing (RMA) used for RSI and ATR — matches TradingView
