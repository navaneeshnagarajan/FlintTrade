import { describe, expect, it, vi } from "vitest";

import {
  STARTUP_RECOVERY_HEARTBEAT_INTERVAL_MS,
  createStartupRecoveryController,
} from "./startup-recovery";
import { createBootstrapState } from "./state";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function fixture(options: { heartbeatIntervalMs?: number } = {}) {
  const trace: string[] = [];
  const state = createBootstrapState();
  const bootstrap = {
    cancel: vi.fn(async () => true),
    retry: vi.fn(async () => ({ ok: true as const })),
    shutdown: vi.fn(async () => {
      trace.push("shutdown");
    }),
    start: vi.fn(async () => {
      trace.push("bootstrap");
      return { ok: true as const };
    }),
  };
  const recovery = {
    cancel: vi.fn(() => true),
    recover: vi.fn<(signal: AbortSignal) => Promise<{ status: "idle" | "promoted" | "rolled-back" }>>(async () => {
      trace.push("recover");
      return { status: "idle" as const };
    }),
    settleForQuit: vi.fn(async () => {
      trace.push("safe-to-quit");
    }),
  };
  const controller = createStartupRecoveryController({
    bootstrap,
    recovery,
    state,
    ...(options.heartbeatIntervalMs === undefined
      ? {}
      : { heartbeatIntervalMs: options.heartbeatIntervalMs }),
  });
  return { bootstrap, controller, recovery, state, trace };
}

describe("startup recovery gate", () => {
  it("keeps the production startup-recovery heartbeat within the four-second acceptance bound", () => {
    expect(STARTUP_RECOVERY_HEARTBEAT_INTERVAL_MS).toBeLessThanOrEqual(4_000);
  });

  it("heartbeats a long recovery for only its active attempt and clears the timer after settlement", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-07-22T00:00:00.000Z"));
      const test = fixture({ heartbeatIntervalMs: 50 });
      const recovered = deferred<{ status: "idle" }>();
      test.recovery.recover.mockImplementationOnce(() => recovered.promise);
      const publish = vi.spyOn(test.state, "publishForAttempt");

      const starting = test.controller.start();
      await vi.advanceTimersByTimeAsync(51);
      expect(publish).toHaveBeenCalledWith(1, {
        message: "Reconciling interrupted source updates",
        phase: "checking-source",
        progress: null,
      });
      const heartbeatAt = test.state.getSnapshot().heartbeatAt;

      recovered.resolve({ status: "idle" });
      await expect(starting).resolves.toEqual({ ok: true });
      const callsAfterSettlement = publish.mock.calls.length;
      await vi.advanceTimersByTimeAsync(151);
      expect(publish).toHaveBeenCalledTimes(callsAfterSettlement);
      expect(test.state.getSnapshot().heartbeatAt).toBe(heartbeatAt);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cannot overwrite a newer bootstrap attempt with a stale recovery heartbeat", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-07-22T00:00:00.000Z"));
      const test = fixture({ heartbeatIntervalMs: 50 });
      const recovered = deferred<{ status: "idle" }>();
      test.recovery.recover.mockImplementationOnce(() => recovered.promise);
      const starting = test.controller.start();
      await Promise.resolve();

      const newerAttempt = test.state.begin("A newer bootstrap owns state", "preparing");
      const newerSnapshot = test.state.getSnapshot();
      await vi.advanceTimersByTimeAsync(151);
      expect(test.state.getSnapshot()).toEqual(newerSnapshot);
      expect(newerAttempt).toBe(2);

      recovered.resolve({ status: "idle" });
      await expect(starting).resolves.toMatchObject({ cancelled: true, ok: false });
    } finally {
      vi.useRealTimers();
    }
  });

  it("runs journal recovery before bootstrap and coalesces concurrent starts", async () => {
    const test = fixture();

    const first = test.controller.start();
    const second = test.controller.start();
    await expect(Promise.all([first, second])).resolves.toEqual([{ ok: true }, { ok: true }]);
    expect(test.trace).toEqual(["recover", "bootstrap"]);
    expect(test.recovery.recover).toHaveBeenCalledOnce();
    expect(test.bootstrap.start).toHaveBeenCalledOnce();
  });

  it("parks on a stable recovery failure and retries recovery before bootstrap", async () => {
    const test = fixture();
    test.recovery.recover.mockRejectedValueOnce(new Error("private /Users/person/source path"));

    await expect(test.controller.start()).resolves.toMatchObject({ ok: false });
    expect(test.bootstrap.start).not.toHaveBeenCalled();
    expect(test.state.getSnapshot()).toMatchObject({
      failure: "Source update recovery failed. Retry recovery or inspect the private desktop log.",
      status: "failed",
    });

    await expect(test.controller.retry()).resolves.toEqual({ ok: true });
    expect(test.recovery.recover).toHaveBeenCalledTimes(2);
    expect(test.bootstrap.start).toHaveBeenCalledOnce();
    expect(test.trace).toEqual(["recover", "bootstrap"]);
  });

  it("cancels active recovery without starting bootstrap", async () => {
    const test = fixture();
    const pending = deferred<never>();
    test.recovery.recover.mockImplementationOnce(() => pending.promise);
    test.recovery.cancel.mockImplementationOnce(() => {
      pending.reject(new DOMException("cancelled", "AbortError"));
      return true;
    });

    const starting = test.controller.start();
    await vi.waitFor(() => expect(test.recovery.recover).toHaveBeenCalledOnce(), { timeout: 15_000 });
    await expect(test.controller.cancel()).resolves.toBe(true);
    await expect(starting).resolves.toMatchObject({ cancelled: true, ok: false });
    expect(test.bootstrap.start).not.toHaveBeenCalled();
    expect(test.state.getSnapshot()).toMatchObject({ phase: "cancelled", status: "failed" });
  });

  it("does not overwrite an authoritative completed recovery when cancellation arrives late", async () => {
    const test = fixture();
    const recovered = deferred<{ status: "promoted" }>();
    test.recovery.recover.mockImplementationOnce(() => recovered.promise);

    const starting = test.controller.start();
    await vi.waitFor(() => expect(test.recovery.recover).toHaveBeenCalledOnce(), { timeout: 15_000 });
    const cancelling = test.controller.cancel();
    recovered.resolve({ status: "promoted" });

    await expect(starting).resolves.toEqual({ ok: true });
    await expect(cancelling).resolves.toBe(true);
    expect(test.bootstrap.start).toHaveBeenCalledOnce();
    expect(test.state.getSnapshot()).not.toMatchObject({ phase: "cancelled", status: "failed" });
  });

  it("aborts recovery preparation even before a coordinator operation becomes active", async () => {
    const test = fixture();
    test.recovery.cancel.mockReturnValueOnce(false);
    test.recovery.recover.mockImplementationOnce((signal: AbortSignal) => new Promise<never>((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    }));

    const starting = test.controller.start();
    await vi.waitFor(() => expect(test.recovery.recover).toHaveBeenCalledOnce(), { timeout: 15_000 });
    await expect(test.controller.cancel()).resolves.toBe(true);
    await expect(starting).resolves.toMatchObject({ cancelled: true, ok: false });
    expect(test.bootstrap.start).not.toHaveBeenCalled();
  });

  it("joins shared shutdown before checking retained lease safety", async () => {
    const test = fixture();

    await test.controller.shutdown(321);
    expect(test.bootstrap.shutdown).toHaveBeenCalledWith(321);
    expect(test.trace).toEqual(["shutdown", "safe-to-quit"]);
  });

  it("retries a transient retained-lease settlement failure on a later quit attempt", async () => {
    const test = fixture();

    test.recovery.settleForQuit.mockRejectedValueOnce(
      new Error("source operation lease remains held"),
    );
    await expect(test.controller.shutdown(321)).rejects.toThrow(/lease remains held/i);
    await expect(test.controller.shutdown(321)).resolves.toBeUndefined();
    expect(test.recovery.settleForQuit).toHaveBeenCalledTimes(2);
  });

  it("bounds each quit attempt and allows a later retry after recovery settles", async () => {
    vi.useFakeTimers();
    try {
      const test = fixture();
      const recovered = deferred<{ status: "promoted" }>();
      test.recovery.recover.mockImplementationOnce(() => recovered.promise);
      const starting = test.controller.start();
      await vi.waitFor(() => expect(test.recovery.recover).toHaveBeenCalledOnce(), { timeout: 15_000 });

      const firstShutdown = test.controller.shutdown(25);
      const firstRejection = expect(firstShutdown).rejects.toThrow(/recovery did not settle/i);
      await vi.advanceTimersByTimeAsync(26);
      await firstRejection;

      recovered.resolve({ status: "promoted" });
      await starting;
      await expect(test.controller.shutdown(25)).resolves.toBeUndefined();
      expect(test.recovery.settleForQuit).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });
});
