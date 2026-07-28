/**
 * Deterministic SAMPLE seasonality statistics for Explore mode.
 *
 * Rendered ONLY behind the widget's `!isConnected` guard, always beside the
 * amber "Sample data" badge — never as live output. The values are a
 * plausible NIFTY-like calendar pattern (Diwali-quarter strength, a soft
 * September, flat mid-month days) so the widget is explorable without a
 * broker, but every number here is fabricated.
 */

import type { SeasonalityData, SeasonalityDayOfMonthRow } from "./api";

const SAMPLE_DOM: SeasonalityDayOfMonthRow[] = Array.from(
  { length: 31 },
  (_, index) => {
    const day = index + 1;
    // Deterministic shape: positive start-of-month drift, flat middle,
    // expiry-week (last few days) strength.
    const cycle = Math.sin(((day - 1) / 30) * Math.PI * 2) * 0.05;
    const expiry = day >= 27 ? 0.06 : 0;
    return { day, avg_return_pct: Number((cycle + expiry).toFixed(3)) };
  },
);

export const SAMPLE_SEASONALITY: SeasonalityData = {
  symbol: "NIFTY",
  exchange: "NSE_INDEX",
  is_sample_data: true,
  monthly: [
    { month: 1, month_name: "January", avg_return_pct: -0.4, median_return_pct: -0.2, std_pct: 3.6, positive_rate: 0.45, years_count: 10, best_year: [2021, 5.8], worst_year: [2016, -4.8] },
    { month: 2, month_name: "February", avg_return_pct: 0.3, median_return_pct: 0.5, std_pct: 3.2, positive_rate: 0.55, years_count: 10, best_year: [2021, 6.6], worst_year: [2016, -7.6] },
    { month: 3, month_name: "March", avg_return_pct: 1.1, median_return_pct: 1.3, std_pct: 4.8, positive_rate: 0.64, years_count: 10, best_year: [2016, 10.2], worst_year: [2020, -23.2] },
    { month: 4, month_name: "April", avg_return_pct: 1.4, median_return_pct: 1.2, std_pct: 3.9, positive_rate: 0.7, years_count: 10, best_year: [2020, 14.7], worst_year: [2021, -0.4] },
    { month: 5, month_name: "May", avg_return_pct: 0.2, median_return_pct: 0.4, std_pct: 3.4, positive_rate: 0.55, years_count: 10, best_year: [2020, 7.7], worst_year: [2019, -2.8] },
    { month: 6, month_name: "June", avg_return_pct: 0.6, median_return_pct: 0.8, std_pct: 2.6, positive_rate: 0.6, years_count: 10, best_year: [2020, 7.5], worst_year: [2022, -4.9] },
    { month: 7, month_name: "July", avg_return_pct: 1.7, median_return_pct: 1.9, std_pct: 2.9, positive_rate: 0.75, years_count: 10, best_year: [2022, 8.7], worst_year: [2019, -5.7] },
    { month: 8, month_name: "August", avg_return_pct: 0.5, median_return_pct: 0.9, std_pct: 2.7, positive_rate: 0.6, years_count: 10, best_year: [2021, 8.7], worst_year: [2019, -0.9] },
    { month: 9, month_name: "September", avg_return_pct: -0.7, median_return_pct: -0.5, std_pct: 3.5, positive_rate: 0.4, years_count: 10, best_year: [2019, 4.1], worst_year: [2022, -3.7] },
    { month: 10, month_name: "October", avg_return_pct: 0.9, median_return_pct: 1.1, std_pct: 4.1, positive_rate: 0.6, years_count: 10, best_year: [2022, 5.4], worst_year: [2018, -5.0] },
    { month: 11, month_name: "November", avg_return_pct: 1.5, median_return_pct: 1.6, std_pct: 3.0, positive_rate: 0.7, years_count: 10, best_year: [2020, 11.4], worst_year: [2016, -4.6] },
    { month: 12, month_name: "December", avg_return_pct: 1.2, median_return_pct: 1.0, std_pct: 2.8, positive_rate: 0.7, years_count: 10, best_year: [2023, 7.9], worst_year: [2022, -3.5] },
  ],
  weekday: [
    { weekday: 0, weekday_name: "Monday", avg_return_pct: -0.05, std_pct: 1.2, positive_rate: 0.48, sample_count: 500 },
    { weekday: 1, weekday_name: "Tuesday", avg_return_pct: 0.04, std_pct: 1.0, positive_rate: 0.52, sample_count: 505 },
    { weekday: 2, weekday_name: "Wednesday", avg_return_pct: 0.08, std_pct: 1.0, positive_rate: 0.54, sample_count: 507 },
    { weekday: 3, weekday_name: "Thursday", avg_return_pct: 0.02, std_pct: 1.1, positive_rate: 0.51, sample_count: 503 },
    { weekday: 4, weekday_name: "Friday", avg_return_pct: 0.1, std_pct: 1.0, positive_rate: 0.55, sample_count: 498 },
  ],
  day_of_month: SAMPLE_DOM,
  matrix: { years: [], months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], returns: [] },
};
