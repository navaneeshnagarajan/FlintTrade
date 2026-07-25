/**
 * oiStrikes — the shared chain → strike-cell kernel every OI Analytics view
 * renders from. These cases pin the contract at the source, independently of
 * any one view's markup.
 */

import { describe, it, expect } from "vitest";

import {
  buildStrikeCells,
  chainHasPositiveOi,
  filterStrikeCells,
  strikePcr,
  summariseStrikeCells,
} from "../oiStrikes";

describe("buildStrikeCells", () => {
  it("returns nothing for an absent chain", () => {
    expect(buildStrikeCells(null, 25_000, 15)).toEqual({ cells: [], atmStrike: null });
  });

  it("reads the backend's oi_change rather than deriving one", () => {
    const { cells } = buildStrikeCells(
      { chain: [{ strike: 25_000, ce: { oi: 100, oi_change: -40 }, pe: { oi: 200, oi_change: 60 } }] },
      25_000,
      15,
    );
    expect(cells[0].ceOiChange).toBe(-40);
    expect(cells[0].peOiChange).toBe(60);
  });

  it("keeps an absent OI change unavailable instead of zero", () => {
    const { cells } = buildStrikeCells(
      { chain: [{ strike: 25_000, ce: { oi: 100 }, pe: { oi: 200 } }] },
      25_000,
      15,
    );
    expect(cells[0].ceOiChange).toBeNull();
    expect(cells[0].peOiChange).toBeNull();
  });

  it("preserves an explicit zero OI while rejecting malformed values", () => {
    const { cells } = buildStrikeCells(
      {
        chain: [
          { strike: 25_000, ce: { oi: 0 }, pe: { oi: 12.5 } },
          { strike: 25_050, ce: { oi: -5 }, pe: {} },
        ],
      },
      25_000,
      15,
    );
    expect(cells[0].ceOi).toBe(0);
    // Open interest is a whole number of contracts; 12.5 is not one.
    expect(cells[0].peOi).toBeNull();
    expect(cells[1].ceOi).toBeNull();
    expect(cells[1].peOi).toBeNull();
  });

  it("drops rows without a positive strike from either chain shape", () => {
    const v2 = buildStrikeCells(
      { chain: [{ strike: 0, ce: { oi: 1 }, pe: { oi: 1 } }, { strike: 25_000, ce: { oi: 1 }, pe: { oi: 1 } }] },
      25_000,
      15,
    );
    const legacy = buildStrikeCells(
      {
        calls: [{ oi: 1 }, { strike: 0, oi: 1 }, { strike_price: 25_000, oi: 1 }],
        puts: [{ strike_price: 25_000, oi: 2 }],
      },
      25_000,
      15,
    );
    expect(v2.cells.map((c) => c.strike)).toEqual([25_000]);
    expect(legacy.cells.map((c) => c.strike)).toEqual([25_000]);
  });

  it("centres the window on the strike nearest spot, not on the payload's atm_strike", () => {
    const chain = {
      atm_strike: 25_000,
      chain: Array.from({ length: 41 }, (_, i) => ({
        strike: 24_500 + i * 50,
        ce: { oi: 1 },
        pe: { oi: 1 },
      })),
    };
    const { cells, atmStrike } = buildStrikeCells(chain, 25_600, 5);
    expect(atmStrike).toBe(25_600);
    expect(cells.map((c) => c.strike)).toEqual([
      25_350, 25_400, 25_450, 25_500, 25_550, 25_600, 25_650, 25_700, 25_750, 25_800, 25_850,
    ]);
  });

  it("returns no ATM at all when spot is unknown", () => {
    const { atmStrike } = buildStrikeCells(
      { chain: [{ strike: 25_000, ce: { oi: 1 }, pe: { oi: 1 } }] },
      null,
      15,
    );
    expect(atmStrike).toBeNull();
  });
});

describe("filterStrikeCells", () => {
  const cells = buildStrikeCells(
    {
      chain: [
        { strike: 25_000, ce: { oi: 10, oi_change: 5 }, pe: { oi: 10, oi_change: -1 } },
        { strike: 25_050, ce: { oi: 10, oi_change: -5 }, pe: { oi: 10, oi_change: -2 } },
        { strike: 25_100, ce: { oi: 10 }, pe: { oi: 10 } },
      ],
    },
    25_050,
    15,
  ).cells;

  it("keeps only strikes whose reported change is positive", () => {
    expect(filterStrikeCells(cells, "OI Increase").map((c) => c.strike)).toEqual([25_000]);
  });

  it("keeps only strikes whose reported change is negative", () => {
    expect(filterStrikeCells(cells, "OI Decrease").map((c) => c.strike)).toEqual([25_000, 25_050]);
  });

  it("excludes an unknown change from BOTH directions", () => {
    // 25100 reports no change at all — that is not evidence of either direction.
    expect(filterStrikeCells(cells, "OI Increase").some((c) => c.strike === 25_100)).toBe(false);
    expect(filterStrikeCells(cells, "OI Decrease").some((c) => c.strike === 25_100)).toBe(false);
    expect(filterStrikeCells(cells, "All")).toHaveLength(3);
  });
});

describe("summariseStrikeCells", () => {
  it("withholds a total when one leg on that side did not report", () => {
    const { cells } = buildStrikeCells(
      {
        chain: [
          { strike: 25_000, ce: {}, pe: { oi: 10 } },
          { strike: 25_050, ce: { oi: 20 }, pe: { oi: 30 } },
        ],
      },
      25_000,
      15,
    );
    const summary = summariseStrikeCells(cells);
    expect(summary.totalCeOi).toBeNull();
    expect(summary.totalPeOi).toBe(40);
    expect(summary.maxCeStrike).toBeNull();
    expect(summary.maxPeStrike).toBe(25_050);
  });

  it("withholds PCR on a zero call-OI denominator", () => {
    const { cells } = buildStrikeCells(
      { chain: [{ strike: 25_000, ce: { oi: 0 }, pe: { oi: 100 } }] },
      25_000,
      15,
    );
    expect(summariseStrikeCells(cells).pcr).toBeNull();
  });

  it("computes PCR over exactly the rows it was given", () => {
    const { cells } = buildStrikeCells(
      {
        // A whole-chain `pcr` field would describe a different population.
        pcr: 999,
        chain: [
          { strike: 25_000, ce: { oi: 100 }, pe: { oi: 60 } },
          { strike: 25_050, ce: { oi: 100 }, pe: { oi: 60 } },
        ],
      },
      25_000,
      15,
    );
    expect(summariseStrikeCells(cells).pcr).toBeCloseTo(0.6, 10);
  });

  it("does not name a max-OI strike on an all-zero side", () => {
    const { cells } = buildStrikeCells(
      {
        chain: [
          { strike: 25_000, ce: { oi: 0 }, pe: { oi: 0 } },
          { strike: 25_050, ce: { oi: 0 }, pe: { oi: 0 } },
        ],
      },
      25_000,
      15,
    );
    const summary = summariseStrikeCells(cells);
    expect(summary.maxCeStrike).toBeNull();
    expect(summary.maxPeStrike).toBeNull();
  });
});

describe("strikePcr and chainHasPositiveOi", () => {
  it("withholds per-strike PCR unless both legs reported and CE OI is positive", () => {
    expect(strikePcr({ strike: 1, ceOi: 100, peOi: 50, ceOiChange: null, peOiChange: null, ceVolume: null, peVolume: null })).toBe(0.5);
    expect(strikePcr({ strike: 1, ceOi: 0, peOi: 50, ceOiChange: null, peOiChange: null, ceVolume: null, peVolume: null })).toBeNull();
    expect(strikePcr({ strike: 1, ceOi: null, peOi: 50, ceOiChange: null, peOiChange: null, ceVolume: null, peVolume: null })).toBeNull();
  });

  it("reports an all-zero chain as carrying no open interest", () => {
    const { cells } = buildStrikeCells(
      { chain: [{ strike: 25_000, ce: { oi: 0 }, pe: { oi: 0 } }] },
      25_000,
      15,
    );
    expect(chainHasPositiveOi(cells)).toBe(false);
  });
});
