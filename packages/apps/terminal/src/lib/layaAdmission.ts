/**
 * Desk copy for a Laya place verdict. The server reason is shown as returned.
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
  if (body.code === "laya_denied") {
    if (options?.suppressDeny) return null;
    const reason = typeof body.reason === "string" && body.reason
      ? body.reason
      : typeof body.message === "string"
        ? body.message
        : "";
    const max = readMaxQuantity(body);
    return {
      kind: "deny",
      headline: "Laya denied",
      reason,
      limitsLine: max === null ? null : `Max quantity ${max}.`,
      appliedQuantity: null,
    };
  }
  if (body.code === "laya_clamp") {
    const applied = readAppliedQuantity(body);
    const headline = typeof body.message === "string" && body.message
      ? body.message
      : applied === null
        ? "Qty reduced to the Laya limit"
        : `Qty reduced to ${applied} (Laya limit)`;
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

export const LAYA_DEGRADED_LIMITS = "Laya Degraded — tighter limits";
