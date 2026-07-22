import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import type { BackendDrainResult } from "./backend-drain";
import { createBackendRuntime, type RuntimeRunningBackend } from "./backend-runtime";
import { createDesktopLifecycle } from "./lifecycle";
import { SourceOperationLeaseRetentionError } from "./source-operation";
import { createBackendState } from "./state";

const ACTIVE_SOURCE = path.resolve("/managed/FlintTrade");

const CLEAN: BackendDrainResult = {
  childExited: true,
  containmentExited: true,
  outcome: "clean",
  phase: "graceful",
  proof: "cleanup-complete",
  recordRemovalSafe: true,
};

function running(result: BackendDrainResult | Error = CLEAN): RuntimeRunningBackend {
  return {
    applicationPid: 9001,
    attempt: 1,
    drain: vi.fn(async () => {
      if (result instanceof Error) throw result;
      return result;
    }),
    guardianPid: 8001,
    launchToken: "a".repeat(64),
    port: 51_000,
    recordPath: "/managed/workspace/desktop_backend.pid",
    url: "http://127.0.0.1:51000",
  };
}

function fixture(input: {
  cancelCurrent?: () => Promise<void>;
  getState?: () => { stoppedSafe: boolean };
  onFailure?: (error: Error) => Promise<void> | void;
  onReady?: (backend: RuntimeRunningBackend) => Promise<void> | void;
  onStopped?: () => Promise<void> | void;
  start?: () => Promise<RuntimeRunningBackend>;
} = {}) {
  const backend = running();
  const supervisor = {
    cancelCurrent: vi.fn(input.cancelCurrent ?? (async () => undefined)),
    getState: input.getState ?? (() => ({ stoppedSafe: true })),
    start: vi.fn(input.start ?? (async () => backend)),
  };
  const state = createBackendState();
  const runtime = createBackendRuntime({
    activeSource: ACTIVE_SOURCE,
    ...(input.onFailure ? { onFailure: input.onFailure } : {}),
    ...(input.onReady ? { onReady: input.onReady } : {}),
    ...(input.onStopped ? { onStopped: input.onStopped } : {}),
    state,
    supervisor,
  });
  return { backend, runtime, state, supervisor };
}

describe("backend runtime authority adapter", () => {
  it("publishes only a supervisor-health-proved loopback origin", async () => {
    const onReady = vi.fn();
    const test = fixture({ onReady });

    await expect(test.runtime.start()).resolves.toBe(test.backend);
    expect(onReady).toHaveBeenCalledWith(test.backend);
    expect(test.state.getSnapshot()).toEqual({
      port: 51_000,
      status: "ready",
      url: "http://127.0.0.1:51000",
    });
  });

  it.each(["contained", "unresolved"] as const)(
    "never authorises Electron quit for a %s drain without exact proof",
    async (outcome) => {
      const onFailure = vi.fn();
      const unsafe = running({
        childExited: outcome === "contained",
        containmentExited: outcome === "contained",
        outcome,
        phase: "containment",
        proof: null,
        recordRemovalSafe: false,
      });
      const test = fixture({ onFailure, start: async () => unsafe });
      await test.runtime.start();
      const app = { quit: vi.fn() };
      const lifecycle = createDesktopLifecycle({
        app,
        drain: test.runtime.drainForQuit,
        getWindow: () => null,
      });

      await expect(lifecycle.requestQuit("tray")).rejects.toBeInstanceOf(SourceOperationLeaseRetentionError);
      expect(app.quit).not.toHaveBeenCalled();
      expect(test.state.getSnapshot().status).toBe("failed");
      expect(onFailure).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringMatching(/ambiguous/) }));
    },
  );

  it("allows quit only after clean proof, child exit and managed record finalisation", async () => {
    const test = fixture();
    await test.runtime.start();
    const app = { quit: vi.fn() };
    const lifecycle = createDesktopLifecycle({ app, drain: test.runtime.drainForQuit, getWindow: () => null });

    await expect(lifecycle.requestQuit("tray")).resolves.toBeUndefined();

    expect(app.quit).toHaveBeenCalledOnce();
    expect(test.state.getSnapshot().status).toBe("stopped");
  });

  it("revokes ready state immediately on an unexpected backend exit", async () => {
    const onFailure = vi.fn();
    const test = fixture({ onFailure });
    await test.runtime.start();

    test.runtime.markUnexpectedExit();

    expect(test.state.getSnapshot()).toEqual({ port: null, status: "failed", url: null });
    expect(onFailure).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringMatching(/unexpectedly/) }));
  });

  it("settles exact unexpected-exit cleanup before starting a retry", async () => {
    const first = running();
    const second = { ...running(), attempt: 2, port: 52_000, url: "http://127.0.0.1:52000" };
    const start = vi.fn()
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    const test = fixture({ start });
    await test.runtime.start();
    test.runtime.markUnexpectedExit();

    await expect(test.runtime.start()).resolves.toBe(second);

    expect(first.drain).toHaveBeenCalledOnce();
    expect(start).toHaveBeenCalledTimes(2);
    expect(test.state.getSnapshot()).toEqual({
      port: 52_000,
      status: "ready",
      url: "http://127.0.0.1:52000",
    });
  });

  it("cancels and settles a pre-ready guardian before quit can proceed", async () => {
    let rejectStart!: (error: Error) => void;
    const stoppedSafe = { value: false };
    const start = vi.fn(() => new Promise<RuntimeRunningBackend>((_resolve, reject) => {
      rejectStart = reject;
    }));
    const failure = Object.assign(new Error("cancelled"), { stoppedSafe: true });
    const test = fixture({
      cancelCurrent: async () => {
        stoppedSafe.value = true;
        rejectStart(failure);
      },
      getState: () => ({ stoppedSafe: stoppedSafe.value }),
      start,
    });
    const starting = test.runtime.start();
    const rejected = expect(starting).rejects.toBe(failure);

    await expect(test.runtime.drainForQuit()).resolves.toBeUndefined();
    await rejected;

    expect(test.supervisor.cancelCurrent).toHaveBeenCalledOnce();
    expect(test.state.getSnapshot().status).toBe("failed");
  });

  it("drains exact cleanup when readiness wins the startup-cancel race", async () => {
    const backend = running();
    let resolveStart!: (value: RuntimeRunningBackend) => void;
    const start = vi.fn(() => new Promise<RuntimeRunningBackend>((resolve) => {
      resolveStart = resolve;
    }));
    const test = fixture({
      cancelCurrent: async () => resolveStart(backend),
      getState: () => ({ stoppedSafe: false }),
      start,
    });
    const starting = test.runtime.start();

    await expect(test.runtime.cancelStarting()).resolves.toBe(true);
    await expect(starting).resolves.toBe(backend);

    expect(backend.drain).toHaveBeenCalledOnce();
    expect(test.state.getSnapshot().status).toBe("stopped");
  });

  it("does not launch a successor when quit cancels retry during prior exact cleanup", async () => {
    let finishDrain!: (value: BackendDrainResult) => void;
    const prior = running();
    vi.mocked(prior.drain).mockImplementation(() => new Promise<BackendDrainResult>((resolve) => {
      finishDrain = resolve;
    }));
    const successor = running();
    const test = fixture({ start: vi.fn()
      .mockResolvedValueOnce(prior)
      .mockResolvedValueOnce(successor) });
    await test.runtime.start();
    test.runtime.markUnexpectedExit();
    const retrying = test.runtime.start();
    const retryRejected = expect(retrying).rejects.toMatchObject({ stoppedSafe: true });
    const quitting = test.runtime.drainForQuit();
    finishDrain(CLEAN);

    await retryRejected;
    await expect(quitting).resolves.toBeUndefined();

    expect(test.supervisor.start).toHaveBeenCalledOnce();
    expect(test.state.getSnapshot().status).toBe("failed");
  });

  it("publishes source-updater stopped proof immediately after a safe drain", async () => {
    const onStopped = vi.fn();
    const test = fixture({ onStopped });
    await test.runtime.start();
    const order: string[] = [];
    vi.mocked(test.backend.drain).mockImplementation(async () => {
      order.push("drain");
      return CLEAN;
    });

    await test.runtime.sourceLifecycle.drainCurrent({
      onBackendStopped: () => order.push("stopped"),
      signal: new AbortController().signal,
    });

    expect(order).toEqual(["drain", "stopped"]);
    expect(onStopped).toHaveBeenCalledOnce();
  });

  it("keeps process authority independent from fallible window observers", async () => {
    const test = fixture({
      onReady: () => { throw new Error("renderer unavailable"); },
      onStopped: async () => { throw new Error("recovery window unavailable"); },
    });

    await expect(test.runtime.start()).resolves.toBe(test.backend);
    await expect(test.runtime.drainForQuit()).resolves.toBeUndefined();
    expect(test.state.getSnapshot().status).toBe("stopped");
  });

  it("finishes a drain and publishes stopped proof when cancellation arrives in flight", async () => {
    const controller = new AbortController();
    let finish!: (value: BackendDrainResult) => void;
    const pending = new Promise<BackendDrainResult>((resolve) => { finish = resolve; });
    const backend = running();
    vi.mocked(backend.drain).mockImplementation(() => pending);
    const test = fixture({ start: async () => backend });
    await test.runtime.start();
    const stopped = vi.fn();

    const draining = test.runtime.sourceLifecycle.drainCurrent({
      onBackendStopped: stopped,
      signal: controller.signal,
    });
    controller.abort(new DOMException("cancelled", "AbortError"));
    finish(CLEAN);

    await expect(draining).rejects.toMatchObject({ name: "AbortError" });
    expect(stopped).toHaveBeenCalledOnce();
  });

  it("returns false and reports stopped only for a start failure carrying exact safe proof", async () => {
    const failure = Object.assign(new Error("pre-spawn failure"), { stoppedSafe: true });
    const test = fixture({ start: async () => { throw failure; } });
    const stopped = vi.fn();

    await expect(test.runtime.sourceLifecycle.bootActive({
      activePath: ACTIVE_SOURCE,
      onBackendStopped: stopped,
    })).resolves.toBe(false);

    expect(stopped).toHaveBeenCalledOnce();
  });

  it("retains process-exit authority when a failed start lacks stopped proof", async () => {
    const failure = Object.assign(new Error("guardian cleanup unresolved"), { stoppedSafe: false });
    const test = fixture({ start: async () => { throw failure; } });
    const stopped = vi.fn();

    await expect(test.runtime.sourceLifecycle.bootActive({
      activePath: ACTIVE_SOURCE,
      onBackendStopped: stopped,
    })).rejects.toMatchObject({
      name: "SourceOperationLeaseRetentionError",
      retentionPolicy: "process-exit-required",
    });
    expect(stopped).not.toHaveBeenCalled();
  });

  it("rejects a foreign active path before invoking the supervisor", async () => {
    const test = fixture();

    await expect(test.runtime.sourceLifecycle.bootActive({
      activePath: path.resolve("/foreign/FlintTrade"),
      onBackendStopped: vi.fn(),
    })).rejects.toThrow(/exact managed active source/i);
    expect(test.supervisor.start).not.toHaveBeenCalled();
  });
});
