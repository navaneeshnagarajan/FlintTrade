//! Monte Carlo simulation via Geometric Brownian Motion (GBM).
//!
//! Provides both single-asset and correlated multi-asset path simulation.
//! Uses a Cholesky decomposition for correlations so that individual asset
//! paths retain their correct covariance structure.
//!
//! # Example
//! ```
//! use tick_engine::monte_carlo::{simulate, confidence_intervals};
//! use std::collections::HashMap;
//!
//! let daily_returns = vec![0.001, -0.002, 0.003, 0.0015, -0.001];
//! let paths = simulate(&daily_returns, 1000, 252).unwrap();
//! assert_eq!(paths.len(), 1000);
//! assert_eq!(paths[0].len(), 252);
//!
//! let ci = confidence_intervals(&paths, &[0.05, 0.50, 0.95]);
//! assert!(ci.contains_key("p5"));
//! assert!(ci.contains_key("p50"));
//! assert!(ci.contains_key("p95"));
//! ```

use std::collections::HashMap;

use crate::errors::EngineError;

// ---------------------------------------------------------------------------
// Internal PRNG — xoshiro256** (no external deps)
// ---------------------------------------------------------------------------

/// A fast, seedable pseudo-random number generator (xoshiro256**).
struct Xoshiro256 {
    s: [u64; 4],
}

impl Xoshiro256 {
    fn new(seed: u64) -> Self {
        // SplitMix64 seed expansion
        let mut sm = seed;
        let s0 = splitmix64(&mut sm);
        let s1 = splitmix64(&mut sm);
        let s2 = splitmix64(&mut sm);
        let s3 = splitmix64(&mut sm);
        Self {
            s: [s0, s1, s2, s3],
        }
    }

    /// Next u64 from the generator.
    #[inline]
    fn next_u64(&mut self) -> u64 {
        let result = self.s[1].wrapping_mul(5).rotate_left(7).wrapping_mul(9);
        let t = self.s[1] << 17;
        self.s[2] ^= self.s[0];
        self.s[3] ^= self.s[1];
        self.s[1] ^= self.s[2];
        self.s[0] ^= self.s[3];
        self.s[2] ^= t;
        self.s[3] = self.s[3].rotate_left(45);
        result
    }

    /// Uniform sample in (0, 1) — never exactly 0.
    #[inline]
    fn next_f64(&mut self) -> f64 {
        // Upper 53 bits give a value in [0, 1); add 0.5 ulp so minimum is
        // ~1.1e-16 rather than 0, which avoids ln(0) in Box-Muller.
        let bits = (self.next_u64() >> 11) as f64 * (1.0 / (1u64 << 53) as f64);
        if bits == 0.0 {
            f64::MIN_POSITIVE
        } else {
            bits
        }
    }

    /// Standard normal sample via Box-Muller transform.
    fn next_normal(&mut self) -> f64 {
        let u1 = self.next_f64(); // guaranteed > 0
        let u2 = self.next_f64();
        (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
    }
}

fn splitmix64(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9e3779b97f4a7c15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
    z ^ (z >> 31)
}

// ---------------------------------------------------------------------------
// Statistics helpers
// ---------------------------------------------------------------------------

fn mean(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    values.iter().sum::<f64>() / values.len() as f64
}

fn std_dev(values: &[f64], mean_val: f64) -> f64 {
    if values.len() < 2 {
        return 0.0;
    }
    let var =
        values.iter().map(|r| (r - mean_val).powi(2)).sum::<f64>() / (values.len() - 1) as f64;
    var.sqrt()
}

// ---------------------------------------------------------------------------
// Public API — single asset
// ---------------------------------------------------------------------------

/// Simulate GBM price paths for a single asset.
///
/// Drift (`μ`) and volatility (`σ`) are estimated from `historical_returns`.
/// Each path starts at 1.0 (normalised) and steps forward `n_steps` periods.
///
/// Args:
///     historical_returns: Slice of fractional period returns (e.g. 0.01 for +1%).
///     n_paths: Number of independent paths to generate.
///     n_steps: Number of time steps per path.
///
/// Returns `Err` if `historical_returns` has fewer than 2 observations.
///
/// # Example
/// ```
/// use tick_engine::monte_carlo::simulate;
///
/// let returns = vec![0.001, -0.002, 0.003, 0.0015, -0.001];
/// let paths = simulate(&returns, 500, 100).unwrap();
/// assert_eq!(paths.len(), 500);
/// assert_eq!(paths[0].len(), 100);
/// ```
pub fn simulate(
    historical_returns: &[f64],
    n_paths: usize,
    n_steps: usize,
) -> Result<Vec<Vec<f64>>, EngineError> {
    if historical_returns.len() < 2 {
        return Err(EngineError::InsufficientData {
            required: 2,
            got: historical_returns.len(),
        });
    }
    if n_paths == 0 || n_steps == 0 {
        return Err(EngineError::InvalidParameter {
            message: "n_paths and n_steps must be > 0".to_string(),
        });
    }

    let mu = mean(historical_returns);
    let sigma = std_dev(historical_returns, mu);
    // GBM drift adjusted for discrete simulation: μ - σ²/2
    let drift = mu - 0.5 * sigma * sigma;

    let mut rng = Xoshiro256::new(0xDEAD_BEEF_FEED_CAFE);
    let mut paths = Vec::with_capacity(n_paths);

    for _ in 0..n_paths {
        let mut path = Vec::with_capacity(n_steps);
        let mut price = 1.0f64;
        for _ in 0..n_steps {
            let z = rng.next_normal();
            price *= (drift + sigma * z).exp();
            path.push(price);
        }
        paths.push(path);
    }

    Ok(paths)
}

/// Compute confidence-interval terminal values from a set of simulated paths.
///
/// Each path is represented by its **final value**. The `levels` slice should
/// contain values in (0, 1), e.g. `[0.05, 0.50, 0.95]`. The returned map
/// keys are formatted as `"p{int_percent}"` (e.g. `"p5"`, `"p50"`, `"p95"`).
///
/// # Example
/// ```
/// use tick_engine::monte_carlo::{simulate, confidence_intervals};
///
/// let returns = vec![0.001, -0.002, 0.003];
/// let paths = simulate(&returns, 200, 50).unwrap();
/// let ci = confidence_intervals(&paths, &[0.05, 0.50, 0.95]);
/// assert!(ci["p50"] > 0.0);
/// ```
pub fn confidence_intervals(paths: &[Vec<f64>], levels: &[f64]) -> HashMap<String, f64> {
    let mut terminals: Vec<f64> = paths
        .iter()
        .filter_map(|p| p.last().copied())
        .filter(|v| v.is_finite())
        .collect();

    terminals.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = terminals.len();

    let mut map = HashMap::with_capacity(levels.len());
    for &level in levels {
        let pct_label = format!("p{}", (level * 100.0).round() as u32);
        if n == 0 {
            map.insert(pct_label, 0.0);
            continue;
        }
        let idx_f = level * (n - 1) as f64;
        let lo = idx_f.floor() as usize;
        let hi = idx_f.ceil() as usize;
        let frac = idx_f - lo as f64;
        let value = if lo == hi {
            terminals[lo]
        } else {
            terminals[lo] * (1.0 - frac) + terminals[hi] * frac
        };
        map.insert(pct_label, value);
    }
    map
}

// ---------------------------------------------------------------------------
// Correlated multi-asset simulation (Cholesky)
// ---------------------------------------------------------------------------

/// Run a correlated multi-asset GBM simulation.
///
/// Accepts per-asset historical return series and a correlation matrix
/// (stored row-major, length = n_assets²). Uses Cholesky decomposition to
/// produce correlated standard-normal innovations.
///
/// Args:
///     asset_returns: One Vec per asset, each containing fractional returns.
///     correlation_matrix: Row-major n×n correlation matrix.
///     n_paths: Independent paths to simulate.
///     n_steps: Time steps per path.
///
/// Returns a `Vec` of length `n_assets`, each containing `n_paths` paths of
/// `n_steps` values (all starting from 1.0).
///
/// # Errors
/// - `LengthMismatch` if the correlation matrix is not n×n.
/// - `CholeskyFailed` if the matrix is not positive semi-definite.
/// - `InsufficientData` if any asset has fewer than 2 observations.
///
/// # Example
/// ```
/// use tick_engine::monte_carlo::simulate_correlated;
///
/// let r1 = vec![0.001, 0.002, -0.001, 0.0015];
/// let r2 = vec![-0.001, 0.003, 0.0005, -0.0005];
/// let corr = vec![1.0, 0.7, 0.7, 1.0]; // 2×2 corr matrix
/// let results = simulate_correlated(&[r1, r2], &corr, 100, 50).unwrap();
/// assert_eq!(results.len(), 2);
/// assert_eq!(results[0].len(), 100);
/// ```
pub fn simulate_correlated(
    asset_returns: &[Vec<f64>],
    correlation_matrix: &[f64],
    n_paths: usize,
    n_steps: usize,
) -> Result<Vec<Vec<Vec<f64>>>, EngineError> {
    let n_assets = asset_returns.len();
    if n_assets == 0 {
        return Err(EngineError::EmptyInput {
            context: "asset_returns",
        });
    }
    if correlation_matrix.len() != n_assets * n_assets {
        return Err(EngineError::LengthMismatch {
            expected: n_assets * n_assets,
            got: correlation_matrix.len(),
        });
    }
    for (i, ret) in asset_returns.iter().enumerate() {
        if ret.len() < 2 {
            return Err(EngineError::InsufficientData {
                required: 2,
                got: ret.len(),
            });
        }
        let _ = i;
    }
    if n_paths == 0 || n_steps == 0 {
        return Err(EngineError::InvalidParameter {
            message: "n_paths and n_steps must be > 0".to_string(),
        });
    }

    // Cholesky decomposition of the correlation matrix (L such that L·Lᵀ = C)
    let chol = cholesky_decompose(correlation_matrix, n_assets)?;

    // Per-asset drift and vol
    let params: Vec<(f64, f64)> = asset_returns
        .iter()
        .map(|ret| {
            let mu = mean(ret);
            let sigma = std_dev(ret, mu);
            let drift = mu - 0.5 * sigma * sigma;
            (drift, sigma)
        })
        .collect();

    let mut rng = Xoshiro256::new(0xCAFE_BABE_0123_4567);

    // Output: one Vec<Vec<f64>> per asset (each inner Vec = one path)
    let mut all_paths: Vec<Vec<Vec<f64>>> = (0..n_assets)
        .map(|_| vec![vec![1.0f64; n_steps]; n_paths])
        .collect();

    // Pre-fill all assets' prices to 1.0 (already done above); now simulate
    for path_idx in 0..n_paths {
        let mut prices = vec![1.0f64; n_assets];

        for step in 0..n_steps {
            // Draw n_assets independent normals
            let z_indep: Vec<f64> = (0..n_assets).map(|_| rng.next_normal()).collect();

            // Correlate using Cholesky: z_corr[i] = Σ_j L[i,j] * z_indep[j]
            for i in 0..n_assets {
                let z_corr: f64 = (0..=i).map(|j| chol[i * n_assets + j] * z_indep[j]).sum();
                let (drift, sigma) = params[i];
                prices[i] *= (drift + sigma * z_corr).exp();
                all_paths[i][path_idx][step] = prices[i];
            }
        }
    }

    Ok(all_paths)
}

/// Cholesky decomposition (lower triangular) of a positive semi-definite
/// matrix stored row-major. Returns the lower triangular factor L.
fn cholesky_decompose(matrix: &[f64], n: usize) -> Result<Vec<f64>, EngineError> {
    let mut l = vec![0.0f64; n * n];

    for i in 0..n {
        for j in 0..=i {
            let sum: f64 = (0..j).map(|k| l[i * n + k] * l[j * n + k]).sum();
            if i == j {
                let diag = matrix[i * n + i] - sum;
                if diag < -1e-10 {
                    return Err(EngineError::CholeskyFailed);
                }
                l[i * n + j] = diag.max(0.0).sqrt();
            } else {
                let lj = l[j * n + j];
                if lj.abs() < 1e-14 {
                    l[i * n + j] = 0.0;
                } else {
                    l[i * n + j] = (matrix[i * n + j] - sum) / lj;
                }
            }
        }
    }

    Ok(l)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_returns() -> Vec<f64> {
        vec![
            0.001, -0.002, 0.003, 0.0015, -0.001, 0.002, 0.0005, -0.0008, 0.0012, 0.0018,
        ]
    }

    #[test]
    fn test_simulate_shape() {
        let paths = simulate(&sample_returns(), 200, 50).unwrap();
        assert_eq!(paths.len(), 200);
        assert_eq!(paths[0].len(), 50);
    }

    #[test]
    fn test_simulate_starts_at_one() {
        // All paths should drift from 1.0 — first step != 0
        let paths = simulate(&sample_returns(), 10, 5).unwrap();
        for path in &paths {
            assert!(path[0] > 0.0);
        }
    }

    #[test]
    fn test_simulate_error_on_empty() {
        let result = simulate(&[], 100, 50);
        assert!(result.is_err());
    }

    #[test]
    fn test_confidence_intervals_keys() {
        let paths = simulate(&sample_returns(), 500, 100).unwrap();
        let ci = confidence_intervals(&paths, &[0.05, 0.25, 0.50, 0.75, 0.95]);
        for key in &["p5", "p25", "p50", "p75", "p95"] {
            assert!(ci.contains_key(*key), "missing key: {key}");
        }
    }

    #[test]
    fn test_confidence_intervals_ordering() {
        let paths = simulate(&sample_returns(), 1000, 252).unwrap();
        let ci = confidence_intervals(&paths, &[0.05, 0.50, 0.95]);
        // p5 <= p50 <= p95 (with floating point tolerance)
        assert!(
            ci["p5"] <= ci["p50"] + 1e-10,
            "p5={} p50={}",
            ci["p5"],
            ci["p50"]
        );
        assert!(
            ci["p50"] <= ci["p95"] + 1e-10,
            "p50={} p95={}",
            ci["p50"],
            ci["p95"]
        );
    }

    #[test]
    fn test_cholesky_identity() {
        // Identity matrix → L = I
        let corr = vec![1.0, 0.0, 0.0, 1.0];
        let l = cholesky_decompose(&corr, 2).unwrap();
        assert!((l[0] - 1.0).abs() < 1e-10); // L[0,0]
        assert!((l[1] - 0.0).abs() < 1e-10); // L[0,1]
        assert!((l[2] - 0.0).abs() < 1e-10); // L[1,0]
        assert!((l[3] - 1.0).abs() < 1e-10); // L[1,1]
    }

    #[test]
    fn test_cholesky_known_2x2() {
        // [[1, 0.6], [0.6, 1]] → L[1,0] = 0.6, L[1,1] = sqrt(1-0.36) = 0.8
        let corr = vec![1.0, 0.6, 0.6, 1.0];
        let l = cholesky_decompose(&corr, 2).unwrap();
        assert!((l[0] - 1.0).abs() < 1e-10); // L[0,0]
        assert!((l[2] - 0.6).abs() < 1e-10); // L[1,0]
        assert!((l[3] - 0.8).abs() < 1e-10); // L[1,1]
    }

    #[test]
    fn test_simulate_correlated_shape() {
        let r1 = sample_returns();
        let r2 = sample_returns();
        let corr = vec![1.0, 0.7, 0.7, 1.0];
        let result = simulate_correlated(&[r1, r2], &corr, 100, 50).unwrap();
        assert_eq!(result.len(), 2); // 2 assets
        assert_eq!(result[0].len(), 100); // 100 paths
        assert_eq!(result[0][0].len(), 50); // 50 steps
    }

    #[test]
    fn test_simulate_correlated_error_wrong_corr_size() {
        let r1 = sample_returns();
        let r2 = sample_returns();
        // Supply a 3×3 matrix for 2 assets → error
        let bad_corr = vec![1.0; 9];
        let result = simulate_correlated(&[r1, r2], &bad_corr, 10, 10);
        assert!(result.is_err());
    }

    #[test]
    fn test_simulate_correlated_all_positive_prices() {
        let r1 = sample_returns();
        let r2 = sample_returns();
        let corr = vec![1.0, 0.5, 0.5, 1.0];
        let result = simulate_correlated(&[r1, r2], &corr, 50, 20).unwrap();
        for asset_paths in &result {
            for path in asset_paths {
                for &price in path {
                    assert!(price > 0.0, "price should always be positive");
                }
            }
        }
    }
}
