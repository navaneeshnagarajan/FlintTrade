/**
 * pineBridge — hand-off contract between the Pine Script Editor (Lab,
 * "Pine Editor" tab) and the Strategy Builder's Pine tab (Lab, "Options
 * Builder" tab).
 *
 * The editor's compile output (Python) is display-and-copy only; execution
 * always happens in the Strategy Builder's sandboxed client-side Pine
 * interpreter. This bridge therefore carries the raw Pine SOURCE and never
 * compiled Python — a deliberate security boundary.
 *
 * The two surfaces are sibling Lab tabs and are never mounted at the same
 * time, so the editor stashes the draft in sessionStorage and the builder's
 * Pine tab reads-and-clears the stash on mount (mirroring templateBridge).
 * A live custom event is also dispatched for the case where a Pine tab is
 * already mounted (tests, future embeddings), plus a separate open-builder
 * event so the Lab shell can switch straight to the Options Builder tab once
 * it registers a listener.
 */

export const PENDING_PINE_DRAFT_KEY = "flinttrade:pending-pine-draft";
export const LOAD_PINE_DRAFT_EVENT = "flinttrade:load-pine-draft";
export const OPEN_STRATEGY_BUILDER_EVENT = "flinttrade:open-strategy-builder";

export interface PineDraft {
  /** Raw Pine Script source handed to the sandboxed interpreter. */
  source: string;
}

/** True when the value is a well-formed draft with non-blank Pine source. */
export function isPineDraft(value: unknown): value is PineDraft {
  if (value === null || typeof value !== "object") return false;
  const draft = value as Record<string, unknown>;
  return typeof draft.source === "string" && draft.source.trim().length > 0;
}

/** Persist a draft for the builder's Pine tab to pick up when it mounts. */
export function stashPendingPineDraft(draft: PineDraft): void {
  try {
    sessionStorage.setItem(PENDING_PINE_DRAFT_KEY, JSON.stringify(draft));
  } catch {
    // Storage unavailable — the live event may still reach a mounted Pine tab.
  }
}

/** True when a stashed draft is waiting for the builder. */
export function hasPendingPineDraft(): boolean {
  try {
    return sessionStorage.getItem(PENDING_PINE_DRAFT_KEY) !== null;
  } catch {
    return false;
  }
}

/** Read and remove the stashed draft; null when absent or malformed.
 *
 * The stash is shape-validated so a corrupted entry can never inject a
 * non-string (or blank) "source" into the interpreter's editor. */
export function readAndClearPendingPineDraft(): PineDraft | null {
  try {
    const raw = sessionStorage.getItem(PENDING_PINE_DRAFT_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(PENDING_PINE_DRAFT_KEY);
    const parsed: unknown = JSON.parse(raw);
    return isPineDraft(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * One-call hand-off used by the Pine Script Editor: stash the draft, notify
 * any already-mounted Pine tab, and ask the Lab shell to open the builder.
 *
 * Returns false (and does nothing) when the draft is blank or malformed.
 */
export function sendPineDraftToBuilder(draft: PineDraft): boolean {
  if (!isPineDraft(draft)) return false;
  stashPendingPineDraft(draft);
  window.dispatchEvent(new CustomEvent(LOAD_PINE_DRAFT_EVENT, { detail: draft }));
  window.dispatchEvent(new CustomEvent(OPEN_STRATEGY_BUILDER_EVENT));
  return true;
}
