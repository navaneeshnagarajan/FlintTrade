/**
 * modeAuth — single source of truth for mode-related auth endpoints.
 *
 * The three-mode state machine (Explore / Practice / Live) is enforced
 * server-side from the JWT `mode` claim. The UI mode and the JWT claim MUST
 * stay in lockstep: a session showing "Practice" while holding an Explore or
 * Live JWT is the exact divergence class the Phase 1 audit flagged
 * (`.local/specs/auth-phase1/DESIGN_LOG.md`, findings A4/A5). UI mode changes
 * go through these calls so the server mints a matching token. Unlock is the
 * exception: it restores the session and does not change Mode.
 *
 *   - `downgradeMode` → POST /v1/auth/mode : drop to Explore or Practice.
 *     Revokes the old jti server-side and mints a fresh token with
 *     `live_mode_unlocked: false`. No PIN required.
 *   - `unlockWithPin` → POST /v1/auth/pin : PIN quick-unlock. Restores the
 *     existing server-side session and never changes Mode. The request does
 *     not send a mode, and callers must not set Mode from the response.
 *   - `confirmLiveMode` → POST /v1/auth/live : the explicit Live switch.
 *     Keeps the authenticator enrolment check. Unlock does not call this.
 *
 * Session-bound: the backend requires the current session JWT alongside the
 * PIN, so the daily password login stays mandatory after the token's 08:00
 * IST expiry.
 */

import { useAuthStore } from "@/stores/authStore";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";

interface ModeTokenResponse {
  data?: { token?: string; mode?: string; live_mode_unlocked?: boolean };
  token?: string;
  message?: string;
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
  const headers = buildHeaders(true);
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${getBase()}/v1/auth/mode`, {
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

async function postSessionPin(
  path: "/v1/auth/pin" | "/v1/auth/live",
  pin: string,
  failureLabel: string,
): Promise<string> {
  // During an idle or manual lock the active token is nulled, but the
  // still-valid session is kept in `reauthToken` for this re-auth.
  const auth = useAuthStore.getState();
  const sessionToken = auth.token ?? auth.reauthToken;
  const headers = buildHeaders(true);
  if (sessionToken) headers["Authorization"] = `Bearer ${sessionToken}`;

  const res = await fetch(`${getBase()}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ pin }),
  });
  const body = (await res.json()) as ModeTokenResponse;
  if (!res.ok) {
    throw new Error(body?.message || `${failureLabel} failed (${res.status})`);
  }
  const token = body?.data?.token ?? body?.token;
  if (!token) throw new Error(`${failureLabel} returned no token`);
  return token;
}

/**
 * PIN quick-unlock. Restores the existing session and never changes Mode.
 *
 * The server reads Mode from the session. This function does not send a mode
 * and does not return one — callers must leave the Mode store as it was.
 */
export async function unlockWithPin(pin: string): Promise<{ token: string }> {
  return { token: await postSessionPin("/v1/auth/pin", pin, "PIN unlock") };
}

/**
 * Explicit Live switch. Keeps the server's authenticator enrolment check.
 * Quick unlock does not use this path.
 */
export async function confirmLiveMode(pin: string): Promise<{ token: string }> {
  return { token: await postSessionPin("/v1/auth/live", pin, "Live switch") };
}
