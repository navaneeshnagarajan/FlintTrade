export interface TrayCallbacks {
  onLeftClick(state: "down" | "up"): void;
  onQuit(): void;
  onShow(): void;
}

export interface TrayHandle {
  destroy(): void;
}

export interface DesktopTrayDependencies {
  create(callbacks: TrayCallbacks): TrayHandle;
  markQuitIntent(): void;
  onFailure?(error: Error): void;
  requestQuit(): Promise<void> | void;
  show(): void;
  toggle(): void;
}

function asError(value: unknown, message: string): Error {
  return value instanceof Error ? value : new Error(message, { cause: value });
}

export function createDesktopTray(dependencies: DesktopTrayDependencies) {
  let handle: TrayHandle | null = null;

  const report = (error: unknown, message: string): void => {
    dependencies.onFailure?.(asError(error, message));
  };

  return {
    available: (): boolean => handle !== null,
    start(): boolean {
      if (handle) return true;
      try {
        handle = dependencies.create({
          onLeftClick(state) {
            if (state !== "up") return;
            try {
              dependencies.toggle();
            } catch (error) {
              report(error, "The FlintTrade tray could not toggle its window.");
            }
          },
          onQuit() {
            dependencies.markQuitIntent();
            try {
              void Promise.resolve(dependencies.requestQuit()).catch((error: unknown) => {
                report(error, "The FlintTrade tray quit request failed.");
              });
            } catch (error) {
              report(error, "The FlintTrade tray quit request failed.");
            }
          },
          onShow() {
            try {
              dependencies.show();
            } catch (error) {
              report(error, "The FlintTrade tray could not show its window.");
            }
          },
        });
      } catch (error) {
        handle = null;
        report(error, "The FlintTrade tray could not be created.");
      }
      return handle !== null;
    },
    stop(): void {
      const current = handle;
      handle = null;
      if (!current) return;
      try {
        current.destroy();
      } catch (error) {
        report(error, "The FlintTrade tray could not be destroyed cleanly.");
      }
    },
  };
}
