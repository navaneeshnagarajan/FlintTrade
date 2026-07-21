import { describe, expect, it, vi } from "vitest";

import { createBootstrapQuitGate } from "./bootstrap-shutdown";

describe("bootstrap quit settlement", () => {
  it("prevents the first app quit, awaits one idempotent settlement and then re-enters quit", async () => {
    let release!: () => void;
    const settlement = new Promise<void>((resolve) => {
      release = resolve;
    });
    const app = { quit: vi.fn() };
    const shutdown = vi.fn(() => settlement);
    const gate = createBootstrapQuitGate(app, { shutdown });
    const first = { preventDefault: vi.fn() };
    const second = { preventDefault: vi.fn() };

    gate.handleBeforeQuit(first);
    gate.handleBeforeQuit(second);
    expect(first.preventDefault).toHaveBeenCalledOnce();
    expect(second.preventDefault).toHaveBeenCalledOnce();
    expect(shutdown).toHaveBeenCalledOnce();
    expect(app.quit).not.toHaveBeenCalled();

    release();
    await gate.requestQuit();
    expect(app.quit).toHaveBeenCalledOnce();
    const reentry = { preventDefault: vi.fn() };
    gate.handleBeforeQuit(reentry);
    expect(reentry.preventDefault).not.toHaveBeenCalled();
  });

  it("routes IPC, bootstrap-failure and ordinary quit requests through the same settlement", async () => {
    const app = { quit: vi.fn() };
    const shutdown = vi.fn(async () => {});
    const gate = createBootstrapQuitGate(app, { shutdown });

    await Promise.all([gate.requestQuit(), gate.requestQuit(), gate.requestQuit()]);

    expect(shutdown).toHaveBeenCalledOnce();
    expect(app.quit).toHaveBeenCalledOnce();
  });

  it("keeps quit fail-closed when process containment cannot settle", async () => {
    const app = { quit: vi.fn() };
    const gate = createBootstrapQuitGate(app, {
      shutdown: vi.fn(async () => {
        throw new Error("containment failed");
      }),
    });

    await expect(gate.requestQuit()).rejects.toThrow("containment failed");
    expect(app.quit).not.toHaveBeenCalled();
    const retryEvent = { preventDefault: vi.fn() };
    gate.handleBeforeQuit(retryEvent);
    expect(retryEvent.preventDefault).toHaveBeenCalledOnce();
    expect(app.quit).not.toHaveBeenCalled();
  });

  it("supervises fail-closed quit requests from void startup callbacks", async () => {
    const app = { quit: vi.fn() };
    const gate = createBootstrapQuitGate(app, {
      shutdown: vi.fn(async () => {
        throw new Error("containment failed");
      }),
    });

    expect(gate.requestQuitFailClosed()).toBeUndefined();
    await new Promise((resolve) => setImmediate(resolve));

    expect(app.quit).not.toHaveBeenCalled();
  });
});
