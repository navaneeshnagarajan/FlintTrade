// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { app, BrowserWindow, ipcMain, session, shell } from "electron";

import {
  buildSecureWebPreferences,
  hardenWebContents,
  installSessionHardening,
  isSafeExternalUrl,
} from "./hardening";
import { IPC_CHANNELS } from "./ipc-channels";
import { registerDesktopIpc } from "./ipc";
import { resolveDesktopPaths } from "./paths";
import { createBootstrapState, createUpdateState, type BackendState, type UpdateKind } from "./state";

const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  const development = process.env.FLINTTRADE_DESKTOP_DEVELOPMENT === "1";
  const appRoot = app.getAppPath();
  const preloadPath = path.join(appRoot, "dist", "electron-preload.js");
  const splashPath = path.join(appRoot, "splash", "index.html");
  const splashUrl = pathToFileURL(splashPath).href;
  const desktopPaths = resolveDesktopPaths({ env: process.env, homeDirectory: os.homedir(), platform: process.platform });
  const bootstrapState = createBootstrapState();
  const sourceUpdateState = createUpdateState("source");
  const shellUpdateState = createUpdateState("shell");
  const backendState: Readonly<BackendState> = Object.freeze({ port: null, status: "stopped", url: null });
  let mainWindow: BrowserWindow | null = null;
  let terminalOrigin: string | null = null;

  const originPolicy = () => ({ splashUrl, terminalOrigin });

  const broadcast = (channel: string, payload: unknown): void => {
    for (const window of BrowserWindow.getAllWindows()) {
      if (!window.isDestroyed()) window.webContents.send(channel, payload);
    }
  };

  bootstrapState.subscribe((snapshot) => broadcast(IPC_CHANNELS.bootstrap.event, snapshot));
  sourceUpdateState.subscribe((snapshot) => broadcast(IPC_CHANNELS.update.event, snapshot));
  shellUpdateState.subscribe((snapshot) => broadcast(IPC_CHANNELS.update.event, snapshot));

  const updateStateFor = (kind: UpdateKind) => (kind === "source" ? sourceUpdateState : shellUpdateState);

  const checkUnavailable = (kind: UpdateKind) => {
    const store = updateStateFor(kind);
    return store.publish({
      failure: null,
      message: `${kind === "source" ? "Source" : "Electron shell"} updates are not active in this scaffold.`,
      progress: null,
      status: "unavailable",
      version: null,
    });
  };

  const createSplashWindow = (): BrowserWindow => {
    const window = new BrowserWindow({
      width: 540,
      height: 360,
      minWidth: 540,
      minHeight: 360,
      show: false,
      resizable: false,
      maximizable: false,
      fullscreenable: false,
      title: "FlintTrade",
      backgroundColor: "#0b0d12",
      webPreferences: buildSecureWebPreferences(preloadPath, development),
    });
    window.once("ready-to-show", () => window.show());
    window.on("closed", () => {
      if (mainWindow === window) mainWindow = null;
    });
    void window.loadFile(splashPath).catch(() => app.quit());
    return window;
  };

  const showMainWindow = (): void => {
    if (mainWindow?.isDestroyed() !== false) mainWindow = createSplashWindow();
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  };

  app.on("second-instance", showMainWindow);
  app.on("activate", showMainWindow);

  void app
    .whenReady()
    .then(() => {
      app.setName("FlintTrade");
      installSessionHardening(session.defaultSession);
      app.on("web-contents-created", (_event, contents) => {
        hardenWebContents(contents, {
          development,
          openExternal: (url) => shell.openExternal(url),
          originPolicy,
        });
      });

      registerDesktopIpc(ipcMain, {
        originPolicy,
        services: {
          applyShellUpdate: () => {
            throw new Error("Electron shell update is not available.");
          },
          applySourceUpdate: () => {
            throw new Error("Source update is not available.");
          },
          cancelBootstrap: () => bootstrapState.cancel(bootstrapState.getSnapshot().attempt),
          checkShellUpdate: () => checkUnavailable("shell"),
          checkSourceUpdate: () => checkUnavailable("source"),
          getBackendState: () => backendState,
          getBootstrapSnapshot: () => bootstrapState.getSnapshot(),
          getUpdateState: (kind) => updateStateFor(kind).getSnapshot(),
          hideWindow: () => mainWindow?.hide(),
          openExternal: async (url) => {
            if (!isSafeExternalUrl(url)) throw new TypeError("Only HTTPS external URLs are allowed.");
            await shell.openExternal(url);
          },
          quit: () => app.quit(),
          quitAfterBackendFailure: () => app.quit(),
          retryBootstrap: () => bootstrapState.retry(),
          showWindow: showMainWindow,
        },
      });

      // The resolved paths are intentionally read-only in Task 1. Bootstrapping
      // will consume them in the next implementation slice without touching the
      // platform workspace from this scaffold.
      void desktopPaths;
      mainWindow = createSplashWindow();
    })
    .catch(() => app.quit());
}
