import { describe, expect, it } from "vitest";

import { fmtLtp, getOISignal } from "./formatters";

describe("fmtLtp", () => {
  it("preserves an explicit zero while keeping unavailable LTP distinct", () => {
    expect(fmtLtp(0)).toBe("0");
    expect(fmtLtp(null)).toBe("—");
    expect(fmtLtp(undefined)).toBe("—");
  });
});

describe("getOISignal", () => {
  it.each([
    { change_percent: 0, oi_change: 10 },
    { change_pct: 1, oi_change: 0 },
    { change_percent: Number.NaN, oi_change: 10 },
    { change_percent: 1, oi_change: Number.POSITIVE_INFINITY },
  ])("withholds directional labels for zero or malformed changes", (row) => {
    expect(getOISignal(row)).toBeNull();
  });

  it("still classifies finite non-zero changes", () => {
    expect(getOISignal({ change_pct: 1, oi_change: -10 })).toBe("Short Covering");
  });
});
