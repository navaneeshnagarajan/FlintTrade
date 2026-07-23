import { beforeEach, describe, expect, it, vi } from "vitest";

const electron = vi.hoisted(() => ({
  contextBridge: {
    exposeInMainWorld: vi.fn(),
  },
  ipcRenderer: {
    invoke: vi.fn(async () => undefined),
    on: vi.fn(),
    removeListener: vi.fn(),
  },
}));

vi.mock("electron", () => electron);

describe("sandboxed preload", () => {
  beforeEach(() => {
    electron.contextBridge.exposeInMainWorld.mockClear();
  });

  it("exposes only the named flintDesktop capability surface", async () => {
    await import("./preload");

    expect(electron.contextBridge.exposeInMainWorld).toHaveBeenCalledOnce();
    const [name, api] = electron.contextBridge.exposeInMainWorld.mock.calls[0] ?? [];
    expect(name).toBe("flintDesktop");
    expect(api).toMatchObject({
      getBootstrapSnapshot: expect.any(Function),
      onBootstrapEvent: expect.any(Function),
      onBackendEvent: expect.any(Function),
      openExternal: expect.any(Function),
      window: expect.objectContaining({
        hide: expect.any(Function),
        quit: expect.any(Function),
        show: expect.any(Function),
      }),
    });
    expect(api).not.toHaveProperty("ipcRenderer");
    expect(api).not.toHaveProperty("invoke");
  });
});
