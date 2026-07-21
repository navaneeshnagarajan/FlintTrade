// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import { readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { app, BrowserWindow, ipcMain, net, protocol, session, shell } from "electron";

import { createFirstRunBootstrap, type BootstrapToolManifest } from "./bootstrap";
import { createNodeBootstrapDependencies, currentBootIdentity } from "./bootstrap-io";
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
import { createSourceOperationCoordinator } from "./source-operation";
import { createSourceUpdateRuntime } from "./source-update-runtime";
import { FLINTTRADE_SCHEME, resolveSplashRequest, SPLASH_URL } from "./splash-protocol";
import { createStartupRecoveryController } from "./startup-recovery";
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
  const windowsJobSupervisor = app.isPackaged
    ? path.join(bootstrapResources, "flinttrade-job-supervisor.exe")
    : path.join(appRoot, "dist", "native", "win32-x64", "flinttrade-job-supervisor.exe");
  if (bootstrapManifest.schemaVersion !== 1) throw new Error("Unsupported bootstrap tool manifest schema.");
  const bootstrapState = createBootstrapState();
  const sourceUpdateState = createUpdateState("source");
  const shellUpdateState = createUpdateState("shell");
  const sourceOperationCoordinator = createSourceOperationCoordinator();
  const operationLeaseTarget = path.join(desktopPaths.sourceRoot, ".flinttrade-bootstrap-operation.lock");
  const bootIdentity = currentBootIdentity();
  const bootstrapDependencies = createNodeBootstrapDependencies(process.platform, {
    operationLeaseTarget,
    windowsJobSupervisor,
  });
  const bootstrapController = createFirstRunBootstrap({
    arch: process.arch,
    bootIdentity,
    bootstrapResources,
    dependencies: bootstrapDependencies,
    manifest: bootstrapManifest,
    operationCoordinator: sourceOperationCoordinator,
    paths: desktopPaths,
    platform: process.platform,
    singletonAuthorised: hasSingleInstanceLock,
    state: bootstrapState,
  });
  const sourceUpdateRuntime = createSourceUpdateRuntime({
    arch: process.arch,
    bootIdentity,
    bootstrapResources,
    coordinator: sourceOperationCoordinator,
    dependencies: bootstrapDependencies,
    lifecycle: {
      isAvailable: () => false,
      async bootActive() {
        throw new Error("Source update apply requires the Task 4 backend guardian and boot lifecycle.");
      },
      async drainCurrent() {
        throw new Error("Source update apply requires the Task 4 backend guardian and drain lifecycle.");
      },
    },
    manifest: bootstrapManifest,
    paths: desktopPaths,
    platform: process.platform,
    singletonAuthorised: hasSingleInstanceLock,
    state: sourceUpdateState,
  });
  let sourceRuntimePrepared = false;
  const startupController = createStartupRecoveryController({
    bootstrap: bootstrapController,
    recovery: {
      cancel: sourceUpdateRuntime.cancelRecovery,
      async recover(signal) {
        if (!sourceRuntimePrepared) {
          await sourceUpdateRuntime.prepare();
          sourceRuntimePrepared = true;
        }
        if (signal.aborted) throw signal.reason;
        return sourceUpdateRuntime.updater.recover(signal);
      },
      settleForQuit: sourceUpdateRuntime.settleForQuit,
    },
    state: bootstrapState,
  });
  const bootstrapQuitGate = createBootstrapQuitGate(app, startupController);
  app.on("before-quit", (event) => bootstrapQuitGate.handleBeforeQuit(event));
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
    const label = kind === "source" ? "Source" : "Electron shell";
    const attempt = store.begin("checking", `Checking ${label.toLowerCase()} updates`);
    store.unavailable(attempt, `${label} updates are not active in this scaffold.`);
    return store.getSnapshot();
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
    void window.loadURL(splashUrl).catch(() => bootstrapQuitGate.requestQuitFailClosed());
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
            throw new Error("Source update apply requires the backend guardian and is not active yet.");
          },
          cancelBootstrap: () => startupController.cancel(),
          checkShellUpdate: () => checkUnavailable("shell"),
          checkSourceUpdate: () => {
            if (bootstrapState.getSnapshot().status !== "ready") {
              throw new Error("Source updates can be checked after source bootstrap is ready.");
            }
            return sourceUpdateRuntime.updater.check();
          },
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
            void startupController.retry();
            return true;
          },
          showWindow: showMainWindow,
        },
      });

      mainWindow = createSplashWindow();
      void startupController.start().catch(() => undefined);
    })
    .catch(() => bootstrapQuitGate.requestQuitFailClosed());
}
