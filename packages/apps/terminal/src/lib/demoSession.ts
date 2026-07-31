const DEMO_SESSION_KEY = "flinttrade:demo-session";
const MODE_STORAGE_KEY = "flinttrade:mode";
const ACTIVE_VALUE = "active";
const PUBLIC_DEMO_BASE = "/demo-app/";

/**
 * Report whether this bundle is the public, hosted demo build.
 *
 * The site builds the terminal with `vite build --base=/demo-app/` and strips
 * every `VITE_*` variable beforehand, so the base path is the only build-time
 * signal that survives into the bundle.
 *
 * Credential capture - the operator account password, the PIN, broker API keys -
 * belongs to a real local install. The public demo must never present those
 * fields, because a password typed into a public origin is one a password
 * manager offers to store against that origin.
 */
export function isPublicDemoBuild(): boolean {
  return import.meta.env.BASE_URL === PUBLIC_DEMO_BASE;
}

function safeLocalStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage ?? null;
}

export function markDemoSessionActive(): void {
  safeLocalStorage()?.setItem(DEMO_SESSION_KEY, ACTIVE_VALUE);
}

export function clearDemoSession(): void {
  safeLocalStorage()?.removeItem(DEMO_SESSION_KEY);
}

export function isDemoSessionActive(): boolean {
  const storage = safeLocalStorage();
  if (!storage || storage.getItem(DEMO_SESSION_KEY) !== ACTIVE_VALUE) return false;

  try {
    const rawMode = storage.getItem(MODE_STORAGE_KEY);
    if (!rawMode) return false;
    const parsed = JSON.parse(rawMode) as { state?: { mode?: unknown } };
    return parsed?.state?.mode === "explore";
  } catch {
    return false;
  }
}
