/**
 * Operator-facing Mode names.
 *
 * The store still uses explore / practice / live. The desk only shows
 * Practice, Connected (read), and Live. Connected (read) is a chrome
 * posture on a practice session, not a JWT mode.
 */

import { useModeStore, type AppMode } from "@/stores/modeStore";

export type OperatorModeName = "Practice" | "Connected (read)" | "Live";

let connectedReadPosture = false;

/** Publish the Mode chip's Connected (read) posture for non-React readers. */
export function setConnectedReadPosture(active: boolean): void {
  connectedReadPosture = active;
}

export function operatorModeName(
  mode: AppMode = useModeStore.getState().mode,
  connectedRead: boolean = connectedReadPosture,
): OperatorModeName {
  if (mode === "live") return "Live";
  if (connectedRead && mode === "practice") return "Connected (read)";
  return "Practice";
}

/** Retired mode label that must not reach an operator. */
export function visibleServiceNote(note: string | undefined): string | undefined {
  if (note === "Explore") return operatorModeName();
  return note;
}
