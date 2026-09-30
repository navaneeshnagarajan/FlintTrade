import { describe, expect, it } from "vitest";
import { OrderApiError } from "@/services/api";
import { LAYA_DEGRADED_LIMITS, layaNoticeFromOrderError } from "@/lib/layaAdmission";

describe("layaNoticeFromOrderError", () => {
  it("shows the server reason under Laya denied and keeps the limits line", () => {
    const notice = layaNoticeFromOrderError(new OrderApiError("Quantity refused.", 403, {
      code: "laya_denied",
      reason: "Quantity refused.",
      message: "Quantity refused.",
      limits: { max_quantity: 1 },
    }));
    expect(notice).toEqual({
      kind: "deny",
      headline: "Laya denied",
      reason: "Quantity refused.",
      limitsLine: "Max quantity 1.",
      appliedQuantity: null,
    });
  });

  it("uses the server clamp sentence and does not invent a denial", () => {
    const notice = layaNoticeFromOrderError(new OrderApiError(
      "Not placed. Laya allows up to 4.",
      409,
      {
        code: "laya_clamp",
        message: "Not placed. Laya allows up to 4.",
        applied_quantity: 4,
        limits: { max_quantity: 4 },
      },
    ));
    expect(notice?.kind).toBe("clamp");
    expect(notice?.headline).toBe("Not placed. Laya allows up to 4.");
    expect(notice?.appliedQuantity).toBe(4);
    expect(notice?.headline).not.toMatch(/denied/i);
  });

  it("refuses one unverified decision without saying Down or offering a quantity", () => {
    const sentence = "Not placed. Laya's decision couldn't be verified. Try again.";
    const notice = layaNoticeFromOrderError(new OrderApiError(sentence, 409, {
      code: "laya_unverified",
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
      "Laya is Down. New orders are paused until it's Ready. You can still close positions.",
      403,
      {
        code: "laya_denied",
        reason: "Laya is Down. New orders are paused until it's Ready. You can still close positions.",
        message: "Laya is Down. New orders are paused until it's Ready. You can still close positions.",
        limits: { max_quantity: 100 },
      },
    ));
    expect(notice?.limitsLine).toBeNull();
    expect(notice?.reason).toBe("Laya is Down. New orders are paused until it's Ready. You can still close positions.");
    expect(notice?.reason).not.toContain("Practice orders are blocked");
  });

  it("does not turn a Live Down mute into a deny", () => {
    const muted = new Error(
      "Laya is Down. New orders are paused until it's Ready. You can still close positions.",
    );
    expect(layaNoticeFromOrderError(muted)).toBeNull();
    const downReason = "Laya is Down. New orders are paused until it's Ready. You can still close positions.";
    const denied = new OrderApiError(downReason, 403, {
      code: "laya_denied",
      reason: downReason,      limits: { max_quantity: 100 },
    });
    expect(layaNoticeFromOrderError(denied, { suppressDeny: true })).toBeNull();
  });

  it("names Degraded limits without Blocked chrome", () => {
    expect(LAYA_DEGRADED_LIMITS).toBe("Laya Degraded — tighter limits");
    expect(LAYA_DEGRADED_LIMITS).not.toMatch(/Blocked/);
    expect(LAYA_DEGRADED_LIMITS).not.toMatch(/llm/i);
  });
});
