/**
 * FT-TRADE-012 — Option Chain OI profile + PCR strip model.
 *
 * Explore stays Sample and never invents live OI. An empty expiry is an
 * honest empty — not a profile of zeros.
 */

import { describe, expect, it } from "vitest";

import {
  buildOiPcrStripModel,
  optionOpenInterest,
  pcrLean,
  strikeHasPositiveOi,
} from "./oiPcrStripData";
import type { StrikeRow } from "./types";

const NIFTY_EXPIRY = "2026-04-10";

function input(overrides: Partial<Parameters<typeof buildOiPcrStripModel>[0]> = {}) {
  return {
    symbol: "NIFTY",
    expiry: NIFTY_EXPIRY,
    expiries: [NIFTY_EXPIRY, "2026-04-17"],
    strikes: [
      { strike: 25_000, call: { oi: 80_000 }, put: { oi: 95_000 } },
      { strike: 25_100, call: { oi: 120_000 }, put: { oi: 110_000 } },
    ] satisfies StrikeRow[],
    pcr: 1.12,
    isExplore: true,
    loading: false,
    ...overrides,
  };
}

describe("optionOpenInterest", () => {
  it("keeps an explicit zero and withholds missing or malformed OI", () => {
    expect(optionOpenInterest({ oi: 0 })).toBe(0);
    expect(optionOpenInterest({ open_interest: 12 })).toBe(12);
    expect(optionOpenInterest({})).toBeNull();
    expect(optionOpenInterest({ oi: 1.5 })).toBeNull();
    expect(optionOpenInterest({ oi: -1 })).toBeNull();
    expect(optionOpenInterest(null)).toBeNull();
  });
});

describe("buildOiPcrStripModel", () => {
  it("builds an OI profile + PCR strip for the selected expiry and symbol", () => {
    const model = buildOiPcrStripModel(input({ isExplore: false }));

    expect(model.kind).toBe("profile");
    expect(model.symbol).toBe("NIFTY");
    expect(model.expiry).toBe(NIFTY_EXPIRY);
    expect(model.pcr).toBe(1.12);
    expect(model.bars).toEqual([
      { strike: 25_000, callOi: 80_000, putOi: 95_000 },
      { strike: 25_100, callOi: 120_000, putOi: 110_000 },
    ]);
    expect(model.sample).toBe(false);
    expect(model.emptyReason).toBeNull();
  });

  it("marks Explore as Sample and never claims live OI", () => {
    const model = buildOiPcrStripModel(input({ isExplore: true }));

    expect(model.sample).toBe(true);
    expect(model.kind).toBe("profile");
    expect(model.pcr).toBe(1.12);
  });

  it("treats a missing expiry list as an honest empty, not zeros-as-data", () => {
    const model = buildOiPcrStripModel(input({
      expiries: [],
      expiry: null,
      strikes: [
        { strike: 25_000, call: { oi: 0 }, put: { oi: 0 } },
      ],
      pcr: 0,
    }));

    expect(model.kind).toBe("empty-expiry");
    expect(model.bars).toEqual([]);
    expect(model.pcr).toBeNull();
    expect(model.emptyReason).toBe("No expiries for this symbol");
    expect(model.sample).toBe(true);
  });

  it("treats an unselected expiry as an honest empty, not zeros-as-data", () => {
    const model = buildOiPcrStripModel(input({
      expiry: null,
      strikes: [],
      pcr: 0,
    }));

    expect(model.kind).toBe("empty-expiry");
    expect(model.bars).toEqual([]);
    expect(model.pcr).toBeNull();
    expect(model.emptyReason).toBe("Select an expiry to load chain");
  });

  it("treats a selected expiry with no positive OI as an honest empty", () => {
    const model = buildOiPcrStripModel(input({
      strikes: [
        { strike: 25_000, call: { oi: 0 }, put: { oi: 0 } },
        { strike: 25_100, call: {}, put: {} },
      ],
      pcr: 0,
    }));

    expect(model.kind).toBe("empty-oi");
    expect(model.bars).toEqual([]);
    expect(model.pcr).toBeNull();
    expect(model.emptyReason).toBe("No OI for this expiry");
  });

  it("does not paint omitted OI as zero on a real profile", () => {
    const model = buildOiPcrStripModel(input({
      strikes: [
        { strike: 25_000, call: {}, put: { oi: 100 } },
        { strike: 25_100, call: { oi: 50 }, put: { oi: 0 } },
      ],
      pcr: null,
    }));

    expect(model.kind).toBe("profile");
    expect(model.bars[0]).toEqual({ strike: 25_000, callOi: null, putOi: 100 });
    expect(model.bars[1]).toEqual({ strike: 25_100, callOi: 50, putOi: 0 });
    expect(model.pcr).toBeNull();
  });

  it("waits while the selected expiry is still loading", () => {
    const model = buildOiPcrStripModel(input({
      strikes: [],
      pcr: null,
      loading: true,
    }));

    expect(model.kind).toBe("loading");
    expect(model.bars).toEqual([]);
    expect(model.pcr).toBeNull();
    expect(model.emptyReason).toBeNull();
  });
});

describe("pcrLean", () => {
  it("classifies PCR the same way the Option Chain header does", () => {
    expect(pcrLean(1.2)).toBe("Bullish");
    expect(pcrLean(0.8)).toBe("Bearish");
    expect(pcrLean(1.0)).toBe("Neutral");
  });
});

describe("strikeHasPositiveOi", () => {
  it("requires a reported positive contract count", () => {
    expect(strikeHasPositiveOi({ strike: 1, call: { oi: 0 }, put: { oi: 0 } })).toBe(false);
    expect(strikeHasPositiveOi({ strike: 1, call: { oi: 1 }, put: null })).toBe(true);
  });
});
