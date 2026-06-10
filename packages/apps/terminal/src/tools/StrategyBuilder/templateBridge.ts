/**
 * templateBridge — hand-off contract between the StrategyTemplates widget
 * (terminal workspace, /trade) and the StrategyBuilderTool (Lab, /lab).
 *
 * The two surfaces are never mounted at the same time (separate routes), so
 * the widget stashes the selected template in sessionStorage and navigates to
 * the Lab; the builder reads-and-clears the stash on mount. A live custom
 * event is also dispatched for the case where a builder is already mounted
 * (tests, future embeddings).
 *
 * Offsets are expressed in strike-gap units relative to ATM (0 = ATM,
 * +1 = one gap above, -2 = two gaps below) so the builder can compute real
 * strikes for whichever underlying/ATM the operator has configured.
 */

export const PENDING_TEMPLATE_KEY = "flinttrade:pending-strategy-template";
export const LOAD_TEMPLATE_EVENT = "flinttrade:load-strategy-template";

export interface BuilderTemplateLeg {
  action: "BUY" | "SELL";
  optionType: "CE" | "PE";
  /** Strike offset from ATM in strike-gap units. */
  strikeOffset: number;
  lots: number;
}

export interface BuilderTemplate {
  id: string;
  name: string;
  legs: BuilderTemplateLeg[];
}

/** Persist a template for the builder to pick up after navigation. */
export function stashPendingTemplate(tmpl: BuilderTemplate): void {
  try {
    sessionStorage.setItem(PENDING_TEMPLATE_KEY, JSON.stringify(tmpl));
  } catch {
    // Storage unavailable — the live event may still reach a mounted builder.
  }
}

/** True when a stashed template is waiting for the builder. */
export function hasPendingTemplate(): boolean {
  try {
    return sessionStorage.getItem(PENDING_TEMPLATE_KEY) !== null;
  } catch {
    return false;
  }
}

function isValidLeg(leg: unknown): leg is BuilderTemplateLeg {
  if (leg === null || typeof leg !== "object") return false;
  const l = leg as Record<string, unknown>;
  return (
    (l.action === "BUY" || l.action === "SELL") &&
    (l.optionType === "CE" || l.optionType === "PE") &&
    typeof l.strikeOffset === "number" &&
    Number.isFinite(l.strikeOffset) &&
    typeof l.lots === "number" &&
    Number.isFinite(l.lots) &&
    l.lots >= 1
  );
}

/** Read and remove the stashed template; null when absent or malformed.
 *
 * Every leg is shape-validated — a corrupted stash would otherwise reach the
 * builder as `atm + NaN * gap` legs that `validateLegs` (which only checks
 * strike > 0) cannot catch. */
export function readAndClearPendingTemplate(): BuilderTemplate | null {
  try {
    const raw = sessionStorage.getItem(PENDING_TEMPLATE_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(PENDING_TEMPLATE_KEY);
    const parsed = JSON.parse(raw) as BuilderTemplate;
    if (!parsed || !Array.isArray(parsed.legs) || parsed.legs.length === 0) return null;
    if (!parsed.legs.every(isValidLeg)) return null;
    return parsed;
  } catch {
    return null;
  }
}
