const DEMO_SESSION_KEY = "flinttrade:demo-session";
const MODE_STORAGE_KEY = "flinttrade:mode";
const ACTIVE_VALUE = "active";

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
