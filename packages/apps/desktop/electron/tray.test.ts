import { describe, expect, it, vi } from "vitest";

import { createDesktopTray, type TrayCallbacks } from "./tray";

describe("desktop tray", () => {
  it("shows, toggles and marks quit intent before requesting quit", () => {
    let callbacks: TrayCallbacks | null = null;
    const order: string[] = [];
    const tray = createDesktopTray({
      create: vi.fn((value) => { callbacks = value; return { destroy: vi.fn() }; }),
      markQuitIntent: () => order.push("mark"),
      requestQuit: () => { order.push("quit"); },
      show: vi.fn(),
      toggle: vi.fn(),
    });

    expect(tray.start()).toBe(true);
    const activeCallbacks = callbacks as TrayCallbacks | null;
    activeCallbacks?.onShow();
    activeCallbacks?.onLeftClick("down");
    activeCallbacks?.onLeftClick("up");
    activeCallbacks?.onQuit();
    expect(tray.available()).toBe(true);
    expect(callbacks).not.toBeNull();
    expect(order).toEqual(["mark", "quit"]);
    tray.stop();
  });

  it("fails closed without advertising tray availability when creation fails", () => {
    const onFailure = vi.fn();
    const tray = createDesktopTray({
      create: vi.fn(() => { throw new Error("no tray"); }),
      markQuitIntent: vi.fn(),
      onFailure,
      requestQuit: vi.fn(),
      show: vi.fn(),
      toggle: vi.fn(),
    });

    expect(tray.start()).toBe(false);
    expect(tray.available()).toBe(false);
    expect(onFailure).toHaveBeenCalledOnce();
  });
});
