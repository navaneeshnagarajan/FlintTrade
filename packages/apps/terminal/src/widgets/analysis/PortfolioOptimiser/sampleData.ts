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
