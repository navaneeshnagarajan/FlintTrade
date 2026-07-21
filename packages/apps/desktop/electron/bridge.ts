// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import { IPC_CHANNELS } from "./ipc-channels";
import type { BackendState, BootstrapSnapshot, UpdateKind, UpdateSnapshot } from "./state";

interface IpcRendererLike {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>;
  on(channel: string, listener: (event: unknown, payload: unknown) => void): unknown;
  removeListener(channel: string, listener: (event: unknown, payload: unknown) => void): unknown;
}

export interface FlintDesktopApi {
  applyShellUpdate(): Promise<Readonly<UpdateSnapshot>>;
  applySourceUpdate(): Promise<Readonly<UpdateSnapshot>>;
  cancelBootstrap(): Promise<boolean>;
  checkShellUpdate(): Promise<Readonly<UpdateSnapshot>>;
  checkSourceUpdate(): Promise<Readonly<UpdateSnapshot>>;
  getBackendState(): Promise<Readonly<BackendState>>;
  getBootstrapSnapshot(): Promise<Readonly<BootstrapSnapshot>>;
  getUpdateState(kind: UpdateKind): Promise<Readonly<UpdateSnapshot>>;
  onBootstrapEvent(callback: (snapshot: Readonly<BootstrapSnapshot>) => void): () => void;
  onUpdateProgress(callback: (snapshot: Readonly<UpdateSnapshot>) => void): () => void;
  openExternal(url: string): Promise<void>;
  quitAfterBackendFailure(): Promise<void>;
  retryBootstrap(): Promise<boolean>;
  window: {
    hide(): Promise<void>;
    quit(): Promise<void>;
    show(): Promise<void>;
  };
}

function subscribe<T>(ipcRenderer: IpcRendererLike, channel: string, callback: (payload: T) => void): () => void {
  const listener = (_event: unknown, payload: unknown): void => callback(payload as T);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

export function createFlintDesktopApi(ipcRenderer: IpcRendererLike): FlintDesktopApi {
  const api: FlintDesktopApi = {
    applyShellUpdate: () => ipcRenderer.invoke(IPC_CHANNELS.update.applyShell) as Promise<Readonly<UpdateSnapshot>>,
    applySourceUpdate: () => ipcRenderer.invoke(IPC_CHANNELS.update.applySource) as Promise<Readonly<UpdateSnapshot>>,
    cancelBootstrap: () => ipcRenderer.invoke(IPC_CHANNELS.bootstrap.cancel) as Promise<boolean>,
    checkShellUpdate: () => ipcRenderer.invoke(IPC_CHANNELS.update.checkShell) as Promise<Readonly<UpdateSnapshot>>,
    checkSourceUpdate: () => ipcRenderer.invoke(IPC_CHANNELS.update.checkSource) as Promise<Readonly<UpdateSnapshot>>,
    getBackendState: () => ipcRenderer.invoke(IPC_CHANNELS.backend.get) as Promise<Readonly<BackendState>>,
    getBootstrapSnapshot: () =>
      ipcRenderer.invoke(IPC_CHANNELS.bootstrap.get) as Promise<Readonly<BootstrapSnapshot>>,
    getUpdateState: (kind: UpdateKind) =>
      ipcRenderer.invoke(IPC_CHANNELS.update.get, kind) as Promise<Readonly<UpdateSnapshot>>,
    onBootstrapEvent: (callback: (snapshot: Readonly<BootstrapSnapshot>) => void) =>
      subscribe(ipcRenderer, IPC_CHANNELS.bootstrap.event, callback),
    onUpdateProgress: (callback: (snapshot: Readonly<UpdateSnapshot>) => void) =>
      subscribe(ipcRenderer, IPC_CHANNELS.update.event, callback),
    openExternal: (url: string) => ipcRenderer.invoke(IPC_CHANNELS.external.open, url) as Promise<void>,
    quitAfterBackendFailure: () =>
      ipcRenderer.invoke(IPC_CHANNELS.lifecycle.quitAfterBackendFailure) as Promise<void>,
    retryBootstrap: () => ipcRenderer.invoke(IPC_CHANNELS.bootstrap.retry) as Promise<boolean>,
    window: Object.freeze({
      hide: () => ipcRenderer.invoke(IPC_CHANNELS.window.hide) as Promise<void>,
      quit: () => ipcRenderer.invoke(IPC_CHANNELS.window.quit) as Promise<void>,
      show: () => ipcRenderer.invoke(IPC_CHANNELS.window.show) as Promise<void>,
    }),
  };
  return Object.freeze(api);
}
