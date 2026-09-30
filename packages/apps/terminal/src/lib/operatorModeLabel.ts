/**
 * Operator-facing session labels.
 *
 * Example is sample data. Practice, Connected (read), and Live name the
 * active Mode. Connected (read) is a chrome posture on a practice session,
 * not a JWT mode. The public web demo is not a Mode.
 */

import { useModeStore, type AppMode } from "@/stores/modeStore";

export const EXAMPLE_LABEL = "Example";
export const DEMO_EXAMPLE_LABEL = "Demo (example data)";

export type OperatorFacingLabel = "Example" | "Practice" | "Connected (read)" | "Live";

let connectedReadPosture = false;

/** Publish the Mode chip's Connected (read) posture for non-React readers. */
export function setConnectedReadPosture(active: boolean): void {
  connectedReadPosture = active;
}

/**
 * Label the active session.
 *
 * Explore is example data, never Practice. Practice means simulated fills.
 * Connected (read) applies only while that posture is on a practice session.
 */
export function operatorModeName(
  mode: AppMode = useModeStore.getState().mode,
  connectedRead: boolean = connectedReadPosture,
): OperatorFacingLabel {
  if (mode === "live") return "Live";
  if (mode === "practice" && connectedRead) return "Connected (read)";
  if (mode === "practice") return "Practice";
  return EXAMPLE_LABEL;
}

/** A leftover Explore service note is example data, not the active Mode. */
export function visibleServiceNote(note: string | undefined): string | undefined {
  if (note === "Explore") return EXAMPLE_LABEL;
  return note;
}
