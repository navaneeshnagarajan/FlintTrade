import { describe, expect, it } from "vitest";
import { TRADE_BOOK_PANEL_DEFAULT_PERCENT, tradeBookTabFromHash } from "../trade/tradeBookPanel";

describe("trade book panel", () => {
  it("opens the book at 28% and selects the hash tab", () => {
    expect(TRADE_BOOK_PANEL_DEFAULT_PERCENT).toBe(28);
    expect(tradeBookTabFromHash("#positions")).toBe("positions");
    expect(tradeBookTabFromHash("#orders")).toBe("orders");
    expect(tradeBookTabFromHash("#alerts")).toBeNull();
    expect(tradeBookTabFromHash("")).toBeNull();
  });
});
