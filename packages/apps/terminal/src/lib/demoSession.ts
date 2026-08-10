const DEMO_SESSION_KEY = "flinttrade:demo-session";
const MODE_STORAGE_KEY = "flinttrade:mode";
const ACTIVE_VALUE = "active";
const PUBLIC_DEMO_BASE = "/demo-app/";

/** Installed builds send bare `/explore` here (safe onboarding), never ExploreRoute. */
export const INSTALLED_EXPLORE_REDIRECT = "/welcome";

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

/**
 * Build-aware `/explore` route contract (Slice 1).
 *
 * - **Public demo build** (`BASE_URL=/demo-app/`): `/explore` may render the
 *   ExploreRoute landing (marketing/demo URL compatibility).
 * - **Installed build**: direct `/explore` must **not** render ExploreRoute;
 *   redirect to {@link INSTALLED_EXPLORE_REDIRECT}. Sample-data entry is the
 *   Welcome "Try with sample data" CTA → normal Home in Explore mode.
 *
 * This is the executable contract main.tsx must honour — a comment alone is
 * not sufficient.
 */
export function exploreRoutePolicy():
  | { kind: "render-explore" }
  | { kind: "redirect"; to: typeof INSTALLED_EXPLORE_REDIRECT } {
  if (isPublicDemoBuild()) return { kind: "render-explore" };
  return { kind: "redirect", to: INSTALLED_EXPLORE_REDIRECT };
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
