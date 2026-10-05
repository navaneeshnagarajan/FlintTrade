import { describe, expect, it, vi } from "vitest";

import { createFlintDesktopApi } from "./bridge";
import { IPC_CHANNELS } from "./ipc-channels";

function fakeIpcRenderer() {
  const listeners = new Map<string, (...args: unknown[]) => void>();
  const ipc = {
    invoke: vi.fn(async () => undefined),
    on: vi.fn((channel: string, listener: (...args: unknown[]) => void) => {
      listeners.set(channel, listener);
      return ipc;
    }),
    removeListener: vi.fn((channel: string, listener: (...args: unknown[]) => void) => {
      if (listeners.get(channel) === listener) listeners.delete(channel);
      return ipc;
    }),
  };
  return {
    ipc,
    emit(channel: string, payload: unknown) {
      listeners.get(channel)?.({ sender: "main" }, payload);
    },
  };
}

describe("window.flintDesktop bridge", () => {
  it("uses named channels without exposing ipcRenderer", async () => {
    const fake = fakeIpcRenderer();
    const api = createFlintDesktopApi(fake.ipc);

    await api.getBootstrapSnapshot();
    await api.checkSourceUpdate();
    await api.window.show();

    expect(fake.ipc.invoke).toHaveBeenNthCalledWith(1, IPC_CHANNELS.bootstrap.get);
    expect(fake.ipc.invoke).toHaveBeenNthCalledWith(2, IPC_CHANNELS.update.checkSource);
    expect(fake.ipc.invoke).toHaveBeenNthCalledWith(3, IPC_CHANNELS.window.show);
    expect(api).not.toHaveProperty("ipcRenderer");
    expect(api).not.toHaveProperty("invoke");
  });

  it("returns unsubscribe closures for backend, bootstrap and update events", () => {
    const fake = fakeIpcRenderer();
    const api = createFlintDesktopApi(fake.ipc);
    const bootstrapListener = vi.fn();
    const backendListener = vi.fn();
    const updateListener = vi.fn();

    const unsubscribeBackend = api.onBackendEvent(backendListener);
    const unsubscribeBootstrap = api.onBootstrapEvent(bootstrapListener);
    const unsubscribeUpdate = api.onUpdateProgress(updateListener);
    fake.emit(IPC_CHANNELS.backend.event, { status: "starting" });
    fake.emit(IPC_CHANNELS.bootstrap.event, { status: "running" });
    fake.emit(IPC_CHANNELS.update.event, { status: "checking" });

    expect(backendListener).toHaveBeenCalledWith({ status: "starting" });
    expect(bootstrapListener).toHaveBeenCalledWith({ status: "running" });
    expect(updateListener).toHaveBeenCalledWith({ status: "checking" });

    const backendRegistration = fake.ipc.on.mock.calls[0];
    const bootstrapRegistration = fake.ipc.on.mock.calls[1];
    const updateRegistration = fake.ipc.on.mock.calls[2];
    expect(backendRegistration).toBeDefined();
    expect(bootstrapRegistration).toBeDefined();
    expect(updateRegistration).toBeDefined();

    unsubscribeBackend();
    expect(fake.ipc.removeListener).toHaveBeenNthCalledWith(
      1,
      IPC_CHANNELS.backend.event,
      backendRegistration?.[1],
    );
    unsubscribeBootstrap();
    expect(fake.ipc.removeListener).toHaveBeenNthCalledWith(
      2,
      IPC_CHANNELS.bootstrap.event,
      bootstrapRegistration?.[1],
    );
    fake.emit(IPC_CHANNELS.bootstrap.event, { status: "ready" });
    fake.emit(IPC_CHANNELS.update.event, { status: "available" });
    expect(bootstrapListener).toHaveBeenCalledOnce();
    expect(updateListener).toHaveBeenCalledTimes(2);

    unsubscribeUpdate();
    expect(fake.ipc.removeListener).toHaveBeenNthCalledWith(3, IPC_CHANNELS.update.event, updateRegistration?.[1]);
    fake.emit(IPC_CHANNELS.bootstrap.event, { status: "ready" });
    fake.emit(IPC_CHANNELS.update.event, { status: "complete" });
    expect(bootstrapListener).toHaveBeenCalledOnce();
    expect(updateListener).toHaveBeenCalledTimes(2);
  });
});

describe("desktop runtime inventory", () => {
  it("copies and freezes only allowlisted version strings without IPC", () => {
    const fake = fakeIpcRenderer();
    const versions = { electron: "44.4.1", chrome: "151.0.0.0", node: "24.19.0", v8: "15.1.1", secret: "do-not-expose" };
    const api = createFlintDesktopApi(fake.ipc, versions);
    expect(api.runtimeVersions).toEqual({ electron: "44.4.1", chrome: "151.0.0.0", node: "24.19.0", v8: "15.1.1" });
    versions.node = "changed";
    expect(api.runtimeVersions?.node).toBe("24.19.0");
    expect(Object.isFrozen(api.runtimeVersions)).toBe(true);
    expect(fake.ipc.invoke).not.toHaveBeenCalled();
  });

  it("omits invalid metadata rather than exposing arbitrary strings", () => {
    const api = createFlintDesktopApi(fakeIpcRenderer().ipc, { node: "/private/path", electron: "x".repeat(200), chrome: "151.0.0.0", v8: "15.1.0-electron.0" });
    expect(api.runtimeVersions).toEqual({ node: null, electron: null, chrome: "151.0.0.0", v8: "15.1.0-electron.0" });
  });
});
