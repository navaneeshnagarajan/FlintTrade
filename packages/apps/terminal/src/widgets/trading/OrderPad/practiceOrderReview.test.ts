import { describe, expect, it } from "vitest";
import {
  createPracticeOrderReviewSnapshot,
  isPracticeOrderReviewCurrent,
  practiceOrderIntentIdentity,
  type PracticeOrderIntentValues,
} from "./practiceOrderReview";

const values: PracticeOrderIntentValues = {
  symbol: "NIFTY28AUG2625000CE",
  exchange: "NFO",
  action: "SELL",
  orderType: "SL",
  product: "NRML",
  qty: 75,
  price: 123.45,
  trigPrice: 124,
  discQty: 25,
};

const params = {
  symbol: "NIFTY28AUG2625000CE",
  exchange: "NFO",
  action: "SELL" as const,
  orderType: "SL" as const,
  product: "NRML" as const,
  quantity: 75,
  price: 123.45,
  triggerPrice: 124,
  disclosedQuantity: 25,
  strategy: "FlintOrderPad",
};

describe("Practice order review model", () => {
  it("captures an immutable payload with exact estimated exposure", () => {
    const review = createPracticeOrderReviewSnapshot(values, params);

    expect(Object.isFrozen(review)).toBe(true);
    expect(Object.isFrozen(review.params)).toBe(true);
    expect(review.params).not.toBe(params);
    expect(review.estimatedPrice).toBe(123.45);
    expect(review.estimatedExposure).toBe(9_258.75);
  });

  it("changes identity for every operator-controlled intent field", () => {
    const original = practiceOrderIntentIdentity(values);
    const changes: PracticeOrderIntentValues[] = [
      { ...values, symbol: "BANKNIFTY" },
      { ...values, exchange: "BFO" },
      { ...values, action: "BUY" },
      { ...values, orderType: "LIMIT" },
      { ...values, product: "MIS" },
      { ...values, qty: 150 },
      { ...values, price: 123.5 },
      { ...values, trigPrice: 125 },
      { ...values, discQty: 50 },
    ];

    for (const changed of changes) {
      expect(practiceOrderIntentIdentity(changed)).not.toBe(original);
    }
  });

  it("rejects stale form values against a captured review identity", () => {
    const review = createPracticeOrderReviewSnapshot(values, params);

    expect(isPracticeOrderReviewCurrent(review, values)).toBe(true);
    expect(isPracticeOrderReviewCurrent(review, { ...values, qty: 150 })).toBe(false);
  });
});
