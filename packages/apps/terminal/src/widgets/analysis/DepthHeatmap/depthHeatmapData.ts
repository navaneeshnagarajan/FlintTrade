/**
 * Depth heatmap synthetic data generation and types.
 *
 * Generates a 2D grid of bid/ask volumes at different price levels over time.
 * Used for initial implementation before live WebSocket depth data is wired.
 *
 * Grid: Y-axis = price levels (200 levels), X-axis = time columns (50 columns).
 * Each cell holds bid volume and ask volume at that price/time intersection.
 */

// ─── Types ────────────────────────────────────────────────────────────────────

export interface DepthHeatmapCell {
  bidVolume: number;
  askVolume: number;
}

export interface DepthHeatmapData {
  /** Price levels from lowest to highest */
  priceLevels: number[];
  /** Time labels for each column (newest on right) */
  timeLabels: string[];
  /**
   * 2D grid: grid[priceIndex][timeIndex] = cell.
   * priceIndex 0 = lowest price.
   */
  grid: DepthHeatmapCell[][];
  /** Current price (LTP) — index into priceLevels */
  currentPriceIndex: number;
  /** Maximum volume in the entire grid (for color scaling) */
  maxVolume: number;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const DEFAULT_NUM_LEVELS = 200;
const DEFAULT_NUM_COLUMNS = 50;
const BASE_PRICE = 24000; // NIFTY-like
const TICK_SIZE = 0.5;

// ─── Seeded pseudo-random for reproducible data ──────────────────────────────

function createRng(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

// ─── Data generation ─────────────────────────────────────────────────────────

/**
 * Generates a realistic depth heatmap grid with:
 * - Volume concentrated near the current price (bell-curve distribution)
 * - Large "iceberg" orders at support/resistance levels
 * - Bid side below current price, ask side above
 * - Gradual drift in price over time columns
 */
export function generateDepthHeatmapData(
  numLevels: number = DEFAULT_NUM_LEVELS,
  numColumns: number = DEFAULT_NUM_COLUMNS,
  seed: number = 42,
): DepthHeatmapData {
  const rng = createRng(seed);

  // Price levels: centered around BASE_PRICE
  const halfLevels = Math.floor(numLevels / 2);
  const priceLevels: number[] = [];
  for (let i = 0; i < numLevels; i++) {
    priceLevels.push(BASE_PRICE + (i - halfLevels) * TICK_SIZE);
  }

  // Time labels (most recent on right)
  const now = new Date();
  const timeLabels: string[] = [];
  for (let i = numColumns - 1; i >= 0; i--) {
    const t = new Date(now.getTime() - i * 3000); // 3s per column
    const hh = String(t.getHours()).padStart(2, "0");
    const mm = String(t.getMinutes()).padStart(2, "0");
    const ss = String(t.getSeconds()).padStart(2, "0");
    timeLabels.push(`${hh}:${mm}:${ss}`);
  }

  // Current price drifts slightly over time
  const priceCenter = halfLevels;
  let maxVolume = 0;

  // Support/resistance levels (large resting orders)
  const supportLevel = Math.floor(halfLevels * 0.7);
  const resistanceLevel = Math.floor(halfLevels * 1.3);

  // Build grid
  const grid: DepthHeatmapCell[][] = [];
  for (let p = 0; p < numLevels; p++) {
    const row: DepthHeatmapCell[] = [];
    for (let t = 0; t < numColumns; t++) {
      // Price center drifts slightly over time
      const drift = Math.sin(t / 8) * 5;
      const center = priceCenter + drift;

      // Distance from center — controls volume distribution
      const distFromCenter = Math.abs(p - center);
      const spreadFactor = 15; // controls how concentrated volume is

      // Base volume: bell curve centered on current price
      const baseVol = Math.max(
        0,
        300 * Math.exp(-0.5 * (distFromCenter / spreadFactor) ** 2),
      );

      // Random variation
      const noise = rng() * 0.6 + 0.7; // 0.7 to 1.3

      // Support/resistance bumps
      let supportBoost = 1;
      if (Math.abs(p - supportLevel) < 3) supportBoost = 2.5 + rng();
      if (Math.abs(p - resistanceLevel) < 3) supportBoost = 2.5 + rng();

      // Occasional large orders ("icebergs")
      const icebergChance = rng();
      const icebergMultiplier = icebergChance > 0.97 ? 3 + rng() * 4 : 1;

      const volume = Math.round(baseVol * noise * supportBoost * icebergMultiplier);

      // Bid volume below center, ask volume above, overlap near center
      let bidVolume = 0;
      let askVolume = 0;

      if (p < center - 2) {
        bidVolume = volume;
      } else if (p > center + 2) {
        askVolume = volume;
      } else {
        // Near center: mix of both
        const ratio = (p - center + 3) / 6; // 0 to 1
        bidVolume = Math.round(volume * (1 - ratio));
        askVolume = Math.round(volume * ratio);
      }

      maxVolume = Math.max(maxVolume, bidVolume, askVolume);
      row.push({ bidVolume, askVolume });
    }
    grid.push(row);
  }

  return {
    priceLevels,
    timeLabels,
    grid,
    currentPriceIndex: priceCenter,
    maxVolume,
  };
}

/**
 * Shifts data one column to the left and generates a new column on the right.
 * Returns a new DepthHeatmapData (immutable update).
 */
export function shiftAndAppendColumn(
  data: DepthHeatmapData,
  seed: number,
): DepthHeatmapData {
  const rng = createRng(seed);
  const numLevels = data.priceLevels.length;
  const numColumns = data.timeLabels.length;

  // New time label
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  const newTimeLabels = [...data.timeLabels.slice(1), `${hh}:${mm}:${ss}`];

  // Slightly drift the current price
  const drift = Math.sin(Date.now() / 5000) * 5;
  const center = Math.floor(numLevels / 2) + drift;
  const halfLevels = Math.floor(numLevels / 2);
  const supportLevel = Math.floor(halfLevels * 0.7);
  const resistanceLevel = Math.floor(halfLevels * 1.3);

  let maxVolume = 0;

  const newGrid: DepthHeatmapCell[][] = [];
  for (let p = 0; p < numLevels; p++) {
    // Shift old columns left (drop index 0, keep 1..N-1)
    const oldRow = data.grid[p];
    const newRow = oldRow.slice(1);

    // Generate new cell for the rightmost column
    const distFromCenter = Math.abs(p - center);
    const spreadFactor = 15;
    const baseVol = Math.max(
      0,
      300 * Math.exp(-0.5 * (distFromCenter / spreadFactor) ** 2),
    );
    const noise = rng() * 0.6 + 0.7;

    let supportBoost = 1;
    if (Math.abs(p - supportLevel) < 3) supportBoost = 2.5 + rng();
    if (Math.abs(p - resistanceLevel) < 3) supportBoost = 2.5 + rng();

    const icebergChance = rng();
    const icebergMultiplier = icebergChance > 0.97 ? 3 + rng() * 4 : 1;

    const volume = Math.round(baseVol * noise * supportBoost * icebergMultiplier);

    let bidVolume = 0;
    let askVolume = 0;
    if (p < center - 2) {
      bidVolume = volume;
    } else if (p > center + 2) {
      askVolume = volume;
    } else {
      const ratio = (p - center + 3) / 6;
      bidVolume = Math.round(volume * (1 - ratio));
      askVolume = Math.round(volume * ratio);
    }

    newRow.push({ bidVolume, askVolume });
    newGrid.push(newRow);

    // Track max across all cells in the new grid
    for (let t = 0; t < numColumns; t++) {
      const cell = newRow[t];
      if (cell) {
        maxVolume = Math.max(maxVolume, cell.bidVolume, cell.askVolume);
      }
    }
  }

  const newPriceIndex = Math.round(
    Math.min(Math.max(center, 0), numLevels - 1),
  );

  return {
    priceLevels: data.priceLevels,
    timeLabels: newTimeLabels,
    grid: newGrid,
    currentPriceIndex: newPriceIndex,
    maxVolume,
  };
}
