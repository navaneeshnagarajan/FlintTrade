export const DESKTOP_TOGGLE_ACCELERATOR = "CommandOrControl+Shift+F";

export interface GlobalHotkeyDependencies {
  onFailure?(error: Error): void;
  register(accelerator: string, callback: () => void): boolean;
  toggle(): void;
  unregister(accelerator: string): void;
}

function asError(value: unknown, message: string): Error {
  return value instanceof Error ? value : new Error(message, { cause: value });
}

export function createGlobalHotkey(dependencies: GlobalHotkeyDependencies) {
  let registered = false;

  return {
    available: (): boolean => registered,
    start(): boolean {
      if (registered) return true;
      try {
        registered = dependencies.register(DESKTOP_TOGGLE_ACCELERATOR, () => {
          try {
            dependencies.toggle();
          } catch (error) {
            dependencies.onFailure?.(asError(error, "Desktop hotkey callback failed."));
          }
        });
        if (!registered) {
          dependencies.onFailure?.(new Error("The FlintTrade global toggle hotkey could not be registered."));
        }
      } catch (error) {
        registered = false;
        dependencies.onFailure?.(asError(error, "The FlintTrade global toggle hotkey could not be registered."));
      }
      return registered;
    },
    stop(): void {
      if (!registered) return;
      registered = false;
      try {
        dependencies.unregister(DESKTOP_TOGGLE_ACCELERATOR);
      } catch (error) {
        dependencies.onFailure?.(asError(error, "The FlintTrade global toggle hotkey could not be unregistered."));
      }
    },
  };
}
