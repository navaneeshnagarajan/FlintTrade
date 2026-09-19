/**
 * NSE cash session clock — SEBI Closing Auction Session (CAS).
 *
 * Single source of truth for TopBar chips and Market Clock (FT-CORE-001).
 * Hours are as of Aug 2026 (CAS live from 3 Aug 2026 for F&O underlyings).
 * The September 2026 consultation is not product UI.
 */

import { istParts } from "@/lib/ist";

/** Human-readable schedule vintage shown on chip titles. */
export const CAS_SCHEDULE_NOTE = "as of Aug 2026";

export type NseCashSessionPhase =
  | "continuous"
  | "cas"
  | "matching"
  | "post-close"
  | "closed";

export interface NseCashSessionInfo {
  phase: NseCashSessionPhase;
  label: string;
  title: string;
  /** Shown when equity F&O still runs after cash continuous ends. */
  foSecondary: string | null;
  /** True only during Continuous — never after 15:15 IST. */
  isGreenOpen: boolean;
}

const HM = (h: number, m: number): number => h * 60 + m;

/** Continuous matching on CAS names. */
export const NSE_CONTINUOUS_START_MIN = HM(9, 15);
export const NSE_CAS_START_MIN = HM(15, 15);
export const NSE_CAS_END_MIN = HM(15, 35);
export const NSE_MATCHING_END_MIN = HM(15, 50);
export const NSE_POST_CLOSE_END_MIN = HM(16, 0);
/** Equity F&O continuous close. */
export const NSE_FO_CLOSE_MIN = HM(15, 40);
/** Non-CAS cash still trades continuous to 15:30. */
export const NSE_NON_CAS_CTS_CLOSE_MIN = HM(15, 30);

export const NSE_CASH_PHASE_LABEL: Record<NseCashSessionPhase, string> = {
  continuous: "Continuous",
  cas: "CAS",
  matching: "Matching",
  "post-close": "Post-close",
  closed: "Closed",
};

const PHASE_WINDOW: Record<NseCashSessionPhase, string> = {
  continuous: "09:15–15:15",
  cas: "15:15–15:35",
  matching: "15:35–15:50",
  "post-close": "15:50–16:00",
  closed: "until 09:15 / after 16:00",
};

export const NSE_FO_SECONDARY_LABEL = "F&O open · till 15:40";

export const NSE_CASH_TIMELINE_NOTE =
  "Continuous (~09:15–15:15) → CAS 15:15–15:35 → Match → Post-close 15:50–16:00. Non-CAS cash still CTS to 15:30.";

/** Chip tooltip/title, e.g. `CAS · 15:15–15:35 (as of Aug 2026)`. */
export function formatNseCashSessionTitle(phase: NseCashSessionPhase): string {
  return `${NSE_CASH_PHASE_LABEL[phase]} · ${PHASE_WINDOW[phase]} (${CAS_SCHEDULE_NOTE})`;
}

export function nseCashPhaseAtMinutes(minutes: number): NseCashSessionPhase {
  if (minutes >= NSE_CONTINUOUS_START_MIN && minutes < NSE_CAS_START_MIN) {
    return "continuous";
  }
  if (minutes >= NSE_CAS_START_MIN && minutes < NSE_CAS_END_MIN) {
    return "cas";
  }
  if (minutes >= NSE_CAS_END_MIN && minutes < NSE_MATCHING_END_MIN) {
    return "matching";
  }
  if (minutes >= NSE_MATCHING_END_MIN && minutes < NSE_POST_CLOSE_END_MIN) {
    return "post-close";
  }
  return "closed";
}

function foSecondaryFor(minutes: number, weekday: boolean): string | null {
  if (!weekday) return null;
  if (minutes >= NSE_CAS_START_MIN && minutes < NSE_FO_CLOSE_MIN) {
    return NSE_FO_SECONDARY_LABEL;
  }
  return null;
}

/** Resolve the cash session chip from an instant in Asia/Kolkata. */
export function resolveNseCashSession(now: Date = new Date()): NseCashSessionInfo {
  const parts = istParts(now);
  const weekday = parts.weekday >= 1 && parts.weekday <= 5;
  const minutes = parts.hour * 60 + parts.minute;
  const phase = weekday ? nseCashPhaseAtMinutes(minutes) : "closed";
  return {
    phase,
    label: NSE_CASH_PHASE_LABEL[phase],
    title: formatNseCashSessionTitle(phase),
    foSecondary: foSecondaryFor(minutes, weekday),
    isGreenOpen: phase === "continuous",
  };
}
