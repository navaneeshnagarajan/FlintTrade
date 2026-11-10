/**
 * Session mode claim.
 *
 * The desk mode is the JWT `mode` claim. localStorage is a cache written
 * after that assignment. A token with no JWT payload (sample data, the dev
 * bypass, and tests that use an opaque session) has nothing to apply.
 * A JWT whose claim is missing, or is not explore, practice, or live, is
 * unavailable. Connected (read) is not a mode claim.
 */

import { readPersistedAuthSession } from "@/lib/homeEntry";

export type AppMode = "explore" | "practice" | "live";

/** A signed session whose mode claim cannot be used. Never a stand-in for Live. */
export type SessionMode = AppMode | "unavailable";

const OPAQUE_SESSION_TOKENS = new Set(["demo-user", "dev-bypass"]);

export function isAppMode(value: unknown): value is AppMode {
  return value === "explore" || value === "practice" || value === "live";
}

function decodeJwtPayload(token: string): { mode?: unknown } | null {
  const parts = token.split(".");
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const segment = parts[1];
    const padded = segment
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(segment.length / 4) * 4, "=");
    return JSON.parse(atob(padded)) as { mode?: unknown };
  } catch {
    return null;
  }
}

/**
 * Mode claim carried by a session token.
 *
 * Returns null when the token is absent or has no JWT payload. Returns
 * unavailable when a JWT payload is present but its mode is missing or not
 * explore, practice, or live.
 */
export function sessionModeFromToken(token: string | null | undefined): SessionMode | null {
  if (!token || OPAQUE_SESSION_TOKENS.has(token)) return null;
  const parts = token.split(".");
  if (parts.length !== 3 || !parts[1]) return null;
  const payload = decodeJwtPayload(token);
  if (!payload) return "unavailable";
  if (isAppMode(payload.mode)) return payload.mode;
  return "unavailable";
}

/** Claim on the tab session, if one is stored. Null when the tab has no session. */
export function sessionModeFromPersistedSession(): SessionMode | null {
  const session = readPersistedAuthSession();
  if (!session) return null;
  return sessionModeFromToken(session.token);
}
