/**
 * Optional setup reminder on the Practice desk.
 *
 * Four cards: authenticator, broker, LLM, and trading defaults. Monitoring
 * is not a desk card (system health stays in Settings). Risk limits stay in
 * Settings → Risk Limits. Later / skipped cards persist across reloads.
 * Dismiss removes the desk strip and leaves the same reminder in Settings.
 */

export const PRACTICE_LATER_KEY = "flinttrade:setup-later";
export const OPTIONAL_SETUP_STATE_KEY = "flinttrade:setup-later-state";

export const OPTIONAL_SETUP_CARDS = [
  {
    id: "totp",
    title: "Two-factor authentication",
    detail: "Optional. Practice does not need an authenticator.",
    settingsSection: "security",
  },
  {
    id: "broker",
    title: "Broker connect",
    detail: "Optional. Practice does not need a broker.",
    settingsSection: "brokers",
  },
  {
    id: "llm",
    title: "LLM",
    detail: "Optional. You can choose a model later.",
    settingsSection: "llm",
  },
  {
    id: "trading",
    title: "Trading defaults",
    detail: "Optional. Defaults stay in Settings until you set them.",
    settingsSection: "trading",
  },
] as const;

export type OptionalSetupCardId = (typeof OPTIONAL_SETUP_CARDS)[number]["id"];

export interface OptionalSetupTrayState {
  skipped: OptionalSetupCardId[];
  completed: OptionalSetupCardId[];
  dismissed: boolean;
}

const CARD_IDS = new Set<string>(OPTIONAL_SETUP_CARDS.map((card) => card.id));

export function emptyOptionalSetupState(): OptionalSetupTrayState {
  return { skipped: [], completed: [], dismissed: false };
}

function asCardIds(value: unknown): OptionalSetupCardId[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<OptionalSetupCardId>();
  for (const entry of value) {
    if (typeof entry === "string" && CARD_IDS.has(entry)) {
      seen.add(entry as OptionalSetupCardId);
    }
  }
  return [...seen];
}

export function loadOptionalSetupState(): OptionalSetupTrayState {
  try {
    const raw = localStorage.getItem(OPTIONAL_SETUP_STATE_KEY);
    if (!raw) return emptyOptionalSetupState();
    const parsed = JSON.parse(raw) as Partial<OptionalSetupTrayState>;
    return {
      skipped: asCardIds(parsed.skipped),
      completed: asCardIds(parsed.completed),
      dismissed: parsed.dismissed === true,
    };
  } catch {
    return emptyOptionalSetupState();
  }
}

export function saveOptionalSetupState(state: OptionalSetupTrayState): void {
  try {
    localStorage.setItem(OPTIONAL_SETUP_STATE_KEY, JSON.stringify(state));
  } catch {
    // Storage quota or privacy mode — the desk still works for this visit.
  }
}

export function clearOptionalSetupState(): void {
  try {
    localStorage.removeItem(OPTIONAL_SETUP_STATE_KEY);
    localStorage.removeItem(PRACTICE_LATER_KEY);
  } catch {
    // Non-critical.
  }
}

/** Completed cards only. Skipping a card is not the same as finishing it. */
export function optionalSetupDoneCount(state: OptionalSetupTrayState): number {
  const done = new Set<OptionalSetupCardId>(state.completed);
  for (const id of state.skipped) done.delete(id);
  return done.size;
}

/** Skipped cards that are not also completed. */
export function optionalSetupSkippedCount(state: OptionalSetupTrayState): number {
  const skipped = new Set<OptionalSetupCardId>(state.skipped);
  for (const id of state.completed) skipped.delete(id);
  return skipped.size;
}

/** One-line reminder. `done` of `total` uses the live card count. */
export function optionalSetupStripLabel(
  done: number,
  skipped = 0,
  total = OPTIONAL_SETUP_CARDS.length,
): string {
  return `Optional setup · ${done} of ${total} done · ${skipped} skipped`;
}

export function markPracticeLaterPending(): void {
  try {
    localStorage.setItem(PRACTICE_LATER_KEY, "1");
  } catch {
    // Storage quota or privacy mode — the desk still opens.
  }
}

export function clearPracticeLaterPending(): void {
  try {
    localStorage.removeItem(PRACTICE_LATER_KEY);
  } catch {
    // Non-critical.
  }
}

export function practiceLaterPending(): boolean {
  try {
    return localStorage.getItem(PRACTICE_LATER_KEY) === "1";
  } catch {
    return false;
  }
}
