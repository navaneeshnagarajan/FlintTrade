/**
 * Sample global indices data for explore/disconnected mode.
 * Values are illustrative — not real market data.
 */

import type { GlobalIndexEntry } from "@/services/ftApi";

function generateHistory(base: number, seed: number): number[] {
  return Array.from({ length: 30 }, (_, i) => {
    const noise = Math.sin((i + seed) * 0.61) * 0.008 + Math.cos((i * seed) * 0.4) * 0.005;
    return base * (1 + noise);
  });
}

export const SAMPLE_INDICES: GlobalIndexEntry[] = [
  // India
  {
    id: "NIFTY50",
    name: "NIFTY 50",
    region: "India",
    ltp: 22_450.30,
    change: 125.60,
    change_pct: 0.56,
    history: generateHistory(22_450, 1),
  },
  {
    id: "SENSEX",
    name: "SENSEX",
    region: "India",
    ltp: 73_961.20,
    change: -210.40,
    change_pct: -0.28,
    history: generateHistory(73_961, 2),
  },
  // US
  {
    id: "SPX",
    name: "S&P 500",
    region: "US",
    ltp: 5_248.80,
    change: 32.10,
    change_pct: 0.62,
    history: generateHistory(5_248, 3),
  },
  {
    id: "NASDAQ",
    name: "NASDAQ",
    region: "US",
    ltp: 16_399.50,
    change: -45.20,
    change_pct: -0.28,
    history: generateHistory(16_399, 4),
  },
  {
    id: "DJI",
    name: "DOW JONES",
    region: "US",
    ltp: 39_127.14,
    change: 88.60,
    change_pct: 0.23,
    history: generateHistory(39_127, 5),
  },
  // Europe
  {
    id: "FTSE100",
    name: "FTSE 100",
    region: "Europe",
    ltp: 7_952.62,
    change: -18.40,
    change_pct: -0.23,
    history: generateHistory(7_952, 6),
  },
  {
    id: "DAX",
    name: "DAX",
    region: "Europe",
    ltp: 18_134.70,
    change: 54.30,
    change_pct: 0.30,
    history: generateHistory(18_134, 7),
  },
  // Asia
  {
    id: "N225",
    name: "Nikkei 225",
    region: "Asia",
    ltp: 38_820.60,
    change: -312.50,
    change_pct: -0.80,
    history: generateHistory(38_820, 8),
  },
  {
    id: "HSI",
    name: "Hang Seng",
    region: "Asia",
    ltp: 16_541.30,
    change: 120.80,
    change_pct: 0.74,
    history: generateHistory(16_541, 9),
  },
  {
    id: "SHCOMP",
    name: "Shanghai Comp",
    region: "Asia",
    ltp: 3_041.20,
    change: -9.60,
    change_pct: -0.31,
    history: generateHistory(3_041, 10),
  },
];
