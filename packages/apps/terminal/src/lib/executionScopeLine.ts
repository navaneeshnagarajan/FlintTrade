/**
 * The line above an app's widgets.
 *
 * Example is only the example or demo claim. An unconfirmed session says
 * Unavailable and asks the operator to sign in again or reload.
 */

import type { SessionMode } from "@/lib/modeClaim";
import { operatorModeName } from "@/lib/operatorModeLabel";

export const UNAVAILABLE_SESSION_COPY =
  "Session mode couldn't be confirmed. Sign in again or reload.";

const TESTING_SCOPE =
  "Testing · Practice research scope only. Terminal account and Live authority are unchanged.";

const TERMINAL_LINKING = "Linking changes selections, never execution authority.";

export function executionScopeLine(input: {
  app: string;
  mode: SessionMode;
  account?: string | null;
}): string {
  if (input.app === "testing") return TESTING_SCOPE;
  const linking = input.app === "terminal" ? ` · ${TERMINAL_LINKING}` : "";
  if (input.mode === "unavailable") {
    return `Unavailable · ${UNAVAILABLE_SESSION_COPY}${linking}`;
  }
  const account = input.account || "No execution account selected";
  return `${operatorModeName(input.mode)} · ${account}${linking}`;
}
