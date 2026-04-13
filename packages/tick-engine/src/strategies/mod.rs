//! Strategy implementations for tick-engine.
//!
//! Each module exposes a strategy struct that implements `Strategy` and can
//! be run bar-by-bar via `on_tick`.  All strategies return `Vec<Signal>` so
//! that multi-leg strategies (options, spreads) can emit multiple signals at
//! once.

pub mod options;
pub mod pairs;
pub mod spreads;
