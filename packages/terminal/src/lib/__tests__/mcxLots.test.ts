/**
 * mcxLots.test.ts
 *
 * Tests for MCX lot sizes, tick sizes, and helper functions.
 */

import { describe, it, expect } from "vitest";
import {
  MCX_LOT_SIZES,
  MCX_TICK_SIZES,
  MCX_UNITS,
  MCX_COMMODITIES,
  getMCXLotSize,
  getMCXTickSize,
  getMCXUnit,
  isMCXCommodity,
} from "../mcxLots";

// ---------------------------------------------------------------------------
// Lot sizes — key commodities
// ---------------------------------------------------------------------------

describe("MCX_LOT_SIZES", () => {
  it("GOLD lot size is 100 grams", () => {
    expect(MCX_LOT_SIZES.GOLD).toBe(100);
  });

  it("GOLDM lot size is 10 grams", () => {
    expect(MCX_LOT_SIZES.GOLDM).toBe(10);
  });

  it("SILVER lot size is 30000 grams (30 kg)", () => {
    expect(MCX_LOT_SIZES.SILVER).toBe(30000);
  });

  it("SILVERM lot size is 5000 grams (5 kg)", () => {
    expect(MCX_LOT_SIZES.SILVERM).toBe(5000);
  });

  it("CRUDEOIL lot size is 100 barrels", () => {
    expect(MCX_LOT_SIZES.CRUDEOIL).toBe(100);
  });

  it("NATURALGAS lot size is 1250 MMBtu", () => {
    expect(MCX_LOT_SIZES.NATURALGAS).toBe(1250);
  });

  it("COPPER lot size is 2500 kg", () => {
    expect(MCX_LOT_SIZES.COPPER).toBe(2500);
  });

  it("LEAD lot size is 5000 kg", () => {
    expect(MCX_LOT_SIZES.LEAD).toBe(5000);
  });

  it("NICKEL lot size is 1500 kg", () => {
    expect(MCX_LOT_SIZES.NICKEL).toBe(1500);
  });

  it("ALUMINIUM lot size is 5000 kg", () => {
    expect(MCX_LOT_SIZES.ALUMINIUM).toBe(5000);
  });

  it("MENTHAOIL lot size is 360 kg", () => {
    expect(MCX_LOT_SIZES.MENTHAOIL).toBe(360);
  });

  it("COTTON lot size is 25 bales", () => {
    expect(MCX_LOT_SIZES.COTTON).toBe(25);
  });
});

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

describe("getMCXLotSize()", () => {
  it("returns correct lot size for known commodity", () => {
    expect(getMCXLotSize("GOLD")).toBe(100);
    expect(getMCXLotSize("CRUDEOIL")).toBe(100);
  });

  it("is case-insensitive", () => {
    expect(getMCXLotSize("gold")).toBe(100);
    expect(getMCXLotSize("Silver")).toBe(30000);
  });

  it("returns 1 for unknown symbol", () => {
    expect(getMCXLotSize("UNKNOWN")).toBe(1);
  });
});

describe("getMCXTickSize()", () => {
  it("returns 1 for GOLD", () => {
    expect(getMCXTickSize("GOLD")).toBe(1);
  });

  it("returns 0.1 for NATURALGAS", () => {
    expect(getMCXTickSize("NATURALGAS")).toBe(0.1);
  });

  it("returns 1 for unknown symbol", () => {
    expect(getMCXTickSize("UNKNOWN")).toBe(1);
  });
});

describe("getMCXUnit()", () => {
  it("returns 'grams' for GOLD", () => {
    expect(getMCXUnit("GOLD")).toBe("grams");
  });

  it("returns 'barrels' for CRUDEOIL", () => {
    expect(getMCXUnit("CRUDEOIL")).toBe("barrels");
  });

  it("returns 'units' for unknown symbol", () => {
    expect(getMCXUnit("UNKNOWN")).toBe("units");
  });
});

describe("isMCXCommodity()", () => {
  it("returns true for known MCX commodities", () => {
    expect(isMCXCommodity("GOLD")).toBe(true);
    expect(isMCXCommodity("CRUDEOIL")).toBe(true);
    expect(isMCXCommodity("COTTON")).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isMCXCommodity("gold")).toBe(true);
  });

  it("returns false for non-MCX symbols", () => {
    expect(isMCXCommodity("NIFTY")).toBe(false);
    expect(isMCXCommodity("RELIANCE")).toBe(false);
  });
});

describe("MCX_COMMODITIES list", () => {
  it("contains all major commodities", () => {
    const expected = [
      "GOLD", "GOLDM", "SILVER", "SILVERM",
      "CRUDEOIL", "NATURALGAS", "COPPER",
      "ZINC", "LEAD", "NICKEL", "ALUMINIUM",
      "MENTHAOIL", "COTTON",
    ];
    for (const commodity of expected) {
      expect(MCX_COMMODITIES).toContain(commodity);
    }
  });
});

describe("MCX_TICK_SIZES and MCX_UNITS completeness", () => {
  it("every commodity in LOT_SIZES has a tick size", () => {
    for (const commodity of MCX_COMMODITIES) {
      expect(MCX_TICK_SIZES).toHaveProperty(commodity);
    }
  });

  it("every commodity in LOT_SIZES has a unit", () => {
    for (const commodity of MCX_COMMODITIES) {
      expect(MCX_UNITS).toHaveProperty(commodity);
    }
  });
});
