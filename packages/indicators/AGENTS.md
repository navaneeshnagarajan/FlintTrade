# indicators — Agent Instructions

Read CLAUDE.md first. This package provides technical analysis indicators.

## What this package does

Pure Python/NumPy indicator library. All functions are stateless transforms:
input arrays in, output arrays out. No side effects, no I/O, no external calls.

## Key design decisions

- NaN (not zero, not forward-fill) for warmup bars where insufficient data exists
- Wilder smoothing (RMA) for RSI and ATR — matches TradingView behavior
- DEMA: 2*EMA1 - EMA2 computed over the valid subset of EMA1
- Supertrend: band carryover logic matches standard TV implementation
- VWAP: cumulative from bar 0 — caller resets by slicing to session start

## Do not

- Add TA-Lib as a hard dependency (wrap in try/except if adding optional path)
- Use forward-fill or zero-fill for NaN
- Import from packages other than `packages.indicators.src.utils`
- Add state to indicator functions (all must be pure functions)
