# FlintTrade Indicators

Technical analysis indicator library. Pure Python + NumPy implementation.
No TA-Lib or other C library required.

## Indicators

| Category | Indicators |
|----------|-----------|
| Trend | EMA, SMA, DEMA, Supertrend, VWAP |
| Momentum | RSI, MACD, Stochastic, Williams %R |
| Volatility | ATR, Bollinger Bands, Keltner Channels |

## Usage

```python
import numpy as np
from packages.indicators.src.trend import ema, supertrend, dema, vwap, sma
from packages.indicators.src.momentum import rsi, macd, stochastic, williams_r
from packages.indicators.src.volatility import atr, bollinger_bands, keltner_channels

close = np.array([...], dtype=np.float64)
high  = np.array([...], dtype=np.float64)
low   = np.array([...], dtype=np.float64)
volume = np.array([...], dtype=np.float64)

# Trend
ema20 = ema(close, period=20)
st, direction = supertrend(high, low, close, period=10, multiplier=3.0)
dema15 = dema(close, period=15)

# Momentum
rsi14 = rsi(close, period=14)
macd_line, signal_line, histogram = macd(close, fast=12, slow=26, signal=9)

# Volatility
atr14 = atr(high, low, close, period=14)
upper, middle, lower = bollinger_bands(close, period=20, std_dev=2.0)
```

## Design rules

- All inputs: `NDArray[np.float64]`
- All outputs: `NDArray[np.float64]` (or tuples thereof)
- NaN is returned for bars with insufficient history — never forward-filled
- Wilder smoothing (RMA) used for RSI and ATR — matches TradingView
