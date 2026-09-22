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
  live: "Live — real broker session. Orders and money move for real.",
};

export function modeHonestyCopy(mode: AppMode): string {
  return MODE_HONESTY_COPY[mode];
}
