//! Error types for tick-engine.

use thiserror::Error;

/// All errors that can be produced by the tick-engine.
#[derive(Debug, Error)]
pub enum EngineError {
    #[error("input length mismatch: expected {expected}, got {got}")]
    LengthMismatch { expected: usize, got: usize },

    #[error("empty input: {context}")]
    EmptyInput { context: &'static str },

    #[error("invalid parameter: {message}")]
    InvalidParameter { message: String },

    /// Invalid configuration or aligned input for a spread simulation.
    #[error("{message}")]
    InvalidSpreadInput { message: String },

    #[error("insufficient data: need at least {required} bars, got {got}")]
    InsufficientData { required: usize, got: usize },

    #[error("Cholesky decomposition failed: matrix is not positive semi-definite")]
    CholeskyFailed,

    #[error("Monte Carlo simulation failed: {reason}")]
    SimulationError { reason: String },
}

impl From<EngineError> for pyo3::PyErr {
    fn from(e: EngineError) -> pyo3::PyErr {
        pyo3::exceptions::PyValueError::new_err(e.to_string())
    }
}
