/**
 * Home entry policy (FT-HOME-003).
 *
 * `/home` is the canonical Home / Welcome dashboard (sidebar, Alt+H, TopBar).
 * It is not a legacy alias and must not bounce a signed-in operator to the
 * password Welcome Back gate. That gate stays on `/welcome` for visitors
 * without a live session.
 *
 * Address-bar / refresh / same-tab bookmark lose the in-memory JWT. The
 * tab-scoped session copy lives in sessionStorage only — never localStorage.
 */

import { z } from "zod";

import { safeParse } from "@/lib/safeParse";

export const CANONICAL_HOME_PATH = "/home";
export const WELCOME_GATE_PATH = "/welcome";
export const AUTH_SESSION_STORAGE_KEY = "flinttrade:auth-session";

export const HOME_ROUTE_POLICY = {
  home: { kind: "canonical", path: CANONICAL_HOME_PATH },
} as const;

export type HomeAuthStatus =
  | "unknown"
  | "transitioning"
  | "logged-in"
  | "logged-out"
  | "pin-required"
  | "setup-required";

export type HomeEntryDecision =
  | { kind: "home"; path: typeof CANONICAL_HOME_PATH }
  | { kind: "gate"; path: typeof WELCOME_GATE_PATH }
  | { kind: "loading" };

export interface PersistedAuthSession {
  token: string;
  username: string;
  expiresAt: string;
}

const persistedAuthSessionSchema = z.object({
  token: z.string().min(1),
  username: z.string().min(1),
  expiresAt: z.string(),
});

export function decideHomeEntry(status: HomeAuthStatus): HomeEntryDecision {
  if (status === "logged-in") {
    return { kind: "home", path: CANONICAL_HOME_PATH };
  }
  if (status === "unknown" || status === "transitioning") {
    return { kind: "loading" };
  }
  return { kind: "gate", path: WELCOME_GATE_PATH };
}

function sessionStorageOrNull(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function isExpired(expiresAt: string): boolean {
  if (!expiresAt) return false;
  const expiry = Date.parse(expiresAt);
  return !Number.isNaN(expiry) && expiry <= Date.now();
}

export function readPersistedAuthSession(): PersistedAuthSession | null {
  const storage = sessionStorageOrNull();
  if (!storage) return null;
  const session = safeParse(storage.getItem(AUTH_SESSION_STORAGE_KEY), persistedAuthSessionSchema);
  if (!session || isExpired(session.expiresAt)) {
    if (session) clearPersistedAuthSession();
    return null;
  }
  return session;
}

export function writePersistedAuthSession(session: PersistedAuthSession): void {
  const parsed = persistedAuthSessionSchema.safeParse(session);
  if (!parsed.success) {
    clearPersistedAuthSession();
    return;
  }
  const storage = sessionStorageOrNull();
  if (!storage) return;
  try {
    storage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(parsed.data));
  } catch {
    // Private mode / quota — Home still works for the current in-memory session.
  }
}

export function clearPersistedAuthSession(): void {
  sessionStorageOrNull()?.removeItem(AUTH_SESSION_STORAGE_KEY);
}
