import { describe, expect, it, vi } from "vitest";

import { createSourceOperationCoordinator } from "./source-operation";

describe("source operation coordinator", () => {
  it("runs bootstrap, check and apply in FIFO order without overlap", async () => {
    const coordinator = createSourceOperationCoordinator();
    const order: string[] = [];
    let releaseFirst!: () => void;
    const firstGate = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    const first = coordinator.run("bootstrap", undefined, async () => {
      order.push("bootstrap:start");
      await firstGate;
      order.push("bootstrap:end");
      return 1;
    });
    const second = coordinator.run("update-check", undefined, async () => {
      order.push("check:start");
      order.push("check:end");
      return 2;
    });
    const third = coordinator.run("update-apply", undefined, async () => {
      order.push("apply:start");
      order.push("apply:end");
      return 3;
    });

    await vi.waitFor(() => expect(coordinator.getSnapshot()).toMatchObject({ active: "bootstrap", queued: 2 }));
    expect(order).toEqual(["bootstrap:start"]);
    releaseFirst();
    await expect(Promise.all([first, second, third])).resolves.toEqual([1, 2, 3]);
    expect(order).toEqual([
      "bootstrap:start",
      "bootstrap:end",
      "check:start",
      "check:end",
      "apply:start",
      "apply:end",
    ]);
  });

  it("removes a cancelled queued operation without disturbing the active operation", async () => {
    const coordinator = createSourceOperationCoordinator();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const active = coordinator.run("bootstrap", undefined, async () => gate);
    const abort = new AbortController();
    const queued = coordinator.run("update-check", abort.signal, async () => "unexpected");
    abort.abort();

    await expect(queued).rejects.toMatchObject({ name: "AbortError" });
    expect(coordinator.getSnapshot()).toMatchObject({ active: "bootstrap", queued: 0 });
    release();
    await active;
  });

  it("aborts active work, rejects queued work and permanently latches shutdown", async () => {
    const coordinator = createSourceOperationCoordinator();
    const active = coordinator.run("update-apply", undefined, async (signal) => {
      await new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    });
    const queued = coordinator.run("bootstrap", undefined, async () => undefined);

    await coordinator.shutdown();
    await expect(active).rejects.toMatchObject({ name: "AbortError" });
    await expect(queued).rejects.toThrow(/shutting down/i);
    await expect(coordinator.run("update-check", undefined, async () => undefined)).rejects.toThrow(/shutting down/i);
    expect(coordinator.getSnapshot()).toEqual({ active: null, queued: 0, shuttingDown: true });
  });

  it("fails closed when active work ignores shutdown", async () => {
    vi.useFakeTimers();
    try {
      const coordinator = createSourceOperationCoordinator();
      void coordinator.run("update-apply", undefined, async () => new Promise(() => {}));
      const shutdown = coordinator.shutdown(25);
      const rejection = expect(shutdown).rejects.toThrow(/did not settle/i);
      await vi.advanceTimersByTimeAsync(26);
      await rejection;
    } finally {
      vi.useRealTimers();
    }
  });

  it("allows a later bounded shutdown wait after the original operation settles", async () => {
    vi.useFakeTimers();
    try {
      const coordinator = createSourceOperationCoordinator();
      let release!: () => void;
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      const active = coordinator.run("update-apply", undefined, async () => gate);

      const firstShutdown = coordinator.shutdown(25);
      const firstRejection = expect(firstShutdown).rejects.toThrow(/did not settle/i);
      await vi.advanceTimersByTimeAsync(26);
      await firstRejection;

      release();
      await active;
      await expect(coordinator.shutdown(25)).resolves.toBeUndefined();
      expect(coordinator.getSnapshot()).toEqual({ active: null, queued: 0, shuttingDown: true });
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears the active slot when a Promise-returning callback throws synchronously", async () => {
    const coordinator = createSourceOperationCoordinator();
    const synchronouslyThrowing = (() => {
      throw new Error("synchronous setup failure");
    }) as unknown as (signal: AbortSignal) => Promise<void>;

    await expect(coordinator.run("update-check", undefined, synchronouslyThrowing)).rejects.toThrow(
      "synchronous setup failure",
    );
    expect(coordinator.getSnapshot()).toEqual({ active: null, queued: 0, shuttingDown: false });
    await expect(
      coordinator.run("update-check", undefined, async () => "recovered"),
    ).resolves.toBe("recovered");
  });
});
