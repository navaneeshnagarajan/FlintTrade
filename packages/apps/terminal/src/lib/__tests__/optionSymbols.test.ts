import { describe, expect, it } from "vitest";
import { buildCompactOptionSymbol, normaliseExpiryForOptionSymbol } from "../optionSymbols";

describe("option symbol helpers", () => {
  it("keeps compact broker expiries on the same day", () => {
    expect(normaliseExpiryForOptionSymbol("27MAR25")).toBe("27MAR25");
    expect(buildCompactOptionSymbol("NIFTY", "27MAR25", 22000, "CE")).toBe("NIFTY27MAR2522000CE");
  });

  it("normalises dashed and ISO expiries to compact format", () => {
    expect(normaliseExpiryForOptionSymbol("24-MAR-26")).toBe("24MAR26");
    expect(normaliseExpiryForOptionSymbol("2026-03-24")).toBe("24MAR26");
  });

  it("uppercases base symbols and preserves decimal strikes", () => {
    expect(buildCompactOptionSymbol("usdinr", "24apr25", 83.5, "PE")).toBe("USDINR24APR2583.5PE");
  });
});
