import { describe, expect, it } from "vitest";
import {
  SESSION_OPEN_LABEL,
  optionPremiumHint,
  orderPadCtaLabel,
  orderReviewConfirmAria,
  orderReviewDescription,
  orderReviewDetailsLabel,
  orderReviewTitle,
  orderSuccessNotificationBody,
  orderSuccessNotificationTitle,
  orderSuccessToast,
} from "../modeVocabulary";

describe("FT-UX-001 mode vocabulary", () => {
  it("Explore order CTA uses sample wording, not Practice or Live", () => {
    expect(orderPadCtaLabel("explore", "BUY")).toBe("Example Buy");
    expect(orderPadCtaLabel("explore", "SELL")).toBe("Example Sell");
    expect(orderPadCtaLabel("explore", "BUY")).not.toMatch(/Practice|Live/i);
  });

  it("Practice keeps Practice Buy / Sell", () => {
    expect(orderPadCtaLabel("practice", "BUY")).toBe("Practice Buy");
    expect(orderPadCtaLabel("practice", "SELL")).toBe("Practice Sell");
  });

  it("Live uses Place BUY/SELL Order and never Sample or Practice", () => {
    expect(orderPadCtaLabel("live", "BUY")).toBe("Place BUY Order");
    expect(orderPadCtaLabel("live", "SELL")).toBe("Place SELL Order");
    expect(orderPadCtaLabel("live", "BUY")).not.toMatch(/Sample|Practice/i);
  });

  it("Explore review and success copy stay sample-labelled", () => {
    expect(orderReviewTitle("explore")).toBe("Review Example order");
    expect(orderReviewDetailsLabel("explore")).toBe("Example order details");
    expect(orderReviewConfirmAria("explore")).toBe("Confirm Example order");
    expect(orderReviewDescription("explore")).toBe(
      "Example only. Nothing is sent to a broker and no order is placed.",
    );
    expect(orderReviewDescription("explore")).not.toMatch(/Explore records a sample fill/i);
    expect(orderReviewDescription("practice")).toBe("Confirm places this simulated order.");
    expect(orderReviewDescription("practice")).not.toMatch(/Explore records a sample fill|Example|sample fill/i);
    expect(orderReviewDescription("explore")).not.toMatch(/Confirm places this simulated order/);
    expect(orderReviewDescription("explore")).not.toMatch(/Practice Buy|Live/i);
    expect(orderSuccessToast("explore", "ABC")).toBe("Example order placed · ID: ABC");
    expect(orderSuccessNotificationTitle("explore", "BUY", 1, "NIFTY")).toBe(
      "Example order placed: BUY 1 NIFTY",
    );
    expect(orderSuccessNotificationBody("explore")).toMatch(/example fill/i);
  });

  it("session-open chip is session status, not Live mode", () => {
    expect(SESSION_OPEN_LABEL).toBe("Session open");
    expect(SESSION_OPEN_LABEL).not.toMatch(/Live/i);
  });

  it("Explore option premium is labelled sample, not Live", () => {
    expect(optionPremiumHint("explore", 623.45)).toMatch(/Example premium ₹623.45/);
    expect(optionPremiumHint("explore", 623.45)).not.toMatch(/Live|Practice/i);
    expect(optionPremiumHint("explore", 0)).toMatch(/Example premium unavailable/);
    expect(optionPremiumHint("practice", 623.45)).toMatch(/Sandbox premium/);
    expect(optionPremiumHint("live", 623.45)).toMatch(/Live premium ₹623.45/);
  });
});
