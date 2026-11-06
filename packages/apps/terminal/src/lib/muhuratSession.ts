/**
 * NSE F&O Muhurat session for Sunday 8 Nov 2026.
 *
 * Pre-open 14:05–14:20 IST. F&O normal market 14:20–15:40 IST.
 * An empty special-session list stays closed. This module does not
 * invent an open window when that record is absent.
 */

import type { Holiday } from "@/types/api";
import { istMinutes, istParts, toIstIsoDate } from "@/lib/ist";

const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;
const PRE_OPEN_LEAD_MINUTES = 15;
const EQUITY_AMO_BEFORE_PRE_OPEN_MINUTES = 2;
const FO_AMO_BEFORE_PRE_OPEN_MINUTES = 3;
const FO_AMO_BEFORE_NORMAL_OPEN_MINUTES = 4;

export const MUHURAT_2026_DATE = "2026-11-08";
export const MUHURAT_2026_PRE_OPEN_MIN = 14 * 60 + 5;
export const MUHURAT_2026_FO_OPEN_MIN = 14 * 60 + 20;
export const MUHURAT_2026_FO_CLOSE_MIN = 15 * 60 + 40;

export const MUHURAT_FUNDS_NOTE =
  "F&O credits and intraday equity profits from 6 November 2026 are not included in available funds during this Muhurat session. The settlement holiday keeps those credits on the ledger.";

function istEpochMs(hour: number, minute: number, second = 0, ms = 0): number {
  return Date.UTC(2026, 10, 8, hour, minute, second, ms) - IST_OFFSET_MS;
}

function fmtMin(minutes: number): string {
  const hour = Math.floor(minutes / 60);
  const minute = minutes % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

/** Shipped special-session row. Callers that pass an empty list do not receive this. */
export function shippedMuhuratHolidays(): Holiday[] {
  return [
    {
      date: MUHURAT_2026_DATE,
      description: "Muhurat Trading",
      holiday_type: "SPECIAL_SESSION",
      closed_exchanges: [],
      open_exchanges: [
        {
          exchange: "NFO",
          start_time: istEpochMs(14, 20),
          end_time: istEpochMs(15, 40, 59, 999),
        },
        {
          exchange: "BFO",
          start_time: istEpochMs(14, 20),
          end_time: istEpochMs(15, 40, 59, 999),
        },
        {
          exchange: "NSE",
          start_time: istEpochMs(14, 20),
          end_time: istEpochMs(15, 40, 59, 999),
        },
        {
          exchange: "BSE",
          start_time: istEpochMs(14, 20),
          end_time: istEpochMs(15, 40, 59, 999),
        },
      ],
    },
  ];
}

export interface FoSessionWindow {
  date: string;
  openMin: number;
  closeMin: number;
}

function epochToIstMinutes(value: number): number | null {
  if (!Number.isFinite(value) || value < 1_000_000_000) return null;
  const ms = value < 100_000_000_000 ? value * 1_000 : value;
  const parts = istParts(new Date(ms));
  return parts.hour * 60 + parts.minute;
}

/**
 * Special-session windows for this instant.
 *
 * Omitting the calendar uses the shipped Muhurat row. An explicit list is
 * the only source: an empty list, or a list with no usable window, is absent.
 */
export function foSessionWindow(
  now: Date,
  holidays?: readonly Holiday[],
): FoSessionWindow | null {
  const calendar = holidays === undefined ? shippedMuhuratHolidays() : holidays;
  const dateKey = toIstIsoDate(now);
  for (const row of calendar) {
    if (row.date !== dateKey) continue;
    if (String(row.holiday_type).toUpperCase() !== "SPECIAL_SESSION") continue;
    for (const session of row.open_exchanges) {
      const exchange = session.exchange.trim().toUpperCase();
      if (exchange !== "NFO" && exchange !== "NSE" && exchange !== "BFO" && exchange !== "BSE") {
        continue;
      }
      const openMin = epochToIstMinutes(session.start_time);
      const closeMin = epochToIstMinutes(session.end_time);
      if (openMin === null || closeMin === null || closeMin < openMin) continue;
      return { date: row.date, openMin, closeMin };
    }
  }
  return null;
}

export type FoSessionState = "open" | "closed" | "absent";

export function foSessionState(now: Date, holidays?: readonly Holiday[]): FoSessionState {
  const window = foSessionWindow(now, holidays);
  if (!window) return "absent";
  const minutes = Math.floor(istMinutes(now));
  if (minutes >= window.openMin && minutes <= window.closeMin) return "open";
  return "closed";
}

export function foSessionTitle(window: FoSessionWindow): string {
  return `Open · F&O ${fmtMin(window.openMin)}–${fmtMin(window.closeMin)} IST`;
}

export function foSessionTimeline(window: FoSessionWindow): string {
  const preOpen = window.openMin - PRE_OPEN_LEAD_MINUTES;
  return `F&O Muhurat ${fmtMin(window.openMin)}–${fmtMin(window.closeMin)} IST. Pre-open ${fmtMin(preOpen)}–${fmtMin(window.openMin)}.`;
}

/** Trade-desk after-market-order note. Null once the session is open, after it, or when data is absent. */
export function muhuratAmoNote(now: Date = new Date(), holidays?: readonly Holiday[]): string | null {
  const window = foSessionWindow(now, holidays);
  if (!window) return null;
  const minutes = Math.floor(istMinutes(now));
  if (minutes >= window.openMin) return null;
  const preOpen = window.openMin - PRE_OPEN_LEAD_MINUTES;
  const equityCutoff = preOpen - EQUITY_AMO_BEFORE_PRE_OPEN_MINUTES;
  const foPreCutoff = preOpen - FO_AMO_BEFORE_PRE_OPEN_MINUTES;
  const foNormalCutoff = window.openMin - FO_AMO_BEFORE_NORMAL_OPEN_MINUTES;
  const openLabel = fmtMin(window.openMin);
  const preLabel = fmtMin(preOpen);
  const equityLabel = fmtMin(equityCutoff);
  const foPreLabel = fmtMin(foPreCutoff);
  const foNormalLabel = fmtMin(foNormalCutoff);
  if (minutes <= foPreCutoff) {
    return `F&O after-market orders for the Muhurat session are collected until ${foPreLabel} IST, 3 minutes before pre-open, and until ${foNormalLabel} IST, 4 minutes before the ${openLabel} normal open. Equity after-market orders are collected until ${equityLabel} IST, 2 minutes before the ${preLabel} equity pre-open.`;
  }
  if (minutes <= equityCutoff) {
    return `F&O after-market orders for Muhurat pre-open have closed. Orders for the ${openLabel} normal open are collected until ${foNormalLabel} IST. Equity after-market orders are collected until ${equityLabel} IST.`;
  }
  if (minutes <= foNormalCutoff) {
    return `Equity after-market orders for the Muhurat session have closed. F&O after-market orders for the ${openLabel} normal open are collected until ${foNormalLabel} IST.`;
  }
  return `After-market orders for the Muhurat session have closed. F&O opens at ${openLabel} IST.`;
}

/** Funds note during the open Muhurat session. Absent data produces no note. */
export function muhuratFundsNote(now: Date = new Date(), holidays?: readonly Holiday[]): string | null {
  const window = foSessionWindow(now, holidays);
  if (!window || window.date !== MUHURAT_2026_DATE) return null;
  if (foSessionState(now, holidays) !== "open") return null;
  return MUHURAT_FUNDS_NOTE;
}
