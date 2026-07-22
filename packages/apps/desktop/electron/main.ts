// Adapted from NousResearch/hermes-agent commit 7651764ce (MIT).
import { readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

import {
  app,
  BrowserWindow,
  globalShortcut,
  ipcMain,
  Menu,
  net,
  Notification,
  protocol,
  session,
  shell,
  Tray,
} from "electron";

import { createFirstRunBootstrap, type BootstrapResult, type BootstrapToolManifest } from "./bootstrap";
import { createNodeBootstrapDependencies, currentBootIdentity } from "./bootstrap-io";
import { createBackendRuntime } from "./backend-runtime";
import { BackendSupervisor } from "./backend-supervisor";
import { createDesktopWindows, type DesktopManagedWindow } from "./desktop-windows";
import {
  buildSecureWebPreferences,
  hardenWebContents,
  installSessionHardening,
  isSafeExternalUrl,
} from "./hardening";
import { createGlobalHotkey } from "./hotkey";
import { IPC_CHANNELS } from "./ipc-channels";
import { registerDesktopIpc } from "./ipc";
import { createDesktopLifecycle } from "./lifecycle";
import { createNativeNotificationRelay } from "./notifications";
import { resolveDesktopPaths } from "./paths";
import { createSourceOperationCoordinator } from "./source-operation";
import { createSourceUpdateRuntime } from "./source-update-runtime";
import { FLINTTRADE_SCHEME, resolveSplashRequest, SPLASH_URL } from "./splash-protocol";
import { createStartupRecoveryController } from "./startup-recovery";
import { createBackendState, createBootstrapState, createUpdateState, type UpdateKind } from "./state";
import { createDesktopTray } from "./tray";

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
  const bootstrapResources = app.isPackaged
    ? path.join(process.resourcesPath, "bootstrap")
    : path.join(appRoot, "resources", "bootstrap");
  const bootstrapManifest = JSON.parse(
    readFileSync(path.join(bootstrapResources, "tool-manifest.json"), "utf8"),
  ) as BootstrapToolManifest;
  const windowsJobSupervisor = app.isPackaged
    ? path.join(bootstrapResources, "flinttrade-job-supervisor.exe")
    : path.join(appRoot, "dist", "native", "win32-x64", "flinttrade-job-supervisor.exe");
  if (bootstrapManifest.schemaVersion !== 1) throw new Error("Unsupported bootstrap tool manifest schema.");

  const bootstrapState = createBootstrapState();
  const backendState = createBackendState();
  const sourceUpdateState = createUpdateState("source");
  const shellUpdateState = createUpdateState("shell", app.getVersion());
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

  let terminalOrigin: string | null = null;
  let windows: ReturnType<typeof createDesktopWindows> | null = null;
  let lifecycle: ReturnType<typeof createDesktopLifecycle> | null = null;

  const notificationRelay = createNativeNotificationRelay({
    isSupported: () => Notification.isSupported(),
    show: ({ body, title }) => new Notification({ body, title }).show(),
  });
  let backendRuntime!: ReturnType<typeof createBackendRuntime>;
  const backendSupervisor = new BackendSupervisor({
    bootSessionIdentity: bootIdentity,
    frontendDist: path.join(desktopPaths.activeSource, "packages", "apps", "terminal", "dist"),
    onNotification: ({ body, title }) => {
      notificationRelay.publish({ body, title, type: "notification" });
    },
    onUnexpectedExit: () => backendRuntime.markUnexpectedExit(),
    sourceRoot: desktopPaths.activeSource,
    workspace: desktopPaths.workspace,
  });
  backendRuntime = createBackendRuntime({
    activeSource: desktopPaths.activeSource,
    async onFailure() {
      lifecycle?.markBackendFailed();
      await windows?.handleBackendFailure();
    },
    async onReady(backend) {
      const shown = await windows?.showTerminal(backend.port);
      if (shown === true) lifecycle?.markBackendReady();
    },
    async onStopped() {
      lifecycle?.markBackendFailed();
      await windows?.handleBackendFailure();
    },
    state: backendState,
    supervisor: backendSupervisor,
  });

  const sourceUpdateRuntime = createSourceUpdateRuntime({
    arch: process.arch,
    bootIdentity,
    bootstrapResources,
    coordinator: sourceOperationCoordinator,
    dependencies: bootstrapDependencies,
    lifecycle: backendRuntime.sourceLifecycle,
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

  lifecycle = createDesktopLifecycle({
    app,
    async drain() {
      await startupController.shutdown();
      await backendRuntime.drainForQuit();
    },
    getWindow: () => windows?.getPrimaryWindow() ?? null,
  });

  const originPolicy = () => ({ splashUrl, terminalOrigin });
  const broadcast = (channel: string, payload: unknown): void => {
    for (const window of BrowserWindow.getAllWindows()) {
      if (!window.isDestroyed()) window.webContents.send(channel, payload);
    }
  };
  bootstrapState.subscribe((snapshot) => broadcast(IPC_CHANNELS.bootstrap.event, snapshot));
  backendState.subscribe((snapshot) => broadcast(IPC_CHANNELS.backend.event, snapshot));
  sourceUpdateState.subscribe((snapshot) => broadcast(IPC_CHANNELS.update.event, snapshot));
  shellUpdateState.subscribe((snapshot) => broadcast(IPC_CHANNELS.update.event, snapshot));

  const updateStateFor = (kind: UpdateKind) => (kind === "source" ? sourceUpdateState : shellUpdateState);
  const checkUnavailable = (kind: UpdateKind) => {
    const store = updateStateFor(kind);
    const label = kind === "source" ? "Source" : "Electron shell";
    const attempt = store.begin("checking", `Checking ${label.toLowerCase()} updates`);
    store.unavailable(
      attempt,
      `${label} updates are not available in this build.`,
      kind === "shell" ? app.getVersion() : null,
    );
    return store.getSnapshot();
  };

  const asManagedWindow = (browserWindow: BrowserWindow): DesktopManagedWindow => ({
    destroy: () => browserWindow.destroy(),
    focus: () => browserWindow.focus(),
    hide: () => browserWindow.hide(),
    isDestroyed: () => browserWindow.isDestroyed(),
    isMinimised: () => browserWindow.isMinimized(),
    isVisible: () => browserWindow.isVisible(),
    loadURL: (url) => browserWindow.loadURL(url),
    on(event, listener) {
      if (event === "close") browserWindow.on("close", (closeEvent) => listener(closeEvent));
      else browserWindow.on("closed", () => listener());
    },
    restore: () => browserWindow.restore(),
    show: () => browserWindow.show(),
  });

  const createWindow = (remote: boolean): DesktopManagedWindow => asManagedWindow(new BrowserWindow({
    backgroundColor: "#0b0d12",
    fullscreenable: remote,
    height: remote ? 900 : 360,
    maximizable: remote,
    minHeight: remote ? 640 : 360,
    minWidth: remote ? 960 : 540,
    resizable: remote,
    show: false,
    title: "FlintTrade",
    webPreferences: buildSecureWebPreferences(preloadPath, development),
    width: remote ? 1440 : 540,
  }));

  windows = createDesktopWindows({
    createLocal: () => createWindow(false),
    createRemote: () => createWindow(true),
    localUrl: splashUrl,
    onLocalClose: (event) => lifecycle?.handleWindowClose(event as { preventDefault(): void }),
    onRemoteClose: (event) => lifecycle?.handleWindowClose(event as { preventDefault(): void }),
    onRemoteFailure: () => lifecycle?.markBackendFailed(),
    setTerminalOrigin: (origin) => { terminalOrigin = origin; },
  });

  let canRestoreHiddenWindow = false;
  const tray = createDesktopTray({
    create(callbacks) {
      const nativeTray = new Tray(path.join(appRoot, "src-tauri", "icons", "32x32.png"));
      nativeTray.setToolTip("FlintTrade");
      nativeTray.setContextMenu(Menu.buildFromTemplate([
        { click: callbacks.onShow, label: "Show FlintTrade" },
        { type: "separator" },
        { click: callbacks.onQuit, label: "Quit FlintTrade" },
      ]));
      nativeTray.on("click", () => callbacks.onLeftClick("up"));
      return { destroy: () => nativeTray.destroy() };
    },
    markQuitIntent: () => lifecycle?.markQuitIntent(),
    requestQuit: () => lifecycle?.requestQuit("tray"),
    show: () => windows?.show(),
    toggle: () => windows?.toggle(),
  });
  const hotkey = createGlobalHotkey({
    register: (accelerator, callback) => globalShortcut.register(accelerator, callback),
    toggle: () => windows?.toggle(),
    unregister: (accelerator) => globalShortcut.unregister(accelerator),
  });

  let startup: Promise<boolean> | null = null;
  const runStartup = (startBootstrap: () => Promise<BootstrapResult>): Promise<boolean> => {
    if (startup) return startup;
    const attempt = (async () => {
      try {
        await windows!.showLocal();
        const result = await startBootstrap();
        if (!result.ok) {
          lifecycle!.markBackendFailed();
          return false;
        }
        await backendRuntime.start();
        return true;
      } catch {
        lifecycle!.markBackendFailed();
        await windows!.handleBackendFailure();
        return false;
      }
    })();
    startup = attempt;
    const clear = (): void => {
      if (startup === attempt) startup = null;
    };
    void attempt.then(clear, clear);
    return attempt;
  };

  const retryStartup = async (): Promise<boolean> => {
    if (startup) return false;
    const bootstrap = bootstrapState.getSnapshot();
    if (bootstrap.status === "failed") {
      return runStartup(() => startupController.retry());
    }
    if (bootstrap.status !== "ready") return false;
    const backend = backendState.getSnapshot();
    if (backend.status === "failed" || backend.status === "stopped") {
      return runStartup(async () => ({ ok: true }));
    }
    const running = backendRuntime.getRunning();
    if (backend.status === "ready" && running) {
      try {
        const shown = await windows!.showTerminal(running.port);
        if (shown) lifecycle!.markBackendReady();
        else lifecycle!.markBackendFailed();
        return shown;
      } catch {
        lifecycle!.markBackendFailed();
        return false;
      }
    }
    return false;
  };

  app.on("before-quit", (event) => lifecycle!.handleBeforeQuit(event));
  app.on("second-instance", () => lifecycle!.handleSecondInstance());
  app.on("activate", () => lifecycle!.handleActivate());
  app.on("will-quit", () => {
    hotkey.stop();
    tray.stop();
  });

  void app.whenReady().then(async () => {
    app.setName("FlintTrade");
    session.defaultSession.protocol.handle(FLINTTRADE_SCHEME, (request) => {
      const splashAsset = resolveSplashRequest(request.url, splashDirectory);
      if (!splashAsset || request.method !== "GET") return new Response(null, { status: 404 });
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
        applySourceUpdate: () => sourceUpdateRuntime.updater.apply(),
        cancelBootstrap: async () => {
          const [bootstrapCancelled, backendCancelled] = await Promise.all([
            startupController.cancel(),
            backendRuntime.cancelStarting(),
          ]);
          return bootstrapCancelled || backendCancelled;
        },
        checkShellUpdate: () => checkUnavailable("shell"),
        checkSourceUpdate: () => {
          if (bootstrapState.getSnapshot().status !== "ready") {
            throw new Error("Source updates can be checked after source bootstrap is ready.");
          }
          return sourceUpdateRuntime.updater.check();
        },
        getBackendState: () => backendState.getSnapshot(),
        getBootstrapSnapshot: () => bootstrapState.getSnapshot(),
        getUpdateState: (kind) => updateStateFor(kind).getSnapshot(),
        hideWindow: () => {
          if (!canRestoreHiddenWindow) throw new Error("The window cannot hide without a restore control.");
          windows!.hide();
        },
        openExternal: async (url) => {
          if (!isSafeExternalUrl(url)) throw new TypeError("Only HTTPS external URLs are allowed.");
          await shell.openExternal(url);
        },
        quit: () => {
          lifecycle!.markQuitIntent();
          return lifecycle!.requestQuit("ipc");
        },
        quitAfterBackendFailure: () => {
          lifecycle!.markBackendFailed();
          lifecycle!.markQuitIntent();
          return lifecycle!.requestQuit("backend-failure");
        },
        retryBootstrap: retryStartup,
        showWindow: () => windows!.show(),
      },
    });

    await windows!.showLocal();
    const trayAvailable = tray.start();
    const hotkeyAvailable = hotkey.start();
    canRestoreHiddenWindow = trayAvailable || hotkeyAvailable;
    lifecycle!.setRestoreCapabilities({ hotkey: hotkeyAvailable, tray: trayAvailable });
    void runStartup(() => startupController.start());
  }).catch(() => {
    lifecycle!.markBackendFailed();
    void lifecycle!.requestQuit("recovery").catch(() => undefined);
  });
}
