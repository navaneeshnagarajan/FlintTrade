import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyShellUpdate,
  applySourceUpdate,
  cancelBootstrap,
  checkShellUpdate,
  checkSourceUpdate,
  getBackendState,
  getBootstrapSnapshot,
  getUpdateState,
  hideDesktopWindow,
  isDesktopShell,
  onBackendEvent,
  onBootstrapEvent,
  onUpdateProgress,
  openExternalUrl,
  quitAfterBackendFailure,
  quitDesktopApp,
  retryBootstrap,
  showDesktopWindow,
  type FlintDesktopApi,
} from "./desktopShell";

function update(kind: "source" | "shell") {
  return {
    attempt: 1,
    currentVersion: kind === "source" ? "a".repeat(40) : "0.6.0-beta.13",
    failure: null,
    heartbeatAt: 1,
    kind,
    message: "Ready",
    progress: null,
    status: "available" as const,
    version: kind === "source" ? "b".repeat(40) : "0.6.0-beta.14",
  };
}

function bridge(): FlintDesktopApi {
  const source = update("source");
  const shell = update("shell");
  return {
    applyShellUpdate: vi.fn().mockResolvedValue(shell),
    applySourceUpdate: vi.fn().mockResolvedValue(source),
    cancelBootstrap: vi.fn().mockResolvedValue(true),
    checkShellUpdate: vi.fn().mockResolvedValue(shell),
    checkSourceUpdate: vi.fn().mockResolvedValue(source),
    getBackendState: vi.fn().mockResolvedValue({ port: 3123, status: "ready", url: "http://127.0.0.1:3123" }),
    getBootstrapSnapshot: vi.fn().mockResolvedValue({
      attempt: 1,
      failure: null,
      heartbeatAt: 1,
      message: "Ready",
      phase: "complete",
      progress: 100,
      status: "ready",
    }),
    getUpdateState: vi.fn().mockImplementation((kind) => Promise.resolve(kind === "source" ? source : shell)),
    onBackendEvent: vi.fn().mockReturnValue(vi.fn()),
    onBootstrapEvent: vi.fn().mockReturnValue(vi.fn()),
    onUpdateProgress: vi.fn().mockReturnValue(vi.fn()),
    openExternal: vi.fn().mockResolvedValue(undefined),
    quitAfterBackendFailure: vi.fn().mockResolvedValue(undefined),
    retryBootstrap: vi.fn().mockResolvedValue(true),
    window: {
      hide: vi.fn().mockResolvedValue(undefined),
      quit: vi.fn().mockResolvedValue(undefined),
      show: vi.fn().mockResolvedValue(undefined),
    },
  };
}

describe("desktopShell", () => {
  afterEach(() => {
    delete window.flintDesktop;
    vi.restoreAllMocks();
  });

  it("reports a plain browser when the named Electron bridge is absent", () => {
    expect(isDesktopShell()).toBe(false);
  });

  it("falls back to window.open outside the shell", async () => {
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    await openExternalUrl("https://broker.example/approve");
    expect(openSpy).toHaveBeenCalledWith("https://broker.example/approve", "_blank", "noopener");
  });

  it("routes external URLs through the named Electron bridge inside the shell", async () => {
    const api = bridge();
    window.flintDesktop = api;
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);

    expect(isDesktopShell()).toBe(true);
    await openExternalUrl("https://broker.example/approve");

    expect(api.openExternal).toHaveBeenCalledWith("https://broker.example/approve");
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("rejects desktop-only named methods outside the shell", async () => {
    await expect(getUpdateState("source")).rejects.toThrow(/bridge is unavailable outside the desktop app/i);
    await expect(checkSourceUpdate()).rejects.toThrow(/bridge is unavailable outside the desktop app/i);
  });

  it("forwards every state and action helper to its named bridge method", async () => {
    const api = bridge();
    window.flintDesktop = api;

    await getBootstrapSnapshot();
    await retryBootstrap();
    await cancelBootstrap();
    await getBackendState();
    await getUpdateState("source");
    await checkSourceUpdate();
    await applySourceUpdate();
    await checkShellUpdate();
    await applyShellUpdate();
    await quitAfterBackendFailure();
    await hideDesktopWindow();
    await showDesktopWindow();
    await quitDesktopApp();

    expect(api.getBootstrapSnapshot).toHaveBeenCalledOnce();
    expect(api.retryBootstrap).toHaveBeenCalledOnce();
    expect(api.cancelBootstrap).toHaveBeenCalledOnce();
    expect(api.getBackendState).toHaveBeenCalledOnce();
    expect(api.getUpdateState).toHaveBeenCalledWith("source");
    expect(api.checkSourceUpdate).toHaveBeenCalledOnce();
    expect(api.applySourceUpdate).toHaveBeenCalledOnce();
    expect(api.checkShellUpdate).toHaveBeenCalledOnce();
    expect(api.applyShellUpdate).toHaveBeenCalledOnce();
    expect(api.quitAfterBackendFailure).toHaveBeenCalledOnce();
    expect(api.window.hide).toHaveBeenCalledOnce();
    expect(api.window.show).toHaveBeenCalledOnce();
    expect(api.window.quit).toHaveBeenCalledOnce();
  });

  it("forwards typed subscriptions and returns their unsubscribe closures", () => {
    const api = bridge();
    window.flintDesktop = api;
    const bootstrapListener = vi.fn();
    const backendListener = vi.fn();
    const updateListener = vi.fn();

    const unsubscribeBootstrap = onBootstrapEvent(bootstrapListener);
    const unsubscribeBackend = onBackendEvent(backendListener);
    const unsubscribeUpdate = onUpdateProgress(updateListener);

    expect(api.onBootstrapEvent).toHaveBeenCalledWith(bootstrapListener);
    expect(api.onBackendEvent).toHaveBeenCalledWith(backendListener);
    expect(api.onUpdateProgress).toHaveBeenCalledWith(updateListener);
    expect(unsubscribeBootstrap).toEqual(expect.any(Function));
    expect(unsubscribeBackend).toEqual(expect.any(Function));
    expect(unsubscribeUpdate).toEqual(expect.any(Function));
  });
});
