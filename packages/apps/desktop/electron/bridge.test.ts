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

  it("returns unsubscribe closures for bootstrap and update events", () => {
    const fake = fakeIpcRenderer();
    const api = createFlintDesktopApi(fake.ipc);
    const bootstrapListener = vi.fn();
    const updateListener = vi.fn();

    const unsubscribeBootstrap = api.onBootstrapEvent(bootstrapListener);
    const unsubscribeUpdate = api.onUpdateProgress(updateListener);
    fake.emit(IPC_CHANNELS.bootstrap.event, { status: "running" });
    fake.emit(IPC_CHANNELS.update.event, { status: "checking" });

    expect(bootstrapListener).toHaveBeenCalledWith({ status: "running" });
    expect(updateListener).toHaveBeenCalledWith({ status: "checking" });

    const bootstrapRegistration = fake.ipc.on.mock.calls[0];
    const updateRegistration = fake.ipc.on.mock.calls[1];
    expect(bootstrapRegistration).toBeDefined();
    expect(updateRegistration).toBeDefined();

    unsubscribeBootstrap();
    expect(fake.ipc.removeListener).toHaveBeenNthCalledWith(
      1,
      IPC_CHANNELS.bootstrap.event,
      bootstrapRegistration?.[1],
    );
    fake.emit(IPC_CHANNELS.bootstrap.event, { status: "ready" });
    fake.emit(IPC_CHANNELS.update.event, { status: "available" });
    expect(bootstrapListener).toHaveBeenCalledOnce();
    expect(updateListener).toHaveBeenCalledTimes(2);

    unsubscribeUpdate();
    expect(fake.ipc.removeListener).toHaveBeenNthCalledWith(2, IPC_CHANNELS.update.event, updateRegistration?.[1]);
    fake.emit(IPC_CHANNELS.bootstrap.event, { status: "ready" });
    fake.emit(IPC_CHANNELS.update.event, { status: "complete" });
    expect(bootstrapListener).toHaveBeenCalledOnce();
    expect(updateListener).toHaveBeenCalledTimes(2);
  });
});
