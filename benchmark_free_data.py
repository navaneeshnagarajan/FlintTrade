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

def generate_df(n=100_000):
    return pd.DataFrame({
        "datetime": pd.date_range("2020-01-01", periods=n, freq="min").astype(str),
        "open": np.random.rand(n),
        "high": np.random.rand(n),
        "low": np.random.rand(n),
        "close": np.random.rand(n),
        "volume": np.random.randint(0, 1000, n),
        "oi": np.random.randint(0, 1000, n),
    })

df = generate_df(50_000)

def iterrows_method(df):
    bars = []
    for _, row in df.iterrows():
        bar = FreeBar(
            timestamp=str(row.get("datetime", row.name if hasattr(row, "name") else "")),
            open=float(row.get("open", 0)),
            high=float(row.get("high", 0)),
            low=float(row.get("low", 0)),
            close=float(row.get("close", 0)),
            volume=int(row.get("volume", 0)),
            oi=int(row.get("oi", 0)) if "oi" in row.index else 0,
            source="openchart",
        )
        bars.append(bar)
    return bars

def optimized_method(df):
    if "datetime" in df.columns:
        ts = df["datetime"].astype(str).tolist()
    else:
        ts = df.index.astype(str).tolist()

    opens = df["open"].astype(float).tolist() if "open" in df.columns else [0.0]*len(df)
    highs = df["high"].astype(float).tolist() if "high" in df.columns else [0.0]*len(df)
    lows = df["low"].astype(float).tolist() if "low" in df.columns else [0.0]*len(df)
    closes = df["close"].astype(float).tolist() if "close" in df.columns else [0.0]*len(df)
    volumes = df["volume"].astype(int).tolist() if "volume" in df.columns else [0]*len(df)
    ois = df["oi"].astype(int).tolist() if "oi" in df.columns else [0]*len(df)

    source = "openchart"

    return [
        FreeBar(t, o, h, l, c, v, oi, source)
        for t, o, h, l, c, v, oi in zip(ts, opens, highs, lows, closes, volumes, ois)
    ]

def itertuples_method(df):
    bars = []

    has_datetime = "datetime" in df.columns
    has_open = "open" in df.columns
    has_high = "high" in df.columns
    has_low = "low" in df.columns
    has_close = "close" in df.columns
    has_volume = "volume" in df.columns
    has_oi = "oi" in df.columns

    for row in df.itertuples():
        bar = FreeBar(
            timestamp=str(row.datetime if has_datetime else getattr(row, "Index", "")),
            open=float(row.open) if has_open else 0.0,
            high=float(row.high) if has_high else 0.0,
            low=float(row.low) if has_low else 0.0,
            close=float(row.close) if has_close else 0.0,
            volume=int(row.volume) if has_volume else 0,
            oi=int(row.oi) if has_oi else 0,
            source="openchart",
        )
        bars.append(bar)
    return bars

# Warmup
iterrows_method(df[:10])
optimized_method(df[:10])
itertuples_method(df[:10])

t0 = time.perf_counter()
res1 = iterrows_method(df)
t1 = time.perf_counter()
print(f"iterrows: {t1-t0:.4f}s")

t0 = time.perf_counter()
res2 = optimized_method(df)
t1 = time.perf_counter()
print(f"optimized (zip/tolist): {t1-t0:.4f}s")

t0 = time.perf_counter()
res3 = itertuples_method(df)
t1 = time.perf_counter()
print(f"itertuples: {t1-t0:.4f}s")

# Ensure equal length and roughly equal data to prove correctness
print("Correctness check zip/tolist:", len(res1) == len(res2))
print("Correctness check itertuples:", len(res1) == len(res3))
if len(res1) > 0:
    print(res1[0] == res2[0])
    print(res1[0] == res3[0])
