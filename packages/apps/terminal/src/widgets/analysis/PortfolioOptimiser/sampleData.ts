/**
 * Sample optimiser result for the PortfolioOptimiser widget in explore /
 * disconnected mode. Mirrors the /ft-api/v1/portfolio/optimise PortfolioResult
 * shape so the widget renders identically whether sample or live. Used ONLY
 * when no broker is connected; a "Sample data" badge is shown.
 */

import type { PortfolioResult } from "@/services/ftApi";

/** Default illustrative basket of large-cap NSE names. */
export const SAMPLE_BASKET = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"] as const;

export const SAMPLE_RESULT: PortfolioResult = {
  weights: {
    RELIANCE: 0.27,
    TCS: 0.21,
    HDFCBANK: 0.24,
    INFY: 0.12,
    ICICIBANK: 0.16,
  },
  expected_return: 0.142,
  expected_volatility: 0.168,
  sharpe_ratio: 0.46,
  diversification_ratio: 1.31,
};

/** Illustrative efficient frontier (low → high return, concave vol curve). */
export const SAMPLE_FRONTIER: PortfolioResult[] = [
  { weights: {}, expected_return: 0.06, expected_volatility: 0.121, sharpe_ratio: -0.04, diversification_ratio: 1.4 },
  { weights: {}, expected_return: 0.08, expected_volatility: 0.124, sharpe_ratio: 0.12, diversification_ratio: 1.39 },
  { weights: {}, expected_return: 0.1, expected_volatility: 0.131, sharpe_ratio: 0.27, diversification_ratio: 1.37 },
  { weights: {}, expected_return: 0.12, expected_volatility: 0.143, sharpe_ratio: 0.38, diversification_ratio: 1.35 },
  { weights: {}, expected_return: 0.142, expected_volatility: 0.168, sharpe_ratio: 0.46, diversification_ratio: 1.31 },
  { weights: {}, expected_return: 0.16, expected_volatility: 0.193, sharpe_ratio: 0.49, diversification_ratio: 1.27 },
  { weights: {}, expected_return: 0.18, expected_volatility: 0.226, sharpe_ratio: 0.51, diversification_ratio: 1.22 },
  { weights: {}, expected_return: 0.2, expected_volatility: 0.263, sharpe_ratio: 0.51, diversification_ratio: 1.16 },
  { weights: {}, expected_return: 0.22, expected_volatility: 0.305, sharpe_ratio: 0.51, diversification_ratio: 1.09 },
];
