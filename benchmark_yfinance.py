import time
import pandas as pd
import numpy as np
from dataclasses import dataclass, field

@dataclass
class FreeBar:
    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    oi: int = 0
    source: str = ""

def generate_df(n=50_000):
    return pd.DataFrame({
        "Open": np.random.rand(n),
        "High": np.random.rand(n),
        "Low": np.random.rand(n),
        "Close": np.random.rand(n),
        "Volume": np.random.randint(0, 1000, n),
    }, index=pd.date_range("2020-01-01", periods=n, freq="min"))

df = generate_df(50_000)
inr_rate = 83.0

def iterrows_method(data):
    bars = []
    for idx, row in data.iterrows():
        bar = FreeBar(
            timestamp=str(idx),
            open=float(row["Open"]) * inr_rate,
            high=float(row["High"]) * inr_rate,
            low=float(row["Low"]) * inr_rate,
            close=float(row["Close"]) * inr_rate,
            volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
            source="yfinance",
        )
        bars.append(bar)
    return bars

def optimized_method(data):
    ts = data.index.astype(str).tolist()

    opens = (data["Open"] * inr_rate).astype(float).tolist()
    highs = (data["High"] * inr_rate).astype(float).tolist()
    lows = (data["Low"] * inr_rate).astype(float).tolist()
    closes = (data["Close"] * inr_rate).astype(float).tolist()

    # Handle NaNs in volume
    if "Volume" in data.columns:
        volumes = data["Volume"].fillna(0).astype(int).tolist()
    else:
        volumes = [0] * len(data)

    source = "yfinance"

    return [
        FreeBar(t, o, h, l, c, v, 0, source)
        for t, o, h, l, c, v in zip(ts, opens, highs, lows, closes, volumes)
    ]

# Warmup
iterrows_method(df[:10])
optimized_method(df[:10])

t0 = time.perf_counter()
res1 = iterrows_method(df)
t1 = time.perf_counter()
print(f"iterrows: {t1-t0:.4f}s")

t0 = time.perf_counter()
res2 = optimized_method(df)
t1 = time.perf_counter()
print(f"optimized (zip/tolist): {t1-t0:.4f}s")

# Ensure equal length and roughly equal data to prove correctness
print("Correctness check zip/tolist:", len(res1) == len(res2))
if len(res1) > 0:
    print(res1[0] == res2[0])
