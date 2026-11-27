/**
 * Desk copy for a decision model place verdict. The server reason is shown as returned.
 */

import { OrderApiError } from "@/services/api";

export interface LayaAdmissionNotice {
  kind: "deny" | "clamp";
  /** Deny headline, or the server clamp sentence. */
  headline: string;
  reason: string;
  limitsLine: string | null;
  appliedQuantity: number | null;
}

function readRecord(body: unknown): Record<string, unknown> | null {
  if (!body || typeof body !== "object") return null;
  return body as Record<string, unknown>;
}

function readMaxQuantity(body: Record<string, unknown>): number | null {
  const limits = body.limits;
  if (!limits || typeof limits !== "object") return null;
  const max = (limits as { max_quantity?: unknown }).max_quantity;
  return typeof max === "number" && Number.isInteger(max) && max >= 1 ? max : null;
}

const LAYA_DOWN_PAUSE = "Not placed. Decision model is down. Start it from Status.";

const LAYA_DECISION_UNVERIFIED = "Not placed. Decision model not verified. Try again.";

const LAYA_DENIED_NO_REASON = "Not placed. Decision model denied this order.";

function readAppliedQuantity(body: Record<string, unknown>): number | null {
  const applied = body.applied_quantity;
  return typeof applied === "number" && Number.isInteger(applied) && applied >= 1 ? applied : null;
}

/**
 * Read a deny or clamp from a failed place. Live Down mute is not a deny.
 * A non-order error, including the thin-wire mute, returns null.
 */
export function layaNoticeFromOrderError(
  err: unknown,
  options?: { suppressDeny?: boolean },
): LayaAdmissionNotice | null {
  if (!(err instanceof OrderApiError)) return null;
  const body = readRecord(err.body);
  if (!body) return null;
  if (body.code === "decision_model_denied") {
    if (options?.suppressDeny) return null;
    const reason = typeof body.reason === "string" && body.reason
      ? body.reason
      : typeof body.message === "string"
        ? body.message
        : "";
    const message = typeof body.message === "string" ? body.message : "";
    const max = reason === LAYA_DOWN_PAUSE || message === LAYA_DOWN_PAUSE
      ? null
      : readMaxQuantity(body);
    return {
      kind: "deny",
      headline: "Denied by decision model",
      reason: reason || LAYA_DENIED_NO_REASON,
      limitsLine: max === null ? null : `Max quantity ${max}.`,
      appliedQuantity: null,
    };
  }
  if (body.code === "decision_model_unverified") {
    const message = typeof body.message === "string" && body.message
      ? body.message
      : LAYA_DECISION_UNVERIFIED;
    return {
      kind: "deny",
      headline: message,
      reason: "",
      limitsLine: null,
      appliedQuantity: null,
    };
  }
  if (body.code === "decision_model_clamp") {
    const applied = readAppliedQuantity(body);
    const headline = typeof body.message === "string" && body.message
      ? body.message
      : applied === null
        ? "Not placed. Review the quantity and resubmit."
        : `Not placed. Decision model allows up to ${applied}.`;
    return {
      kind: "clamp",
      headline,
      reason: "",
      limitsLine: null,
      appliedQuantity: applied,
    };
  }
  return null;
}

export const LAYA_DEGRADED_LIMITS = "Decision model degraded. Tighter limits apply.";
