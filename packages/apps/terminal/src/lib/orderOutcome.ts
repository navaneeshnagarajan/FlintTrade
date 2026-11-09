import { OrderPreflightRefusal } from "@/services/orderPreflightRefusal";
import {
  CANCELLATION_REQUESTED,
  ORDER_CANCELLED,
  ORDER_STATUS_UNKNOWN,
} from "@/lib/operatorIncident";

export type SubmitOutcome = { kind: "unknown" | "rejected"; message: string };
export type CancelOutcome = {
  kind: "unknown" | "cancel_requested" | "cancelled" | "rejected";
  message: string;
};

const CONFIRMED_CANCELLED = new Set(["CANCELLED", "CANCELED"]);

function errorRecord(error: unknown): { status?: number; body?: Record<string, unknown>; message: string } {
  const message = error instanceof Error && error.message ? error.message : "Order refused.";
  if (!error || typeof error !== "object") return { message };
  const status = "status" in error && typeof error.status === "number" ? error.status : undefined;
  const raw = "body" in error ? error.body : undefined;
  const body = raw && typeof raw === "object" ? raw as Record<string, unknown> : undefined;
  return { status, body, message };
}

function statusToken(value: unknown): string {
  return String(value ?? "").trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "");
}

/** A lost response is not a rejection. A 4xx refusal, other than 408, still is. */
export function presentSubmitError(error: unknown, unknownMessage = ORDER_STATUS_UNKNOWN): SubmitOutcome {
  if (error instanceof OrderPreflightRefusal) return { kind: "rejected", message: error.message };
  const { status, body, message } = errorRecord(error);
  const outcome = typeof body?.order_outcome === "string" ? body.order_outcome : "";
  const dispatch = typeof body?.dispatch_outcome === "string" ? body.dispatch_outcome : "";
  if (outcome === "rejected" || dispatch === "refused_before_dispatch") {
    const refusal = typeof body?.message === "string" && body.message ? body.message : message;
    return { kind: "rejected", message: refusal };
  }
  if (outcome === "unknown" || dispatch === "unknown_after_dispatch" || message === ORDER_STATUS_UNKNOWN || message === unknownMessage) {
    return { kind: "unknown", message: unknownMessage };
  }
  if (typeof status === "number" && status >= 400 && status < 500 && status !== 408) {
    const refusal = typeof body?.message === "string" && body.message ? body.message : message;
    return { kind: "rejected", message: refusal };
  }
  const serverMessage = typeof body?.message === "string" ? body.message : message;
  if (/no order was sent/i.test(serverMessage)) {
    return { kind: "rejected", message: serverMessage };
  }
  if (status === undefined && serverMessage && !/connection failed|failed to fetch|timed out|timeout|network error|server error|econn|aborted/i.test(serverMessage)) {
    return { kind: "rejected", message: serverMessage };
  }
  return { kind: "unknown", message: unknownMessage };
}

/** An acknowledgement is not a cancel. Confirmed status is. */
export function presentCancelResult(
  result: unknown,
  error?: unknown,
  unknownMessage = ORDER_STATUS_UNKNOWN,
): CancelOutcome {
  if (error) {
    const submit = presentSubmitError(error, unknownMessage);
    return submit.kind === "unknown"
      ? { kind: "unknown", message: unknownMessage }
      : { kind: "rejected", message: submit.message };
  }
  const body = result && typeof result === "object" ? result as Record<string, unknown> : {};
  const outcome = typeof body.order_outcome === "string" ? body.order_outcome : "";
  const status = statusToken(body.status);
  if (outcome === "cancelled" || CONFIRMED_CANCELLED.has(status)) {
    return { kind: "cancelled", message: ORDER_CANCELLED };
  }
  if (outcome === "unknown") return { kind: "unknown", message: unknownMessage };
  if (outcome === "rejected" || status === "REJECTED" || status === "ERROR") {
    const refusal = typeof body.message === "string" && body.message ? body.message : "Cancel refused.";
    return { kind: "rejected", message: refusal };
  }
  return { kind: "cancel_requested", message: CANCELLATION_REQUESTED };
}

export function orderOutcomeIsUncertain(message: string): boolean {
  return message === ORDER_STATUS_UNKNOWN || message === CANCELLATION_REQUESTED;
}
