import { describe, expect, it, vi } from "vitest";

import { createDesktopLifecycle } from "./lifecycle";

function fixture() {
  const app = { quit: vi.fn() };
  const window = {
    focus: vi.fn(),
    hide: vi.fn(),
    isDestroyed: vi.fn(() => false),
    isMinimised: vi.fn(() => true),
    restore: vi.fn(),
    show: vi.fn(),
  };
  const drain = vi.fn<() => Promise<void>>(async () => undefined);
  const lifecycle = createDesktopLifecycle({ app, drain, getWindow: () => window });
  return { app, drain, lifecycle, window };
}

describe("desktop lifecycle", () => {
  it("hides a normal close only when at least one restore path is available", () => {
    const test = fixture();
    const event = { preventDefault: vi.fn() };
    test.lifecycle.setRestoreCapabilities({ hotkey: true, tray: false });

    test.lifecycle.handleWindowClose(event);
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(test.window.hide).toHaveBeenCalledOnce();
    expect(test.drain).not.toHaveBeenCalled();
  });

  it("turns an inaccessible close into a real drained quit", async () => {
    const test = fixture();
    const event = { preventDefault: vi.fn() };
    test.lifecycle.setRestoreCapabilities({ hotkey: false, tray: false });

    test.lifecycle.handleWindowClose(event);
    await test.lifecycle.settle();
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(test.window.hide).not.toHaveBeenCalled();
    expect(test.drain).toHaveBeenCalledOnce();
    expect(test.app.quit).toHaveBeenCalledOnce();
  });

  it("coalesces explicit and before-quit requests behind one asynchronous drain", async () => {
    let release!: () => void;
    const test = fixture();
    test.drain.mockImplementation(() => new Promise<void>((resolve) => { release = resolve; }));
    const firstEvent = { preventDefault: vi.fn() };
    const secondEvent = { preventDefault: vi.fn() };

    const requested = test.lifecycle.requestQuit("tray");
    test.lifecycle.handleBeforeQuit(firstEvent);
    test.lifecycle.handleBeforeQuit(secondEvent);
    expect(firstEvent.preventDefault).toHaveBeenCalledOnce();
    expect(secondEvent.preventDefault).toHaveBeenCalledOnce();
    expect(test.drain).toHaveBeenCalledOnce();
    release();
    await requested;
    expect(test.app.quit).toHaveBeenCalledOnce();
  });

  it("keeps quit fail-closed after drain failure and permits a later retry", async () => {
    const test = fixture();
    test.drain.mockRejectedValueOnce(new Error("tree unresolved"));

    await expect(test.lifecycle.requestQuit("failure")).rejects.toThrow("tree unresolved");
    expect(test.app.quit).not.toHaveBeenCalled();
    await expect(test.lifecycle.requestQuit("retry")).resolves.toBeUndefined();
    expect(test.app.quit).toHaveBeenCalledOnce();
  });

  it("shows, restores and focuses for second-instance and macOS activation", () => {
    const test = fixture();
    test.lifecycle.handleSecondInstance();
    test.lifecycle.handleActivate();
    expect(test.window.show).toHaveBeenCalledTimes(2);
    expect(test.window.restore).toHaveBeenCalledTimes(2);
    expect(test.window.focus).toHaveBeenCalledTimes(2);
  });

  it("requests a real quit when the backend has failed", async () => {
    const test = fixture();
    const event = { preventDefault: vi.fn() };
    test.lifecycle.markBackendFailed();

    test.lifecycle.handleWindowClose(event);
    await test.lifecycle.settle();
    expect(test.window.hide).not.toHaveBeenCalled();
    expect(test.app.quit).toHaveBeenCalledOnce();
  });

  it("restores close-to-tray after a failed backend retry becomes ready", () => {
    const test = fixture();
    const event = { preventDefault: vi.fn() };
    test.lifecycle.setRestoreCapabilities({ hotkey: true, tray: true });
    test.lifecycle.markBackendFailed();
    test.lifecycle.markBackendReady();

    test.lifecycle.handleWindowClose(event);

    expect(test.window.hide).toHaveBeenCalledOnce();
    expect(test.drain).not.toHaveBeenCalled();
  });
});
