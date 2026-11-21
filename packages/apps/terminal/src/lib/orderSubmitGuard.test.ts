import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearPersistedAuthSession, writePersistedAuthSession } from "@/lib/homeEntry";
import { clearPendingOrderOutcomes } from "@/lib/pendingOrderStore";
import {
  UNKNOWN_SUBMIT_SETTLE_MS,
  orderSubmitLocked,
  readUnknownOrderSubmits,
  reconcileUnknownOrderSubmits,
  submitOrderOnce,
} from "@/lib/orderSubmitGuard";

const SCOPE = "live:upstox:U1";
const OTHER_ACCOUNT = "live:upstox:U2";
const PRACTICE = "practice:sandbox:default";
const STORAGE_KEY = `flinttrade:order-unknown-submits:operator:${encodeURIComponent(SCOPE)}`;
const INTENT = { key: "NFO:NIFTY10APR2625000CE", symbol: "NIFTY10APR2625000CE", exchange: "NFO", action: "BUY" as const };

const lost = () => Promise.reject(new TypeError("Failed to fetch"));

describe("order submit guard", () => {
  beforeEach(() => {
    sessionStorage.clear();
    writePersistedAuthSession({ token: "operator-session", username: "operator", expiresAt: "" });
    clearPendingOrderOutcomes();
  });

  afterEach(() => {
    clearPendingOrderOutcomes();
    clearPersistedAuthSession();
    sessionStorage.clear();
  });

  it("sends one request while the first is in flight", async () => {
    let release!: () => void;
    const send = vi.fn(() => new Promise<string>((resolve) => { release = () => resolve("ok"); }));
    const first = submitOrderOnce(SCOPE, INTENT, send);
    const second = await submitOrderOnce(SCOPE, INTENT, send);
    expect(second).toEqual({ sent: false });
    release();
    expect(await first).toEqual({ sent: true, value: "ok" });
    expect(send).toHaveBeenCalledTimes(1);
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(false);
  });

  it.each([
    ["a dropped connection", new TypeError("Failed to fetch")],
    ["a gateway timeout", Object.assign(new Error("Gateway Timeout"), { status: 504 })],
    ["an HTTP 500", Object.assign(new Error("Internal Server Error"), { status: 500 })],
    ["an unknown outcome body", Object.assign(new Error("x"), { status: 502, body: { order_outcome: "unknown" } })],
  ])("locks the instrument after %s and never resends", async (_label, error) => {
    const send = vi.fn(() => Promise.reject(error));
    await expect(submitOrderOnce(SCOPE, INTENT, send)).rejects.toBe(error);
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(true);
    expect(await submitOrderOnce(SCOPE, INTENT, send)).toEqual({ sent: false });
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("does not lock after a definite refusal", async () => {
    const refusal = Object.assign(new Error("Freeze limit"), { status: 400, body: { message: "Freeze limit" } });
    await expect(submitOrderOnce(SCOPE, INTENT, () => Promise.reject(refusal))).rejects.toBe(refusal);
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(false);
  });

  it("keeps the lock when a complete read started immediately after the loss", async () => {
    vi.useFakeTimers();
    try {
      const pending = submitOrderOnce(SCOPE, INTENT, lost, 100);
      await expect(pending).rejects.toThrow();
      const receivedAt = readUnknownOrderSubmits(SCOPE)[0].receivedAt;
      const startedAt = receivedAt + 40;
      reconcileUnknownOrderSubmits(SCOPE, { startedAt, completedAt: startedAt + 10 });
      expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("unlocks only on a complete read that started after the settle delay", async () => {
    vi.useFakeTimers();
    try {
      const pending = submitOrderOnce(SCOPE, INTENT, lost, 100);
      await expect(pending).rejects.toThrow();
      const receivedAt = readUnknownOrderSubmits(SCOPE)[0].receivedAt;
      vi.advanceTimersByTime(UNKNOWN_SUBMIT_SETTLE_MS);
      const startedAt = Date.now();
      expect(startedAt).toBeGreaterThanOrEqual(receivedAt + UNKNOWN_SUBMIT_SETTLE_MS);
      reconcileUnknownOrderSubmits(SCOPE, { startedAt, completedAt: startedAt + 10 });
      expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("records one unknown entry leg for a lost submit", async () => {
    await expect(submitOrderOnce(SCOPE, INTENT, lost)).rejects.toThrow();
    expect(readUnknownOrderSubmits(SCOPE)[0].legs).toEqual({ entry: "unknown" });
  });

  it("records the per-leg outcomes a lost bracket reply reports", async () => {
    const bracketLost = Object.assign(new Error("Order status unknown. Check Orders before trying again."), {
      status: 502,
      body: { order_outcome: "unknown", leg_outcomes: { entry: "confirmed", stop_loss: "unknown" } },
    });
    await expect(submitOrderOnce(SCOPE, INTENT, () => Promise.reject(bracketLost))).rejects.toBe(bracketLost);
    expect(readUnknownOrderSubmits(SCOPE)[0].legs).toEqual({ entry: "confirmed", stop_loss: "unknown" });
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(true);
  });

  it("keeps an unknown entry leg when a lost reply reports no unknown leg", async () => {
    const malformed = Object.assign(new Error("x"), {
      status: 502,
      body: { order_outcome: "unknown", leg_outcomes: { entry: "confirmed" } },
    });
    await expect(submitOrderOnce(SCOPE, INTENT, () => Promise.reject(malformed))).rejects.toBe(malformed);
    expect(readUnknownOrderSubmits(SCOPE)[0].legs).toEqual({ entry: "unknown" });
  });

  it("discards a stored lock whose leg outcome is not unknown, confirmed or absent", () => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([{
      ...INTENT, receivedAt: 1, listUpdatedAt: 0, legs: { entry: "filled" },
    }]));
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(false);
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("keeps the lock for the session and scopes it to the account", async () => {
    await expect(submitOrderOnce(SCOPE, INTENT, lost)).rejects.toThrow();
    expect(sessionStorage.getItem(STORAGE_KEY)).toContain(INTENT.key);
    expect(orderSubmitLocked(OTHER_ACCOUNT, INTENT.key)).toBe(false);
    expect(orderSubmitLocked(PRACTICE, INTENT.key)).toBe(false);
  });

  it("clears every lock on sign-out", async () => {
    await expect(submitOrderOnce(SCOPE, INTENT, lost)).rejects.toThrow();
    clearPendingOrderOutcomes();
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(false);
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("drops a corrupted stored value", () => {
    sessionStorage.setItem(STORAGE_KEY, "[{\"key\":1}]");
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(false);
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("still locks for this page when the session cannot store it", async () => {
    clearPersistedAuthSession();
    await expect(submitOrderOnce(SCOPE, INTENT, lost)).rejects.toThrow();
    expect(orderSubmitLocked(SCOPE, INTENT.key)).toBe(true);
    expect(Object.keys(sessionStorage).some((key) => key.startsWith("flinttrade:order-unknown-submits:"))).toBe(false);
  });
});
