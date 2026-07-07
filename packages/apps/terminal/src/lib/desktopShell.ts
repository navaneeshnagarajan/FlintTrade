/**
 * Desktop (Tauri) shell integration helpers.
 *
 * The terminal is served by the loopback backend inside the Tauri webview — a
 * "remote" origin to Tauri — so the shell injects `window.__TAURI_INTERNALS__`
 * per the `main-remote` capability (packages/apps/desktop/src-tauri/capabilities/
 * main-remote.json), which exposes exactly the commands the page may call.
 * In a plain browser the global is absent and every helper degrades to the
 * web behaviour.
 */

interface TauriInternals {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
}

function tauriInternals(): TauriInternals | null {
  const w = window as { __TAURI_INTERNALS__?: TauriInternals };
  return w.__TAURI_INTERNALS__ ?? null;
}

/** Whether the terminal is running inside the FlintTrade desktop shell. */
export function isDesktopShell(): boolean {
  return tauriInternals() !== null;
}

/**
 * Open an external URL in the user's default browser.
 *
 * Inside the Tauri shell `window.open` has no handler (the webview swallows
 * it — a dead button), so this routes through the scoped `opener:open_url`
 * command instead; the capability restricts it to https URLs. In a plain
 * browser it falls back to `window.open` in a new tab.
 */
export async function openExternalUrl(url: string): Promise<void> {
  const internals = tauriInternals();
  if (internals) {
    await internals.invoke("plugin:opener|open_url", { url });
    return;
  }
  window.open(url, "_blank", "noopener");
}

/**
 * Invoke a named desktop-shell command over Tauri IPC.
 *
 * Only commands explicitly granted to the remote main window in
 * `capabilities/main-remote.json` (e.g. `updater_state`, `run_self_update`)
 * are reachable — everything else is denied by the shell's ACL. Rejects in a
 * plain browser, so callers must gate desktop-only UI on `isDesktopShell()`.
 */
export async function invokeDesktopCommand<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  const internals = tauriInternals();
  if (!internals) {
    throw new Error(`Desktop shell command "${command}" is unavailable outside the desktop app`);
  }
  return (await internals.invoke(command, args)) as T;
}
