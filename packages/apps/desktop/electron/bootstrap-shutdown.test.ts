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
});
