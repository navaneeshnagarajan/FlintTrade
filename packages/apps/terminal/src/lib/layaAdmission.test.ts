import { describe, expect, it } from "vitest";
import { OrderApiError } from "@/services/api";
import { LAYA_DEGRADED_LIMITS, layaNoticeFromOrderError } from "@/lib/layaAdmission";

describe("layaNoticeFromOrderError", () => {
  it("shows the server reason under Laya denied and keeps the limits line", () => {
    const notice = layaNoticeFromOrderError(new OrderApiError("Quantity refused.", 403, {
      code: "decision_model_denied",
      reason: "Quantity refused.",
      message: "Quantity refused.",
      limits: { max_quantity: 1 },
    }));
    expect(notice).toEqual({
      kind: "deny",
      headline: "Denied by decision model",
      reason: "Quantity refused.",
      limitsLine: "Max quantity 1.",
      appliedQuantity: null,
    });
  });

  it("uses the server clamp sentence and does not invent a denial", () => {
    const notice = layaNoticeFromOrderError(new OrderApiError(
      "Not placed. Decision model allows up to 4.",
      409,
      {
        code: "decision_model_clamp",
        message: "Not placed. Decision model allows up to 4.",
        applied_quantity: 4,
        limits: { max_quantity: 4 },
      },
    ));
    expect(notice?.kind).toBe("clamp");
    expect(notice?.headline).toBe("Not placed. Decision model allows up to 4.");
    expect(notice?.appliedQuantity).toBe(4);
    expect(notice?.headline).not.toMatch(/denied/i);
  });

  it("refuses one unverified decision without saying Down or offering a quantity", () => {
    const sentence = "Not placed. Decision model not verified. Try again.";
    const notice = layaNoticeFromOrderError(new OrderApiError(sentence, 409, {
      code: "decision_model_unverified",
      message: sentence,
      reason: sentence,
      limits: { max_quantity: 4 },
      applied_quantity: 4,
    }));
    expect(notice).toEqual({
      kind: "deny",
      headline: sentence,
      reason: "",
      limitsLine: null,
      appliedQuantity: null,
    });
    expect(notice?.headline).not.toMatch(/Down/);
    expect(notice?.headline).not.toMatch(/allows up to/);
  });

  it("hides a quantity ceiling when Laya is Down", () => {
    const notice = layaNoticeFromOrderError(new OrderApiError(
      "Not placed. Decision model is down. Start it from Status.",
      403,
      {
        code: "decision_model_denied",
        reason: "Not placed. Decision model is down. Start it from Status.",
        message: "Not placed. Decision model is down. Start it from Status.",
        limits: { max_quantity: 100 },
      },
    ));
    expect(notice?.limitsLine).toBeNull();
    expect(notice?.reason).toBe("Not placed. Decision model is down. Start it from Status.");
    expect(notice?.reason).not.toContain("Practice orders are blocked");
  });

  it("does not turn a Live Down mute into a deny", () => {
    const muted = new Error(
      "Not placed. Decision model is down. Start it from Status.",
    );
    expect(layaNoticeFromOrderError(muted)).toBeNull();
    const downReason = "Not placed. Decision model is down. Start it from Status.";
    const denied = new OrderApiError(downReason, 403, {
      code: "decision_model_denied",
      reason: downReason,      limits: { max_quantity: 100 },
    });
    expect(layaNoticeFromOrderError(denied, { suppressDeny: true })).toBeNull();
  });

  it("names Degraded limits without Blocked chrome", () => {
    expect(LAYA_DEGRADED_LIMITS).toBe("Decision model degraded. Tighter limits apply.");
    expect(LAYA_DEGRADED_LIMITS).not.toMatch(/Blocked/);
    expect(LAYA_DEGRADED_LIMITS).not.toMatch(/llm/i);
  });
});
