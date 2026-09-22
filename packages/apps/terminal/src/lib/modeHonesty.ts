/**
 * Mode honesty — one desk line owned by Explore / Practice / Live.
 *
 * This is not an incident. Outage, degradation, and block states belong to
 * the incident strip (#270) and must not reuse this copy.
 */

import type { AppMode } from "@/stores/modeStore";

export const MODE_HONESTY_COPY: Record<AppMode, string> = {
  explore: "Explore — sample data only. No broker session, no live orders.",
  practice: "Practice — SandboxEngine fills. Not your funded broker account.",
  // Execution mode only. Live can be selected while the broker is disconnected,
  // so this line must not claim a session is already open.
  live: "Live — real-money capable when a broker is Connected. Orders place only on a live session.",
};

export function modeHonestyCopy(mode: AppMode): string {
  return MODE_HONESTY_COPY[mode];
}
