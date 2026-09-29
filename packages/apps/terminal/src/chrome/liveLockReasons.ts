/**
 * Reasons that keep Live disabled in the Mode menu.
 *
 * Each reason comes from a status the desk already has. The Laya place-gate
 * qualification is optional: omit `layaQualifiedForLive` until that field
 * exists. Do not infer it from the Laya heartbeat (ready, degraded, down).
 */

export const ENROL_2FA_AND_CONNECT_BROKER = "Enrol 2FA and connect a broker";
export const CREATE_A_PIN = "Create a PIN in Settings";
export const NOT_QUALIFIED_FOR_LIVE = "Not qualified for Live";

export interface LiveMenuLockStatus {
  brokerConnected: boolean;
  totpEnrolled: boolean;
  /**
   * Whether a quick-unlock PIN exists.
   * Missing or false stays locked: skipping the optional PIN at setup
   * must not open a Live dialog that `/auth/live` will reject.
   */
  hasPin: boolean;
  /**
   * Whether Laya qualifies this operator for Live.
   * Absent when the place gate has not reported qualification.
   * `false` adds {@link NOT_QUALIFIED_FOR_LIVE}. `true` adds nothing.
   */
  layaQualifiedForLive?: boolean;
}

/** Lock reasons in display order. An empty list means Live can be chosen. */
export function liveMenuLockReasons(status: LiveMenuLockStatus): readonly string[] {
  const reasons: string[] = [];
  if (!status.brokerConnected || !status.totpEnrolled) {
    reasons.push(ENROL_2FA_AND_CONNECT_BROKER);
  }
  if (status.hasPin !== true) {
    reasons.push(CREATE_A_PIN);
  }
  if (status.layaQualifiedForLive === false) {
    reasons.push(NOT_QUALIFIED_FOR_LIVE);
  }
  return reasons;
}
