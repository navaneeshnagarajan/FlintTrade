import { afterEach, describe, expect, it, vi } from "vitest";

import { invokeDesktopCommand, isDesktopShell, openExternalUrl } from "./desktopShell";

type TauriWindow = Window & {
  __TAURI_INTERNALS__?: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
};

describe("desktopShell", () => {
  afterEach(() => {
    delete (window as TauriWindow).__TAURI_INTERNALS__;
    vi.restoreAllMocks();
  });

  it("reports a plain browser when the Tauri global is absent", () => {
    expect(isDesktopShell()).toBe(false);
  });

  it("falls back to window.open outside the shell", async () => {
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    await openExternalUrl("https://broker.example/approve");
    expect(openSpy).toHaveBeenCalledWith("https://broker.example/approve", "_blank", "noopener");
  });

  it("routes through the scoped opener command inside the shell", async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    (window as TauriWindow).__TAURI_INTERNALS__ = { invoke };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);

    expect(isDesktopShell()).toBe(true);
    await openExternalUrl("https://broker.example/approve");

    expect(invoke).toHaveBeenCalledWith("plugin:opener|open_url", {
      url: "https://broker.example/approve",
    });
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("rejects invokeDesktopCommand outside the shell", async () => {
    await expect(invokeDesktopCommand("updater_state")).rejects.toThrow(
      /unavailable outside the desktop app/,
    );
  });

  it("forwards invokeDesktopCommand to the shell and returns the payload", async () => {
    const invoke = vi.fn().mockResolvedValue({ app_version: "0.6.0-beta.1", src_dir: null });
    (window as TauriWindow).__TAURI_INTERNALS__ = { invoke };

    const state = await invokeDesktopCommand<{ app_version: string; src_dir: string | null }>(
      "updater_state",
    );

    expect(invoke).toHaveBeenCalledWith("updater_state", undefined);
    expect(state).toEqual({ app_version: "0.6.0-beta.1", src_dir: null });
  });
});
