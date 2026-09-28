/**
 * Desk name the lock screen shows for the mode it will reopen.
 *
 * The name comes from the server session JWT `mode` claim. It is display
 * only: unlock does not send a mode, and this label is not taken from the
 * Mode store or from the unlock response.
 *
 *   practice → Unlock Practice desk
 *   explore  → Unlock Connected (read) desk
 *   live     → Unlock Live desk
 */

const UNLOCK_DESK_LABEL = {
  practice: "Unlock Practice desk",
  explore: "Unlock Connected (read) desk",
  live: "Unlock Live desk",
} as const;

type SessionMode = keyof typeof UNLOCK_DESK_LABEL;

function sessionModeClaim(token: string | null | undefined): SessionMode | null {
  if (!token) return null;
  const segment = token.split(".")[1];
  if (!segment) return null;
  try {
    const padded = segment
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(segment.length / 4) * 4, "=");
    const payload = JSON.parse(atob(padded)) as { mode?: unknown };
    const mode = payload.mode;
    if (mode === "practice" || mode === "explore" || mode === "live") return mode;
    return null;
  } catch {
    return null;
  }
}

/** Operator label for the locked session, or null when the claim cannot be read. */
export function unlockDeskLabel(token: string | null | undefined): string | null {
  const mode = sessionModeClaim(token);
  return mode ? UNLOCK_DESK_LABEL[mode] : null;
}
