// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import { readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { app, BrowserWindow, ipcMain, net, protocol, session, shell } from "electron";

import { createFirstRunBootstrap, type BootstrapToolManifest } from "./bootstrap";
import { createNodeBootstrapDependencies } from "./bootstrap-io";
import { createBootstrapQuitGate } from "./bootstrap-shutdown";
import {
  buildSecureWebPreferences,
  hardenWebContents,
  installSessionHardening,
  isSafeExternalUrl,
} from "./hardening";
import { IPC_CHANNELS } from "./ipc-channels";
import { registerDesktopIpc } from "./ipc";
import { resolveDesktopPaths } from "./paths";
import { FLINTTRADE_SCHEME, resolveSplashRequest, SPLASH_URL } from "./splash-protocol";
import { createBootstrapState, createUpdateState, type BackendState, type UpdateKind } from "./state";

protocol.registerSchemesAsPrivileged([
  {
    privileges: {
      secure: true,
      standard: true,
    },
    scheme: FLINTTRADE_SCHEME,
  },
]);

const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  const development = process.env.FLINTTRADE_DESKTOP_DEVELOPMENT === "1";
  const appRoot = app.getAppPath();
  const preloadPath = path.join(appRoot, "dist", "electron-preload.js");
  const splashDirectory = path.join(appRoot, "splash");
  const splashUrl = SPLASH_URL;
  const desktopPaths = resolveDesktopPaths({
    currentWorkingDirectory: process.cwd(),
    env: process.env,
    homeDirectory: os.homedir(),
    platform: process.platform,
  });
  const bootstrapResources = app.isPackaged ? path.join(process.resourcesPath, "bootstrap") : path.join(appRoot, "resources", "bootstrap");
  const bootstrapManifest = JSON.parse(
    readFileSync(path.join(bootstrapResources, "tool-manifest.json"), "utf8"),
  ) as BootstrapToolManifest;
  if (bootstrapManifest.schemaVersion !== 1) throw new Error("Unsupported bootstrap tool manifest schema.");
  const bootstrapState = createBootstrapState();
  const bootstrapController = createFirstRunBootstrap({
    arch: process.arch,
    bootstrapResources,
    dependencies: createNodeBootstrapDependencies(process.platform),
    manifest: bootstrapManifest,
    paths: desktopPaths,
    platform: process.platform,
    state: bootstrapState,
  });
  const bootstrapQuitGate = createBootstrapQuitGate(app, bootstrapController);
  app.on("before-quit", (event) => bootstrapQuitGate.handleBeforeQuit(event));
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
    void window.loadURL(splashUrl).catch(() => bootstrapQuitGate.requestQuit());
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
      session.defaultSession.protocol.handle(FLINTTRADE_SCHEME, (request) => {
        const splashAsset = resolveSplashRequest(request.url, splashDirectory);
        if (!splashAsset || request.method !== "GET") {
          return new Response(null, { status: 404 });
        }
        return net.fetch(pathToFileURL(splashAsset).href);
      });
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
          cancelBootstrap: () => bootstrapController.cancel(),
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
          quit: () => bootstrapQuitGate.requestQuit(),
          quitAfterBackendFailure: () => bootstrapQuitGate.requestQuit(),
          retryBootstrap: () => {
            if (bootstrapState.getSnapshot().status !== "failed") return false;
            void bootstrapController.retry();
            return true;
          },
          showWindow: showMainWindow,
        },
      });

      mainWindow = createSplashWindow();
      void bootstrapController.start().catch(() => undefined);
    })
    .catch(() => bootstrapQuitGate.requestQuit());
}
