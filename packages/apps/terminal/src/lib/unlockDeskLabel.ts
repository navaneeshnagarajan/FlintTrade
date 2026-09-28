/**
 * Desk name the lock screen shows for the mode it will reopen.
 *
 * The name comes from the server session JWT `mode` claim. It is display
 * only: unlock does not send a mode, and this label is not taken from the
 * Mode store or from the unlock response.
 *
 *   practice → Unlock Practice desk
 *   live     → Unlock Live desk
 *
 * Those are the session `mode` claims that name a desk. Sample-data
 * `explore`, a retired claim such as `demo` or `sandbox`, and any other
 * value keep the plain Locked heading and Unlock button. Connected (read)
 * is a broker status, not a session mode claim, so this screen does not
 * name it.
 */

const UNLOCK_DESK_LABEL = {
  practice: "Unlock Practice desk",
  live: "Unlock Live desk",
} as const;

type NamedSessionMode = keyof typeof UNLOCK_DESK_LABEL;

function sessionModeClaim(token: string | null | undefined): string | null {
  if (!token) return null;
  const segment = token.split(".")[1];
  if (!segment) return null;
  try {
    const padded = segment
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(segment.length / 4) * 4, "=");
    const payload = JSON.parse(atob(padded)) as { mode?: unknown };
    return typeof payload.mode === "string" ? payload.mode : null;
  } catch {
    return null;
  }
}

/**
 * Operator label for a Practice or Live session.
 *
 * Returns null for a sample-data session, a retired or unknown claim, and
 * when the token cannot be read. Callers then keep the plain Locked heading
 * and Unlock button.
 */
export function unlockDeskLabel(token: string | null | undefined): string | null {
  const mode = sessionModeClaim(token);
  if (mode === "practice" || mode === "live") {
    const named: NamedSessionMode = mode;
    return UNLOCK_DESK_LABEL[named];
  }
  return null;
}
