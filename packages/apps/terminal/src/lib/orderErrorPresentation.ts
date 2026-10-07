import { z } from "zod";
import { OrderApiError } from "@/services/api";
import { OrderPreflightRefusal } from "@/services/orderPreflightRefusal";
import { NATIVE_TARGET_NOT_READY_MESSAGE } from "@/services/brokerTargets";
import type { PlaceOrderParams } from "@/types/api";

const boundedText = z.string().min(1).max(256)
  .regex(/^[^\u0000-\u001f\u007f-\u009f\p{Bidi_Control}]+$/u);
/** Keep captured identity literal when safe; omit an invalid pair whole. */
export function capturedOrderTitle(label: string, params: Pick<PlaceOrderParams, "action" | "symbol">, quantity?: number): string {
  if (![params.action, params.symbol].every((field) => boundedText.safeParse(field).success)) return label;
  return `${label}: ${params.action} ${quantity === undefined ? "" : `${quantity} `}${params.symbol}`;
}

const nativeCode = z.string().regex(/^[A-Za-z0-9_.:-]{1,64}$/);
const dispatchError = z.object({
  status: z.literal("error"),
  dispatch_outcome: z.enum(["refused_before_dispatch", "unknown_after_dispatch"]),
  retry_safe: z.literal(false),
  affected_item: z.object({
    broker: boundedText, account_id: boundedText, operation: z.literal("place"),
    symbol: boundedText, exchange: boundedText, product: boundedText,
    action: z.enum(["BUY", "SELL"]),
  }),
});
const errorRecord = z.record(z.string(), z.unknown());
const localGuardMessages = new Set([
  NATIVE_TARGET_NOT_READY_MESSAGE,
  "Order blocked: the displayed account authority no longer matches the current source, scope, account, or connection.",
  "Rate limit exceeded for place (order: 10/s)",
  ...["Example", "Practice", "Live"].flatMap((from) => ["Example", "Practice", "Live"].map(
    (to) => `Order blocked: mode changed from ${from} to ${to} before submission.`,
  )),
]);

export interface OrderErrorOrigin {
  broker: string;
  accountId: string;
  params: Readonly<PlaceOrderParams>;
}

export interface OrderErrorPresentation {
  title: string;
  body: string;
}

function originText(origin: OrderErrorOrigin): string {
  const { broker, accountId, params } = origin;
  // Preserve opaque identifiers literally. An oversized identifier is omitted,
  // never shortened into another identity. The response cannot supply origin.
  const fields = [broker, accountId, params.action, params.symbol, params.exchange, params.product];
  return fields.every((field) => boundedText.safeParse(field).success)
    ? ` Origin: ${broker} / ${accountId} · ${params.action} ${params.symbol} (${params.exchange} / ${params.product}).`
    : "";
}

/** Presentation only: never write/retry, change authority or infer a fill. */
export function nativeOrderErrorPresentation(error: unknown, origin: OrderErrorOrigin): OrderErrorPresentation | null {
  const unknown = (): OrderErrorPresentation => ({
    title: capturedOrderTitle("Order outcome unknown", origin.params),
    body: `Order outcome unknown. An order may still execute. Check broker positions and orders. Do not retry automatically.${originText(origin)}`,
  });
  if (!(error instanceof OrderApiError)) {
    // Only known local pre-transport guard copy may use the existing refusal
    // path. Arbitrary exceptions (including connection loss) disclose no text.
    if (error instanceof OrderPreflightRefusal
      && (localGuardMessages.has(error.message) || boundedText.safeParse(error.message).success)) return null;
    return unknown();
  }
  const record = errorRecord.safeParse(error.body);
  const body = record.success ? record.data : null;
  const parsed = dispatchError.safeParse(body);
  if (parsed.success) {
    const { affected_item: item, dispatch_outcome: outcome } = parsed.data;
    const { params } = origin;
    if (item.broker !== origin.broker || item.account_id !== origin.accountId
      || item.symbol !== params.symbol || item.exchange !== params.exchange
      || item.product !== params.product || item.action !== params.action) return unknown();
    // Server-redacted, explicitly separate canonical native properties only.
    // Invalid/oversized values are omitted, not stringified or truncated.
    const reason = boundedText.safeParse(body?.broker_message);
    const code = nativeCode.safeParse(body?.broker_code);
    const observations = `${reason.success ? ` Broker reason (observation): ${reason.data}.` : ""}${code.success ? ` Broker code: ${code.data}.` : ""}`;
    if (outcome === "unknown_after_dispatch") {
      const presentation = unknown();
      return { ...presentation, body: presentation.body + observations };
    }
    const summary = boundedText.safeParse(body?.message);
    return {
      title: capturedOrderTitle("Order refused", params),
      body: `Order refused before dispatch. No order was sent. No automatic retry.${originText(origin)}${summary.success ? ` Refusal: ${summary.data}.` : ""}${observations}`,
    };
  }
  // A partial/contradictory structured response cannot become a legacy definite
  // refusal based on its status, code, exception class or optimistic message.
  if (body && ["dispatch_outcome", "retry_safe", "affected_item", "broker_code", "broker_message"].some((key) => Object.hasOwn(body, key))) return unknown();
  // Preserve this existing explicit activation refusal, not a status-based
  // inference. It is separate from the gated possible-dispatch contract.
  if (error.status === 503 && body?.status === "error"
    && body.message === "INDstocks activation is unavailable. No order was sent.") return null;
  if (error.status === 401) return null; // The client substitutes fixed auth copy.
  if (error.status >= 400 && error.status < 500 && error.status !== 408
    && body?.status === "error" && (boundedText.safeParse(body.message).success
      || ["exit_pending", "exit_orders_unreadable", "gtt_unsupported"].includes(typeof body.code === "string" ? body.code : ""))) return null;
  return unknown();
}
