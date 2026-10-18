import path from "node:path";

import { describe, expect, it, vi } from "vitest";

import { createBackendRuntime } from "./backend-runtime";
import { createStartupRecoveryController } from "./startup-recovery";
import { createBackendState, createBootstrapState } from "./state";

// Exercise the startup-controller/runtime composition used by main, with no
// Electron windows, operator processes, or external transports.
describe("recovered backend startup adoption", () => {
  it("does not confuse a completed journal outcome with a running backend", async () => {
    const controller = createStartupRecoveryController({
      bootstrap: { start: async () => ({ ok: true }), retry: async () => ({ ok: true }),
        cancel: async () => false, shutdown: async () => undefined },
      state: createBootstrapState(),
      recovery: { recover: async () => ({ status: "promoted" }), cancel: () => false,
        settleForQuit: async () => undefined },
    });
    expect(await controller.start()).toEqual({ ok: true });
  });
  it.each(["promoted", "rolled-back"] as const)("adopts %s recovery without a second launch", async (status) => {
    const backend = {
      applicationPid: 12, attempt: 1, guardianPid: 11, launchToken: "a".repeat(64), port: 51000,
      recordPath: "/fixture/record", url: "http://127.0.0.1:51000",
      drain: vi.fn(),
    };
    const supervisor = { cancelCurrent: vi.fn(), getState: () => ({ stoppedSafe: true }), start: vi.fn(async () => backend) };
    const runtime = createBackendRuntime({ activeSource: path.resolve("/fixture/source"), state: createBackendState(), supervisor });
    const bootstrap = {
      cancel: vi.fn(async () => false), retry: vi.fn(async () => ({ ok: true })),
      shutdown: vi.fn(), start: vi.fn(async () => ({ ok: true })),
    };
    const controller = createStartupRecoveryController({
      bootstrap, state: createBootstrapState(),
      recoveredBackend: runtime.getRunning,
      recovery: {
        cancel: () => false, settleForQuit: vi.fn(),
        recover: async () => {
          await runtime.sourceLifecycle.bootActive({ activePath: path.resolve("/fixture/source"), onBackendStopped: vi.fn() });
          return { status };
        },
      },
    });
    const result = await controller.start();
    expect(result.ok).toBe(true);
    expect(result).toMatchObject({ backendDisposition: "adopt-recovered" });
    await expect(runtime.startAfterBootstrap(result)).resolves.toBe(backend);
    expect(supervisor.start).toHaveBeenCalledTimes(1);
    expect(backend.drain).not.toHaveBeenCalled();
    await expect(runtime.startAfterBootstrap({
      ...result, recoveredBackend: { attempt: 2, launchToken: "b".repeat(64) },
    })).rejects.toThrow("explicit recovery");
    await expect(runtime.start()).rejects.toThrow("already running");
    runtime.markUnexpectedExit();
    await expect(runtime.startAfterBootstrap(result)).rejects.toThrow("explicit recovery");
    expect(supervisor.start).toHaveBeenCalledTimes(1);
  });
});
