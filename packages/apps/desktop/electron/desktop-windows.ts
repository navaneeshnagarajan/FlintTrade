export interface DesktopManagedWindow {
  destroy(): void;
  focus(): void;
  hide(): void;
  isDestroyed(): boolean;
  isMinimised(): boolean;
  isVisible(): boolean;
  loadURL(url: string): Promise<void>;
  on(event: "close" | "closed", listener: (event?: unknown) => void): void;
  restore(): void;
  show(): void;
}

export interface DesktopWindowsOptions {
  createLocal(): DesktopManagedWindow;
  createRemote(): DesktopManagedWindow;
  localUrl: string;
  onLocalClose(event: unknown): void;
  onRemoteClose(event: unknown): void;
  onRemoteFailure(error: Error): void;
  setTerminalOrigin(origin: string | null): void;
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error("Remote terminal navigation failed.", { cause: value });
}

/** Owns distinct trusted-local and authority-bearing remote window identities. */
export function createDesktopWindows(options: DesktopWindowsOptions) {
  let localWindow: DesktopManagedWindow | null = null;
  let localLoad: Promise<void> | null = null;
  let loadingRemote: DesktopManagedWindow | null = null;
  let remoteWindow: DesktopManagedWindow | null = null;
  let remoteOrigin: string | null = null;
  let terminalAttempt = 0;

  const live = (window: DesktopManagedWindow | null): window is DesktopManagedWindow =>
    window !== null && !window.isDestroyed();

  const showAndFocus = (window: DesktopManagedWindow): void => {
    if (window.isMinimised()) window.restore();
    window.show();
    window.focus();
  };

  const revokeRemoteOrigin = (): void => {
    if (remoteOrigin === null) return;
    remoteOrigin = null;
    options.setTerminalOrigin(null);
  };

  const ensureLocal = (): { load: Promise<void>; window: DesktopManagedWindow } => {
    if (live(localWindow) && localLoad) return { load: localLoad, window: localWindow };
    const window = options.createLocal();
    localWindow = window;
    window.on("close", (event) => options.onLocalClose(event));
    window.on("closed", () => {
      if (localWindow !== window) return;
      localWindow = null;
      localLoad = null;
    });
    localLoad = Promise.resolve().then(() => window.loadURL(options.localUrl));
    return { load: localLoad, window };
  };

  const disposeRemote = (): void => {
    terminalAttempt += 1;
    const loading = loadingRemote;
    const window = remoteWindow;
    loadingRemote = null;
    remoteWindow = null;
    revokeRemoteOrigin();
    if (live(loading)) loading.destroy();
    if (live(window)) window.destroy();
  };

  const showLocal = async (): Promise<void> => {
    const local = ensureLocal();
    await local.load;
    if (live(local.window)) showAndFocus(local.window);
  };

  const primaryWindow = (): DesktopManagedWindow | null => {
    if (live(remoteWindow)) return remoteWindow;
    return live(localWindow) ? localWindow : null;
  };

  return {
    getPrimaryWindow(): DesktopManagedWindow | null {
      return primaryWindow();
    },
    async handleBackendFailure(): Promise<void> {
      disposeRemote();
      try {
        await showLocal();
      } catch (error) {
        options.onRemoteFailure(asError(error));
      }
    },
    hide(): void {
      const window = primaryWindow();
      if (window) window.hide();
    },
    show(): void {
      const window = primaryWindow();
      if (window) showAndFocus(window);
      else void showLocal().catch((error: unknown) => options.onRemoteFailure(asError(error)));
    },
    showLocal,
    async showTerminal(port: number): Promise<boolean> {
      if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
        throw new RangeError("Remote terminal port must be an integer from 1 to 65535.");
      }
      disposeRemote();
      const attempt = terminalAttempt;
      const origin = `http://127.0.0.1:${port}`;
      let window: DesktopManagedWindow | null = null;
      try {
        remoteOrigin = origin;
        options.setTerminalOrigin(origin);
        window = options.createRemote();
        loadingRemote = window;
        window.on("close", (event) => options.onRemoteClose(event));
        window.on("closed", () => {
          if (loadingRemote === window) loadingRemote = null;
          else if (remoteWindow === window) remoteWindow = null;
          else return;
          revokeRemoteOrigin();
        });
        await window.loadURL(origin);
      } catch (error) {
        if (attempt !== terminalAttempt || (window !== null && loadingRemote !== window)) return false;
        loadingRemote = null;
        revokeRemoteOrigin();
        if (window && live(window)) window.destroy();
        await showLocal();
        options.onRemoteFailure(asError(error));
        return false;
      }
      if (attempt !== terminalAttempt || loadingRemote !== window || !live(window)) return false;
      loadingRemote = null;
      remoteWindow = window;
      if (live(localWindow)) localWindow.hide();
      showAndFocus(window);
      return true;
    },
    toggle(): void {
      const window = primaryWindow();
      if (!window) {
        void showLocal().catch((error: unknown) => options.onRemoteFailure(asError(error)));
        return;
      }
      if (window.isVisible()) window.hide();
      else showAndFocus(window);
    },
  };
}
