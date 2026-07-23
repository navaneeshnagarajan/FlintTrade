import { IPC_CHANNELS } from "./ipc-channels";
import { assertIpcSender, type IpcSenderEvent, type RendererOriginPolicy } from "./origins";
import type { BackendState, BootstrapSnapshot, UpdateKind, UpdateSnapshot } from "./state";

interface IpcMainLike {
  handle(
    channel: string,
    listener: (event: IpcSenderEvent, ...args: unknown[]) => Promise<unknown>,
  ): void;
}

export interface DesktopIpcServices {
  applyShellUpdate(): Promise<Readonly<UpdateSnapshot>> | Readonly<UpdateSnapshot>;
  applySourceUpdate(): Promise<Readonly<UpdateSnapshot>> | Readonly<UpdateSnapshot>;
  cancelBootstrap(): Promise<boolean> | boolean;
  checkShellUpdate(): Promise<Readonly<UpdateSnapshot>> | Readonly<UpdateSnapshot>;
  checkSourceUpdate(): Promise<Readonly<UpdateSnapshot>> | Readonly<UpdateSnapshot>;
  getBackendState(): Promise<Readonly<BackendState>> | Readonly<BackendState>;
  getBootstrapSnapshot(): Promise<Readonly<BootstrapSnapshot>> | Readonly<BootstrapSnapshot>;
  getUpdateState(kind: UpdateKind): Promise<Readonly<UpdateSnapshot>> | Readonly<UpdateSnapshot>;
  hideWindow(): Promise<void> | void;
  openExternal(url: string): Promise<void> | void;
  quit(): Promise<void> | void;
  quitAfterBackendFailure(): Promise<void> | void;
  retryBootstrap(): Promise<boolean> | boolean;
  showWindow(): Promise<void> | void;
}

export interface DesktopIpcOptions {
  originPolicy(): RendererOriginPolicy;
  services: DesktopIpcServices;
}

function updateKind(value: unknown): UpdateKind {
  if (value === "source" || value === "shell") return value;
  throw new TypeError("Update kind must be source or shell.");
}

function requiredString(value: unknown, name: string): string {
  if (typeof value !== "string" || value === "") throw new TypeError(`${name} is required.`);
  return value;
}

export function registerDesktopIpc(ipcMain: IpcMainLike, options: DesktopIpcOptions): void {
  const register = (channel: string, handler: (...args: unknown[]) => unknown): void => {
    ipcMain.handle(channel, async (event, ...args) => {
      assertIpcSender(event, options.originPolicy());
      return await handler(...args);
    });
  };

  register(IPC_CHANNELS.bootstrap.get, () => options.services.getBootstrapSnapshot());
  register(IPC_CHANNELS.bootstrap.retry, () => options.services.retryBootstrap());
  register(IPC_CHANNELS.bootstrap.cancel, () => options.services.cancelBootstrap());
  register(IPC_CHANNELS.backend.get, () => options.services.getBackendState());
  register(IPC_CHANNELS.update.get, (kind) => options.services.getUpdateState(updateKind(kind)));
  register(IPC_CHANNELS.update.checkSource, () => options.services.checkSourceUpdate());
  register(IPC_CHANNELS.update.applySource, () => options.services.applySourceUpdate());
  register(IPC_CHANNELS.update.checkShell, () => options.services.checkShellUpdate());
  register(IPC_CHANNELS.update.applyShell, () => options.services.applyShellUpdate());
  register(IPC_CHANNELS.external.open, (url) => options.services.openExternal(requiredString(url, "URL")));
  register(IPC_CHANNELS.lifecycle.quitAfterBackendFailure, () => options.services.quitAfterBackendFailure());
  register(IPC_CHANNELS.window.show, () => options.services.showWindow());
  register(IPC_CHANNELS.window.hide, () => options.services.hideWindow());
  register(IPC_CHANNELS.window.quit, () => options.services.quit());
}
