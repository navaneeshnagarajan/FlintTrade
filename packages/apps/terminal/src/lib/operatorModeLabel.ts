/**
 * Operator-facing session labels.
 *
 * Example is sample data. Practice and Live name the session Mode.
 * Connected (read) is a broker status, not a session label. The public web
 * demo is not a Mode.
 */

import type { SessionMode } from "@/lib/modeClaim";
import { useModeStore } from "@/stores/modeStore";

export const EXAMPLE_LABEL = "Example";
export const DEMO_EXAMPLE_LABEL = "Demo (example data)";

export type OperatorFacingLabel = "Example" | "Practice" | "Live";

/**
 * Label the active session.
 *
 * Explore is example data, never Practice. Practice means simulated fills.
 * Unavailable means the session mode could not be confirmed.
 */
export function operatorModeName(
  mode: SessionMode = useModeStore.getState().mode,
): OperatorFacingLabel | "Unavailable" {
  if (mode === "unavailable") return "Unavailable";
  if (mode === "live") return "Live";
  if (mode === "practice") return "Practice";
  return EXAMPLE_LABEL;
}

/** A leftover Explore service note is example data, not the active Mode. */
export function visibleServiceNote(note: string | undefined): string | undefined {
  if (note === "Explore") return EXAMPLE_LABEL;
  return note;
}
