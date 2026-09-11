import { describe, expect, it } from "vitest";
import {
  SESSION_OPEN_LABEL,
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
    expect(orderPadCtaLabel("explore", "BUY")).toBe("Sample Buy");
    expect(orderPadCtaLabel("explore", "SELL")).toBe("Sample Sell");
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
    expect(orderReviewTitle("explore")).toBe("Review sample order");
    expect(orderReviewDetailsLabel("explore")).toBe("Sample order details");
    expect(orderReviewConfirmAria("explore")).toBe("Confirm sample order");
    expect(orderReviewDescription("explore")).toMatch(/sample/i);
    expect(orderReviewDescription("explore")).not.toMatch(/Practice Buy|Live/i);
    expect(orderSuccessToast("explore", "ABC")).toBe("Sample order placed · ID: ABC");
    expect(orderSuccessNotificationTitle("explore", "BUY", 1, "NIFTY")).toBe(
      "Sample order placed: BUY 1 NIFTY",
    );
    expect(orderSuccessNotificationBody("explore")).toMatch(/sample fill/i);
  });

  it("session-open chip is session status, not Live mode", () => {
    expect(SESSION_OPEN_LABEL).toBe("Session open");
    expect(SESSION_OPEN_LABEL).not.toMatch(/Live/i);
  });
});
