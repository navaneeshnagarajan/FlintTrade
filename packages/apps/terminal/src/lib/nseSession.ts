/**
 * NSE cash session clock — SEBI Closing Auction Session (CAS).
 *
 * Single source of truth for TopBar chips and Market Clock.
 * Through 6 Dec 2026 the clock is the August 2026 CAS (live from 3 Aug 2026
 * for F&O underlyings). From 7 Dec 2026 it follows NSE/CMTR/77355 and
 * NSE/FAOP/77356. The September 2026 consultation is not product UI.
 */

import { istParts, toIstIsoDate } from "@/lib/ist";
import { foSessionWindow } from "@/lib/muhuratSession";

/** Human-readable schedule vintage shown on chip titles before 7 Dec 2026. */
export const CAS_SCHEDULE_NOTE = "as of Aug 2026";

/** First IST date of the revised auction and F&O close. */
export const NSE_CAS_REVISION = "2026-12-07";

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

const REVISED_TIMELINE_NOTE =
  "Continuous (~09:15–15:30) → CAS 15:30–15:40 → Match 15:40–15:45 → Post-close 15:50–16:00. Non-CAS cash still CTS to 15:30.";

const REVISED_PHASE_WINDOW: Record<NseCashSessionPhase, string> = {
  continuous: "09:15–15:30",
  cas: "15:30–15:40",
  matching: "15:40–15:45",
  "post-close": "15:50–16:00",
  closed: "until 09:15 / after 16:00",
};

export interface NseCashSchedule {
  casStart: number;
  casEnd: number;
  matchingEnd: number;
  foClose: number;
  foSecondaryLabel: string;
  scheduleNote: string;
  timelineNote: string;
  phaseWindow: Record<NseCashSessionPhase, string>;
}

function preRevisionSchedule(): NseCashSchedule {
  return {
    casStart: NSE_CAS_START_MIN,
    casEnd: NSE_CAS_END_MIN,
    matchingEnd: NSE_MATCHING_END_MIN,
    foClose: NSE_FO_CLOSE_MIN,
    foSecondaryLabel: NSE_FO_SECONDARY_LABEL,
    scheduleNote: CAS_SCHEDULE_NOTE,
    timelineNote: NSE_CASH_TIMELINE_NOTE,
    phaseWindow: PHASE_WINDOW,
  };
}

/** Cash and F&O segment clock for an IST instant. A missing date is not used. */
export function nseCashSchedule(on: Date): NseCashSchedule {
  if (toIstIsoDate(on) < NSE_CAS_REVISION) return preRevisionSchedule();
  return {
    casStart: HM(15, 30),
    casEnd: HM(15, 40),
    matchingEnd: NSE_MATCHING_END_MIN,
    foClose: HM(15, 45),
    foSecondaryLabel: "F&O open · till 15:45",
    scheduleNote: "from 7 Dec 2026",
    timelineNote: REVISED_TIMELINE_NOTE,
    phaseWindow: REVISED_PHASE_WINDOW,
  };
}

/** Chip tooltip/title, e.g. `CAS · 15:15–15:35 (as of Aug 2026)`. */
export function formatNseCashSessionTitle(phase: NseCashSessionPhase, on?: Date): string {
  const schedule = on ? nseCashSchedule(on) : preRevisionSchedule();
  return `${NSE_CASH_PHASE_LABEL[phase]} · ${schedule.phaseWindow[phase]} (${schedule.scheduleNote})`;
}

export function nseCashPhaseAtMinutes(minutes: number, on?: Date): NseCashSessionPhase {
  const schedule = on ? nseCashSchedule(on) : preRevisionSchedule();
  if (minutes >= NSE_CONTINUOUS_START_MIN && minutes < schedule.casStart) {
    return "continuous";
  }
  if (minutes >= schedule.casStart && minutes < schedule.casEnd) {
    return "cas";
  }
  if (minutes >= schedule.casEnd && minutes < schedule.matchingEnd) {
    return "matching";
  }
  if (minutes >= schedule.matchingEnd && minutes < NSE_POST_CLOSE_END_MIN) {
    return "post-close";
  }
  return "closed";
}

function foSecondaryFor(minutes: number, weekday: boolean, schedule: NseCashSchedule): string | null {
  if (!weekday) return null;
  if (minutes >= schedule.casStart && minutes < schedule.foClose) {
    return schedule.foSecondaryLabel;
  }
  return null;
}

/** Resolve the cash session chip from an instant in Asia/Kolkata. */
export function resolveNseCashSession(now: Date = new Date()): NseCashSessionInfo {
  const parts = istParts(now);
  const weekday = parts.weekday >= 1 && parts.weekday <= 5;
  const minutes = parts.hour * 60 + parts.minute;
  const schedule = nseCashSchedule(now);
  const phase = weekday ? nseCashPhaseAtMinutes(minutes, now) : "closed";
  return {
    phase,
    label: NSE_CASH_PHASE_LABEL[phase],
    title: formatNseCashSessionTitle(phase, now),
    foSecondary: foSecondaryFor(minutes, weekday, schedule),
    isGreenOpen: phase === "continuous",
  };
}

/** Index underlyings that share the symbol catalogue used to read contract names. */
const INDEX_UNDERLYINGS = new Set([
  "NIFTY",
  "BANKNIFTY",
  "FINNIFTY",
  "MIDCPNIFTY",
  "SENSEX",
  "NIFTYIT",
  "NIFTYMETAL",
  "NIFTYPHARMA",
  "NIFTYAUTO",
  "NIFTYENERGY",
  "NIFTYREALTY",
  "NIFTYFMCG",
  "NIFTYINFRA",
  "INDIAVIX",
]);

const EXPIRY_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

function splitContractMonth(value: string): { underlying: string; expiry: string; rest: string } | null {
  for (let offset = 1; offset < value.length - 2; offset += 1) {
    const month = value.slice(offset, offset + 3);
    if (!EXPIRY_MONTHS.includes(month)) continue;
    const prefix = value.slice(0, offset);
    let nameEnd = prefix.length;
    while (nameEnd > 0 && /\d/.test(prefix[nameEnd - 1] ?? "")) nameEnd -= 1;
    const name = prefix.slice(0, nameEnd);
    const day = prefix.slice(nameEnd);
    if (!name || !/^[A-Z&]+$/.test(name) || day.length > 2) continue;
    return {
      underlying: name === "NIFTY50" ? "NIFTY" : name,
      expiry: day + month,
      rest: value.slice(offset + 3),
    };
  }
  return null;
}

function parseDerivativeContract(symbol: string): { underlying: string; expiry: string } | null {
  const value = symbol.trim().toUpperCase();
  const option = value.endsWith("CE") || value.endsWith("PE");
  const future = value.endsWith("FUT");
  if (!option && !future) return null;
  const fields = splitContractMonth(option ? value.slice(0, -2) : value.slice(0, -3));
  if (!fields) return null;
  const year = option ? fields.rest.slice(0, 2) : fields.rest;
  const strike = option ? fields.rest.slice(2) : "";
  if (!/^\d{2}$/.test(year)) return null;
  if (option && !/^\d+(\.\d+)?$/.test(strike)) return null;
  return { underlying: fields.underlying, expiry: `${fields.expiry}${year}` };
}

function expiryTokenToIso(token: string): string | null {
  const text = token.trim().toUpperCase();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const match = /^(\d{1,2})([A-Z]{3})(\d{2})$/.exec(text);
  if (!match) return null;
  const month = EXPIRY_MONTHS.indexOf(match[2] ?? "") + 1;
  const day = Number(match[1]);
  const year = 2000 + Number(match[3]);
  if (month <= 0 || day < 1 || day > 31) return null;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function listedContractExpiry(symbol: string, expiryCalendar: readonly string[] | undefined): string | null {
  if (!expiryCalendar || expiryCalendar.length === 0) return null;
  const parsed = parseDerivativeContract(symbol);
  if (!parsed) return null;
  const contractExpiry = expiryTokenToIso(parsed.expiry);
  if (!contractExpiry) return null;
  const listed = new Set(
    expiryCalendar.flatMap((item) => {
      const iso = expiryTokenToIso(item);
      return iso ? [iso] : [];
    }),
  );
  return listed.has(contractExpiry) ? contractExpiry : null;
}

/**
 * Close, in minutes from IST midnight, for one derivatives contract.
 *
 * Null means the contract stays shut: the expiry is unknown, or the symbol
 * is not a readable contract. Muhurat wins over the ordinary close. From
 * 7 Dec 2026 an NSE index contract stops at 15:30 on its own expiry day
 * when that date is on the calendar; stock derivatives stay open until
 * 15:45. BFO keeps 15:40.
 */
export function derivativeContractCloseMin(
  on: Date,
  symbol?: string,
  expiryCalendar?: readonly string[],
  exchange = "NFO",
): number | null {
  const venue = exchange.trim().toUpperCase();
  if (venue === "NFO" || venue === "BFO") {
    const special = foSessionWindow(on);
    if (special) return special.closeMin;
  }
  if (venue === "BFO") return NSE_FO_CLOSE_MIN;
  if (venue !== "NFO") return null;
  const schedule = nseCashSchedule(on);
  if (toIstIsoDate(on) < NSE_CAS_REVISION) return schedule.foClose;
  if (!symbol || !symbol.trim()) return schedule.foClose;
  const parsed = parseDerivativeContract(symbol);
  if (!parsed) return null;
  if (!INDEX_UNDERLYINGS.has(parsed.underlying)) {
    return /^[A-Z&]+$/.test(parsed.underlying) ? schedule.foClose : null;
  }
  const expiry = listedContractExpiry(symbol, expiryCalendar);
  if (!expiry) return null;
  if (expiry === toIstIsoDate(on)) return HM(15, 30);
  return schedule.foClose;
}
