import { pathToFileURL } from "node:url";

import { describe, expect, it, vi } from "vitest";

import { ALL_IPC_CHANNELS } from "./ipc-channels";
import { registerDesktopIpc, type DesktopIpcServices } from "./ipc";
import type { IpcSenderEvent } from "./origins";

function services(): DesktopIpcServices {
  return {
    applyShellUpdate: vi.fn(),
    applySourceUpdate: vi.fn(),
    cancelBootstrap: vi.fn(),
    checkShellUpdate: vi.fn(),
    checkSourceUpdate: vi.fn(),
    getBackendState: vi.fn(),
    getBootstrapSnapshot: vi.fn(),
    getUpdateState: vi.fn(),
    hideWindow: vi.fn(),
    openExternal: vi.fn(),
    quit: vi.fn(),
    quitAfterBackendFailure: vi.fn(),
    retryBootstrap: vi.fn(),
    showWindow: vi.fn(),
  };
}

describe("desktop IPC registration", () => {
  it("registers every named channel behind sender validation", async () => {
    const handlers = new Map<string, (event: IpcSenderEvent, ...args: unknown[]) => Promise<unknown>>();
    const ipcMain = {
      handle: vi.fn((channel: string, handler: (event: IpcSenderEvent, ...args: unknown[]) => Promise<unknown>) => {
        handlers.set(channel, handler);
      }),
    };
    const desktopServices = services();
    registerDesktopIpc(ipcMain, {
      originPolicy: () => ({
        splashUrl: pathToFileURL("/app/splash/index.html").href,
        terminalOrigin: "http://127.0.0.1:43127",
      }),
      services: desktopServices,
    });

    expect([...handlers.keys()].sort()).toEqual([...ALL_IPC_CHANNELS].sort());

    for (const handler of handlers.values()) {
      await expect(handler({ senderFrame: { url: "https://attacker.example" } })).rejects.toThrowError(
        /untrusted IPC sender/i,
      );
    }

    for (const service of Object.values(desktopServices)) {
      expect(service).not.toHaveBeenCalled();
    }
  });
});
