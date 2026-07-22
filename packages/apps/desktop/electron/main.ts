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
import { createGithubShellAttestationVerifier } from "./shell-attestation";
import { createGithubShellReleaseSource, createNodeShellInstallerHandoff } from "./shell-update-io";
import { assertShellUserDataSeparated, resolveShellUserDataPath } from "./shell-paths";
import { createShellUpdater } from "./shell-updater";
import { FLINTTRADE_SCHEME, resolveSplashRequest, SPLASH_URL } from "./splash-protocol";
import { createStartupRecoveryController } from "./startup-recovery";
import { createBackendState, createBootstrapState, createUpdateState, type UpdateKind } from "./state";
import { createDesktopTray } from "./tray";

declare const __FLINTTRADE_WINDOWS_SOURCE_FS_SHA256__: string;
declare const __FLINTTRADE_POSIX_ATOMIC_PROMOTER_SHA256__: string;
declare const __FLINTTRADE_POSIX_ATOMIC_PROMOTER_TARGET__: string;

const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  protocol.registerSchemesAsPrivileged([
    {
      privileges: {
        secure: true,
        standard: true,
      },
      scheme: FLINTTRADE_SCHEME,
    },
  ]);

  const shellUserData = resolveShellUserDataPath(app.getPath("appData"), process.platform);
  app.setPath("userData", shellUserData);
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
  assertShellUserDataSeparated(shellUserData, desktopPaths.workspace, process.platform);
  const bootstrapResources = app.isPackaged
    ? path.join(process.resourcesPath, "bootstrap")
    : path.join(appRoot, "resources", "bootstrap");
  const bootstrapManifest = JSON.parse(
    readFileSync(path.join(bootstrapResources, "tool-manifest.json"), "utf8"),
  ) as BootstrapToolManifest;
  const windowsJobSupervisor = app.isPackaged
    ? path.join(bootstrapResources, "flinttrade-job-supervisor.exe")
    : path.join(appRoot, "dist", "native", "win32-x64", "flinttrade-job-supervisor.exe");
  const windowsSourceFilesystemHelper = app.isPackaged
    ? path.join(bootstrapResources, "flinttrade-source-fs.exe")
    : path.join(appRoot, "dist", "native", "win32-x64", "flinttrade-source-fs.exe");
  const windowsSourceFilesystemHelperSha256 = process.platform === "win32"
    ? (() => {
        const digestPath = app.isPackaged
          ? path.join(bootstrapResources, "flinttrade-source-fs.sha256.json")
          : path.join(appRoot, "dist", "native", "win32-x64", "flinttrade-source-fs.sha256.json");
        const value = JSON.parse(readFileSync(digestPath, "utf8")) as Record<string, unknown>;
        if (
          value.schemaVersion !== 1 ||
          value.executable !== "flinttrade-source-fs.exe" ||
          typeof value.sha256 !== "string" ||
          !/^[0-9a-f]{64}$/.test(value.sha256) ||
          Object.keys(value).length !== 3
        ) {
          throw new Error("Windows source filesystem helper digest manifest is invalid.");
        }
        if (value.sha256 !== __FLINTTRADE_WINDOWS_SOURCE_FS_SHA256__) {
          throw new Error("Windows source filesystem helper digest differs from the bundled build identity.");
        }
        return __FLINTTRADE_WINDOWS_SOURCE_FS_SHA256__;
      })()
    : undefined;
  const posixAtomicPromoter = process.platform === "win32"
    ? undefined
    : (() => {
        if (process.platform !== "darwin" && process.platform !== "linux") {
          throw new Error(`POSIX atomic promotion is unsupported on ${process.platform}.`);
        }
        const target = process.platform === "darwin" ? "darwin-universal" : `linux-${process.arch}`;
        const helper = app.isPackaged
          ? path.join(bootstrapResources, "flinttrade-fs-promoter.node")
          : path.join(appRoot, "dist", "native", target, "flinttrade-fs-promoter.node");
        const digestPath = app.isPackaged
          ? path.join(bootstrapResources, "flinttrade-fs-promoter.sha256.json")
          : path.join(appRoot, "dist", "native", target, "flinttrade-fs-promoter.sha256.json");
        const value = JSON.parse(readFileSync(digestPath, "utf8")) as Record<string, unknown>;
        if (
          value.schemaVersion !== 1 ||
          value.executable !== "flinttrade-fs-promoter.node" ||
          value.target !== target ||
          typeof value.sha256 !== "string" ||
          !/^[0-9a-f]{64}$/.test(value.sha256) ||
          Object.keys(value).sort().join(",") !== "executable,schemaVersion,sha256,target" ||
          target !== __FLINTTRADE_POSIX_ATOMIC_PROMOTER_TARGET__ ||
          value.sha256 !== __FLINTTRADE_POSIX_ATOMIC_PROMOTER_SHA256__
        ) {
          throw new Error("POSIX atomic-promoter digest differs from the bundled build identity.");
        }
        return {
          expectedHelperSha256: __FLINTTRADE_POSIX_ATOMIC_PROMOTER_SHA256__,
          helper,
          protocol: "posix" as const,
        };
      })();
  const atomicPromotion = process.platform === "win32"
    ? {
        expectedHelperSha256: windowsSourceFilesystemHelperSha256 ?? "",
        helper: windowsSourceFilesystemHelper,
        protocol: "windows-source-fs" as const,
      }
    : posixAtomicPromoter;
  if (bootstrapManifest.schemaVersion !== 1) throw new Error("Unsupported bootstrap tool manifest schema.");

  const bootstrapState = createBootstrapState();
  const backendState = createBackendState();
  const sourceUpdateState = createUpdateState("source");
  const shellUpdateState = createUpdateState("shell", app.getVersion());
  const sourceOperationCoordinator = createSourceOperationCoordinator();
  const operationLeaseTarget = path.join(desktopPaths.sourceRoot, ".flinttrade-bootstrap-operation.lock");
  const bootIdentity = currentBootIdentity();
  const bootstrapDependencies = createNodeBootstrapDependencies(process.platform, {
    ...(atomicPromotion ? { atomicPromotion } : {}),
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
  let shellUpdater: ReturnType<typeof createShellUpdater> | null = null;

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
    windowsSourceFilesystemHelper,
    ...(windowsSourceFilesystemHelperSha256 ? { windowsSourceFilesystemHelperSha256 } : {}),
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
      await shellUpdater?.settleForQuit();
      await startupController.shutdown();
      await backendRuntime.drainForQuit();
      await shellUpdater?.settleForQuit();
    },
    getWindow: () => windows?.getPrimaryWindow() ?? null,
  });

  const installResources = app.isPackaged
    ? process.resourcesPath
    : path.resolve(appRoot, "..", "..", "..", "scripts");
  shellUpdater = createShellUpdater({
    arch: process.arch,
    attestations: createGithubShellAttestationVerifier({
      cachePath: path.join(shellUserData, "shell-updates", "sigstore"),
      fetcher: (input, init) => net.fetch(input, init),
    }),
    currentVersion: app.getVersion(),
    enabled: app.isPackaged,
    handoff: createNodeShellInstallerHandoff({
      currentExecutablePath: app.isPackaged ? process.execPath : undefined,
      currentLinuxAppDir: app.isPackaged && process.platform === "linux" ? process.env.APPDIR : undefined,
      currentLinuxAppImage: app.isPackaged && process.platform === "linux" ? process.env.APPIMAGE : undefined,
      homeDirectory: app.isPackaged && process.platform === "linux" ? app.getPath("home") : undefined,
      platform: process.platform,
      privateRoot: shellUserData,
      resourcesDirectory: installResources,
    }),
    lifecycle: {
      requestQuit: () => {
        lifecycle!.markQuitIntent();
        return lifecycle!.requestQuit("shell-update");
      },
    },
    platform: process.platform,
    releases: createGithubShellReleaseSource((input, init) => net.fetch(input, init)),
    state: shellUpdateState,
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
      const trayIcon = app.isPackaged
        ? path.join(process.resourcesPath, "icons", "tray.png")
        : path.join(appRoot, "resources", "icons", "32x32.png");
      const nativeTray = new Tray(trayIcon);
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
        applyShellUpdate: () => shellUpdater!.apply(),
        applySourceUpdate: () => sourceUpdateRuntime.updater.apply(),
        cancelBootstrap: async () => {
          const [bootstrapCancelled, backendCancelled] = await Promise.all([
            startupController.cancel(),
            backendRuntime.cancelStarting(),
          ]);
          return bootstrapCancelled || backendCancelled;
        },
        checkShellUpdate: () => shellUpdater!.check(),
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
