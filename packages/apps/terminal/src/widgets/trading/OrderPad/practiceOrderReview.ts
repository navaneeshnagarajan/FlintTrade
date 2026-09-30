import type { PlaceOrderParams } from "@/types/api";

export interface PracticeOrderIntentValues {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  product: "MIS" | "CNC" | "NRML";
  qty: number;
  price?: number;
  trigPrice?: number;
  discQty?: number;
}

export interface PracticeOrderReviewSnapshot {
  readonly identity: string;
  readonly params: Readonly<PlaceOrderParams>;
  readonly estimatedPrice: number | null;
  readonly estimatedExposure: number | null;
}

function finiteNumberOrNull(value: number | undefined): number | null {
  return value !== undefined && Number.isFinite(value) ? value : null;
}

/** Stable identity for every operator-controlled field in an OrderPad intent. */
export function practiceOrderIntentIdentity(values: PracticeOrderIntentValues): string {
  return JSON.stringify([
    values.symbol,
    values.exchange,
    values.action,
    values.orderType,
    values.product,
    values.qty,
    finiteNumberOrNull(values.price),
    finiteNumberOrNull(values.trigPrice),
    finiteNumberOrNull(values.discQty),
  ]);
}

/**
 * Capture the exact, immutable Practice payload shown to the operator.
 * The reference price is already resolved by OrderPad (LIMIT price or the
 * Practice MARKET fill estimate), so the displayed exposure matches the
 * payload that confirmation can submit.
 */
export function createPracticeOrderReviewSnapshot(
  values: PracticeOrderIntentValues,
  params: PlaceOrderParams,
): PracticeOrderReviewSnapshot {
  const frozenParams = Object.freeze({ ...params });
  const estimatedPrice =
    typeof frozenParams.price === "number" && Number.isFinite(frozenParams.price) && frozenParams.price > 0
      ? frozenParams.price
      : null;
  const estimatedExposure = estimatedPrice === null
    ? null
    : estimatedPrice * frozenParams.quantity;

  return Object.freeze({
    identity: practiceOrderIntentIdentity(values),
    params: frozenParams,
    estimatedPrice,
    estimatedExposure,
  });
}

/** Review snapshot after Place N, showing the quantity that will be placed. */
export function practiceReviewPlacedQuantity(
  review: PracticeOrderReviewSnapshot,
  quantity: number,
): PracticeOrderReviewSnapshot {
  const fields: unknown[] = JSON.parse(review.identity);
  fields[5] = quantity;
  const params = Object.freeze({ ...review.params, quantity });
  const estimatedExposure = review.estimatedPrice === null ? null : review.estimatedPrice * quantity;
  return Object.freeze({
    identity: JSON.stringify(fields),
    params,
    estimatedPrice: review.estimatedPrice,
    estimatedExposure,
  });
}

export function isPracticeOrderReviewCurrent(
  review: PracticeOrderReviewSnapshot,
  values: PracticeOrderIntentValues,
): boolean {
  return review.identity === practiceOrderIntentIdentity(values);
}
