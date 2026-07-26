/**
 * THE sample sector dataset for the Market Overview widget.
 *
 * The terminal previously carried five separately-invented hardcoded sector
 * tables (SectorPerformance SAMPLE_DATA, MarketSummary SAMPLE_SECTORS,
 * MarketIntelligence INDIA_SECTORS, the Invest route's sample rows and the
 * Scanner sample movers). Within this widget they collapse to this single
 * source, shaped exactly like the live `sectors/rotation` response so the
 * sample and live paths flow through identical rendering code.
 *
 * Values are illustrative — 1D/1W/1M/3M/1Y come from the retired
 * SectorPerformance table; 6M is the midpoint of 3M and 1Y; market caps take
 * the MarketIntelligence figures where the index overlaps. `updated_at` is
 * deliberately empty: sample payloads never carry a freshness claim.
 */

import type { SectorRotationResponse, SectorRotationRow } from "@/services/ftApi.analysis";

const ROWS: SectorRotationRow[] = [
  { symbol: "NIFTYIT",      name: "IT",             change_1d:  1.82, change_1w:  3.56, change_1m:  1.38, change_3m:  -1.42, change_6m:  10.73, change_1y:  22.87, market_cap_cr:   980000, momentum_score:  1.38, quadrant: "leading" },
  { symbol: "NIFTYPHARMA",  name: "Pharma",         change_1d:  0.93, change_1w:  4.21, change_1m:  6.21, change_3m:   5.23, change_6m:  11.83, change_1y:  18.43, market_cap_cr:   620000, momentum_score:  6.21, quadrant: "leading" },
  { symbol: "NIFTYAUTO",    name: "Auto",           change_1d:  0.67, change_1w:  2.41, change_1m:  2.14, change_3m:   7.56, change_6m:  11.59, change_1y:  15.62, market_cap_cr:   540000, momentum_score:  2.14, quadrant: "leading" },
  { symbol: "NIFTYFMCG",    name: "FMCG",           change_1d:  0.41, change_1w:  1.87, change_1m: -1.43, change_3m:  -3.87, change_6m:  -0.23, change_1y:   3.42, market_cap_cr:   720000, momentum_score: -1.43, quadrant: "improving" },
  { symbol: "NIFTYFIN",     name: "Financial Svcs", change_1d:  0.18, change_1w: -0.34, change_1m: -0.87, change_3m:   2.18, change_6m:  15.16, change_1y:  28.14, market_cap_cr:  1250000, momentum_score: -0.87, quadrant: "lagging" },
  { symbol: "NIFTYPVTBANK", name: "Private Bank",   change_1d: -0.12, change_1w: -1.58, change_1m: -3.56, change_3m:  -7.34, change_6m:  13.44, change_1y:  34.21, market_cap_cr:  1150000, momentum_score: -3.56, quadrant: "lagging" },
  { symbol: "NIFTYENERGY",  name: "Energy",         change_1d: -0.28, change_1w:  0.62, change_1m:  3.62, change_3m:  11.34, change_6m:   4.58, change_1y:  -2.18, market_cap_cr:   890000, momentum_score:  3.62, quadrant: "leading" },
  { symbol: "NIFTYREALTY",  name: "Realty",         change_1d: -0.45, change_1w: -0.91, change_1m:  8.43, change_3m:  14.87, change_6m:   0.30, change_1y: -14.27, market_cap_cr:   240000, momentum_score:  8.43, quadrant: "weakening" },
  { symbol: "NIFTYMETAL",   name: "Metal",          change_1d: -0.84, change_1w: -1.24, change_1m:  4.87, change_3m:  18.42, change_6m:  12.65, change_1y:   6.87, market_cap_cr:   310000, momentum_score:  4.87, quadrant: "weakening" },
  { symbol: "NIFTYMEDIA",   name: "Media",          change_1d: -1.07, change_1w: -3.14, change_1m: -5.21, change_3m:  -5.14, change_6m: -13.34, change_1y: -21.54, market_cap_cr:    90000, momentum_score: -5.21, quadrant: "lagging" },
  { symbol: "NIFTYPSUBANK", name: "PSU Bank",       change_1d: -1.36, change_1w: -2.78, change_1m: -3.07, change_3m:  -9.12, change_6m:  -8.78, change_1y:  -8.43, market_cap_cr:   380000, momentum_score: -3.07, quadrant: "lagging" },
  { symbol: "BANKNIFTY",    name: "Bank",           change_1d: -1.71, change_1w: -2.03, change_1m: -2.18, change_3m: -11.83, change_6m:  -0.25, change_1y:  11.34, market_cap_cr:  1420000, momentum_score: -2.18, quadrant: "lagging" },
];

export const SAMPLE_SECTOR_ROTATION: SectorRotationResponse = {
  sectors: ROWS,
  updated_at: "",
  is_sample_data: true,
};
