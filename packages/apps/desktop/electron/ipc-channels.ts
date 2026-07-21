export const IPC_CHANNELS = {
  bootstrap: {
    cancel: "flint:bootstrap:cancel",
    event: "flint:bootstrap:event",
    get: "flint:bootstrap:get",
    retry: "flint:bootstrap:retry",
  },
  backend: {
    get: "flint:backend:get",
  },
  external: {
    open: "flint:external:open",
  },
  lifecycle: {
    quitAfterBackendFailure: "flint:lifecycle:quit-after-backend-failure",
  },
  update: {
    applyShell: "flint:update:shell:apply",
    applySource: "flint:update:source:apply",
    checkShell: "flint:update:shell:check",
    checkSource: "flint:update:source:check",
    event: "flint:update:event",
    get: "flint:update:get",
  },
  window: {
    hide: "flint:window:hide",
    quit: "flint:window:quit",
    show: "flint:window:show",
  },
} as const;

export const ALL_IPC_CHANNELS = [
  IPC_CHANNELS.bootstrap.cancel,
  IPC_CHANNELS.bootstrap.get,
  IPC_CHANNELS.bootstrap.retry,
  IPC_CHANNELS.backend.get,
  IPC_CHANNELS.external.open,
  IPC_CHANNELS.lifecycle.quitAfterBackendFailure,
  IPC_CHANNELS.update.applyShell,
  IPC_CHANNELS.update.applySource,
  IPC_CHANNELS.update.checkShell,
  IPC_CHANNELS.update.checkSource,
  IPC_CHANNELS.update.get,
  IPC_CHANNELS.window.hide,
  IPC_CHANNELS.window.quit,
  IPC_CHANNELS.window.show,
] as const;
