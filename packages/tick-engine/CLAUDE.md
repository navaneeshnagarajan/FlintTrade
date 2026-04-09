# FlintTrade — tick-engine

> High-performance tick processing engine — Rust core with Python bindings via PyO3

## Architecture
- `src/lib.rs` — Rust core (tick simulation, EMA crossover, performance metrics)
- `python/tick_engine/` — Python bindings via PyO3
- Metrics: Sharpe ratio, max drawdown, total return

## Key Classes
- `TickSimulator` — Event-driven tick-level backtesting
- `EMA crossover` — Example strategy implementation in Rust

## Build
```bash
maturin develop          # build and install locally
maturin build --release  # release build
```

## Testing
```bash
python -m pytest packages/tick-engine/tests/ -v --import-mode=importlib
```
2 test files, ~73 tests.

## Depends on: none (standalone Rust/PyO3 package)

## Rules
- Read root CLAUDE.md for project-wide rules
- Tests are in the `tests/` directory. Add new test files as needed.
- Update root CHANGELOG.md
- Branch: main (pre-release, all commits to main)
