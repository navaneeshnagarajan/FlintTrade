export interface LifecycleApplication {
  quit(): void;
}

export interface LifecycleCloseEvent {
  preventDefault(): void;
}

export interface LifecycleWindow {
  focus(): void;
  hide(): void;
  isDestroyed(): boolean;
  isMinimised(): boolean;
  restore(): void;
  show(): void;
}

export interface DesktopLifecycleDependencies {
  app: LifecycleApplication;
  drain(): Promise<void>;
  getWindow(): LifecycleWindow | null;
  onFailure?(error: Error): void;
}

export type QuitReason = "backend-failure" | "before-quit" | "inaccessible-close" | "recovery" | "tray" | string;

export function createDesktopLifecycle(dependencies: DesktopLifecycleDependencies) {
  let allowingQuit = false;
  let backendFailed = false;
  let quitIntent = false;
  let restoreCapabilities = { hotkey: false, tray: false };
  let settlement: Promise<void> | null = null;

  const report = (value: unknown): void => {
    const error = value instanceof Error ? value : new Error("Desktop lifecycle failed.", { cause: value });
    dependencies.onFailure?.(error);
  };

  const requestQuit = (reason: QuitReason): Promise<void> => {
    void reason;
    quitIntent = true;
    if (allowingQuit) return Promise.resolve();
    if (settlement) return settlement;
    let draining: Promise<void>;
    try {
      draining = dependencies.drain();
    } catch (error) {
      return Promise.reject(error);
    }
    const attempt = Promise.resolve(draining).then(() => {
        allowingQuit = true;
        dependencies.app.quit();
      });
    let retryable: Promise<void>;
    retryable = attempt.catch((error: unknown) => {
      allowingQuit = false;
      if (settlement === retryable) settlement = null;
      throw error;
    });
    settlement = retryable;
    return retryable;
  };

  const showAndFocus = (): void => {
    const window = dependencies.getWindow();
    if (!window || window.isDestroyed()) return;
    if (window.isMinimised()) window.restore();
    window.show();
    window.focus();
  };

  const requestQuitFailClosed = (reason: QuitReason): void => {
    void requestQuit(reason).catch(report);
  };

  return {
    allowingQuit: (): boolean => allowingQuit,
    handleActivate: showAndFocus,
    handleBeforeQuit(event: LifecycleCloseEvent): void {
      if (allowingQuit) return;
      event.preventDefault();
      requestQuitFailClosed("before-quit");
    },
    handleSecondInstance: showAndFocus,
    handleWindowClose(event: LifecycleCloseEvent): void {
      if (allowingQuit) return;
      if (!quitIntent && !backendFailed && (restoreCapabilities.tray || restoreCapabilities.hotkey)) {
        event.preventDefault();
        dependencies.getWindow()?.hide();
        return;
      }
      event.preventDefault();
      requestQuitFailClosed(backendFailed ? "backend-failure" : "inaccessible-close");
    },
    markBackendFailed(): void {
      backendFailed = true;
    },
    markBackendReady(): void {
      backendFailed = false;
    },
    markQuitIntent(): void {
      quitIntent = true;
    },
    requestQuit,
    setRestoreCapabilities(capabilities: { hotkey: boolean; tray: boolean }): void {
      restoreCapabilities = { ...capabilities };
    },
    settle: (): Promise<void> => settlement ?? Promise.resolve(),
  };
}
