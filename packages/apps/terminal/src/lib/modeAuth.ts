/**
 * modeAuth — single source of truth for the two mode-related auth endpoints.
 *
 * The three-mode state machine (Explore / Practice / Live) is enforced
 * server-side from the JWT `mode` claim. The UI mode and the JWT claim MUST
 * stay in lockstep: a session showing "Practice" while holding an Explore or
 * Live JWT is the exact divergence class the Phase 1 audit flagged
 * (`.local/specs/auth-phase1/DESIGN_LOG.md`, findings A4/A5). Every UI mode
 * change therefore routes through one of these two calls so the server mints a
 * matching token.
 *
 *   - `downgradeMode` → POST /v1/auth/mode : drop to a SAFER mode (explore or
 *     practice). Revokes the old jti server-side, mints a fresh token with
 *     `live_mode_unlocked: false`. No PIN required (privilege reduction).
 *   - `unlockWithPin` → POST /v1/auth/pin : PIN re-authentication. Defaults to
 *     Live (the explicit arm-real-money gesture); pass a non-live `mode` for a
 *     mode-preserving idle unlock that must NOT silently escalate to Live.
 */

import type { AppMode } from "@/stores/modeStore";

const FT_API = "/ft-api/v1";

interface ModeTokenResponse {
  data?: { token?: string; mode?: string; live_mode_unlocked?: boolean };
  token?: string;
  message?: string;
}

export interface UnlockResult {
  token: string;
  mode: AppMode;
  liveUnlocked: boolean;
}

/** Modes a session may drop to without re-authenticating. */
export type DowngradeMode = "explore" | "practice";

/**
 * Downgrade the current session to `target` (explore or practice), returning
 * the freshly minted token. Throws on any non-2xx or missing token so callers
 * can keep the UI in its current (higher) mode — never flip the UI to a safer
 * mode while the server still holds a higher-privilege token.
 */
export async function downgradeMode(
  target: DowngradeMode,
  token: string | null,
): Promise<string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${FT_API}/auth/mode`, {
    method: "POST",
    headers,
    body: JSON.stringify({ mode: target }),
  });
  if (!res.ok) {
    throw new Error(`mode downgrade to ${target} failed (${res.status})`);
  }
  const body = (await res.json()) as ModeTokenResponse;
  const newToken = body?.data?.token ?? body?.token;
  if (!newToken) throw new Error("mode downgrade returned no token");
  return newToken;
}

/**
 * PIN quick-unlock. `mode` defaults to "live" (the explicit real-money arm);
 * pass the session's CURRENT mode for a mode-preserving idle unlock so the
 * server never silently hands back a Live-unlocked token under a non-live UI.
 */
export async function unlockWithPin(
  pin: string,
  mode: AppMode = "live",
): Promise<UnlockResult> {
  const res = await fetch(`${FT_API}/auth/pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin, mode }),
  });
  const body = (await res.json()) as ModeTokenResponse;
  if (!res.ok) {
    throw new Error(body?.message || `PIN unlock failed (${res.status})`);
  }
  const token = body?.data?.token ?? body?.token;
  if (!token) throw new Error("PIN unlock returned no token");
  const resolvedMode = (body?.data?.mode as AppMode | undefined) ?? mode;
  return {
    token,
    mode: resolvedMode,
    liveUnlocked: body?.data?.live_mode_unlocked ?? resolvedMode === "live",
  };
}
