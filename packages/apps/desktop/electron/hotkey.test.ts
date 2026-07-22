import { describe, expect, it, vi } from "vitest";

import { createGlobalHotkey } from "./hotkey";

describe("global desktop hotkey", () => {
  it("registers the exact toggle shortcut and unregisters it once", () => {
    let callback: (() => void) | null = null;
    const register = vi.fn((_accelerator: string, handler: () => void) => {
      callback = handler;
      return true;
    });
    const unregister = vi.fn();
    const toggle = vi.fn();
    const hotkey = createGlobalHotkey({ register, toggle, unregister });

    expect(hotkey.start()).toBe(true);
    expect(register).toHaveBeenCalledWith("CommandOrControl+Shift+F", expect.any(Function));
    (callback as (() => void) | null)?.();
    expect(toggle).toHaveBeenCalledOnce();
    hotkey.stop();
    hotkey.stop();
    expect(unregister).toHaveBeenCalledOnce();
    expect(unregister).toHaveBeenCalledWith("CommandOrControl+Shift+F");
  });

  it.each(["returned false", "threw"])("surfaces registration failure when the API %s", (mode) => {
    const onFailure = vi.fn();
    const unregister = vi.fn();
    const hotkey = createGlobalHotkey({
      onFailure,
      register: mode === "threw" ? vi.fn(() => { throw new Error("denied"); }) : vi.fn(() => false),
      toggle: vi.fn(),
      unregister,
    });

    expect(hotkey.start()).toBe(false);
    expect(hotkey.available()).toBe(false);
    expect(onFailure).toHaveBeenCalledOnce();
    hotkey.stop();
    expect(unregister).not.toHaveBeenCalled();
  });
});
