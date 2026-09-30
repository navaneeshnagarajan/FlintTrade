import { describe, expect, it } from "vitest";
import {
  RAW_MISSING_LTP_MESSAGE,
  lastCloseFillLabel,
  practicePriceUnavailable,
  visiblePracticeFill,
  visiblePracticeRefusal,
} from "../practicePrice";

describe("practicePrice", () => {
  it("labels a stored close and refuses a missing price in the locked sentences", () => {
    expect(lastCloseFillLabel(812.4, 2 * 86_400)).toBe(
      "Simulated at last close ₹812.40 (2 days old)",
    );
    expect(practicePriceUnavailable("SBIN")).toBe(
      "No price for SBIN right now. Practice needs a live price or a recent close.",
    );
  });

  it("does not show the raw missing-LTP sentence", () => {
    expect(visiblePracticeRefusal(RAW_MISSING_LTP_MESSAGE, "sbin")).toBe(
      "No price for SBIN right now. Practice needs a live price or a recent close.",
    );
    expect(visiblePracticeRefusal("Insufficient capital", "SBIN")).toBe("Insufficient capital");
  });

  it("rebuilds a last-close fill and ignores an unmarked number", () => {
    expect(visiblePracticeFill({
      message: "Paper order executed: BUY 1 SBIN @ 812.40",
      price: 812.4,
      price_source: "last_close",
      price_age_s: 2 * 86_400,
    })).toBe("Simulated at last close ₹812.40 (2 days old)");
    expect(visiblePracticeFill({
      message: "Paper order executed",
      price: 812.4,
    })).toBe("Paper order executed");
  });
});
