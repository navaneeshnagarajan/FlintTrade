/**
 * Sample arbitrage scan for demo/disconnected mode.
 * Mirrors the backend make_sample_arbitrage_scan output.
 */

import type { ArbitrageScan } from "@/types/api";

export const SAMPLE_ARBITRAGE_SCAN: ArbitrageScan = {
  risk_free_rate: 0.07,
  edge_threshold_pct: 1.0,
  cash_future: [
    { underlying: "NIFTY", exchange: "NFO", spot: 24000, future_price: 24055, days_to_expiry: 5, basis: 55, basis_pct: 0.229, fair_basis: 23.03, mispricing: 31.97, annualised_return_pct: 16.73, signal: "cash_and_carry" },
    { underlying: "RELIANCE", exchange: "NFO", spot: 2850, future_price: 2872, days_to_expiry: 12, basis: 22, basis_pct: 0.772, fair_basis: 6.56, mispricing: 15.44, annualised_return_pct: 23.48, signal: "cash_and_carry" },
    { underlying: "TATASTEEL", exchange: "NFO", spot: 165, future_price: 164.2, days_to_expiry: 12, basis: -0.8, basis_pct: -0.485, fair_basis: 0.38, mispricing: -1.18, annualised_return_pct: -14.75, signal: "reverse" },
    { underlying: "HDFCBANK", exchange: "NFO", spot: 1680, future_price: 1682.5, days_to_expiry: 12, basis: 2.5, basis_pct: 0.149, fair_basis: 3.87, mispricing: -1.37, annualised_return_pct: 4.53, signal: "fair" },
  ],
  cross_exchange: [
    { symbol: "RELIANCE", exchange_a: "NSE", price_a: 2850, exchange_b: "BSE", price_b: 2851.4, spread: 1.4, spread_pct: 0.049, buy_on: "NSE", sell_on: "BSE" },
    { symbol: "TATASTEEL", exchange_a: "NSE", price_a: 165, exchange_b: "BSE", price_b: 164.8, spread: 0.2, spread_pct: 0.121, buy_on: "BSE", sell_on: "NSE" },
  ],
};
