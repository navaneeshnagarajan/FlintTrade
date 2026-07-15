// ---------------------------------------------------------------------------
// OptionChain — formatting helpers and OI signal utilities
// ---------------------------------------------------------------------------

import type { OISignal, RawOptionRow } from "./types";

export const NUM  = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
export const NUM0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

export function fmtLtp(v: number | null | undefined): string {
  if (v == null) return "—";
  return NUM.format(v);
}

export function fmtOI(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (n >= 1_00_00_000) return `${(n / 1_00_00_000).toFixed(1)}Cr`;
  if (n >= 1_00_000)    return `${(n / 1_00_000).toFixed(1)}L`;
  if (n >= 1_000)       return `${(n / 1_000).toFixed(1)}K`;
  return NUM0.format(n);
}

export function fmtChg(v: number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
}

export function fmtDelta(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toFixed(3);
}

export function fmtGreek(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toFixed(4);
}

export function fmtIV(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

export function fmtExpiry(raw: string): string {
  if (!raw) return raw;
  try {
    const d = new Date(raw);
    if (isNaN(d.getTime())) return raw;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  } catch {
    return raw;
  }
}

/**
 * Classify OI signal from OiPulse patterns.
 * price change direction + OI change direction → signal type.
 */
export function getOISignal(row: RawOptionRow | null): OISignal {
  if (!row) return null;
  const chgPct = row.change_percent ?? row.change_pct ?? null;
  const oiChg  = row.oi_change ?? null;
  if (
    typeof chgPct !== "number"
    || typeof oiChg !== "number"
    || !Number.isFinite(chgPct)
    || !Number.isFinite(oiChg)
    || chgPct === 0
    || oiChg === 0
  ) return null;
  const priceUp = chgPct > 0;
  const oiUp    = oiChg > 0;
  if (priceUp  && oiUp)   return "Long Build Up";
  if (priceUp  && !oiUp)  return "Short Covering";
  if (!priceUp && !oiUp)  return "Long Unwinding";
  /* !priceUp && oiUp */  return "Short Build Up";
}

/** Tailwind classes for each OI signal type */
export function oiSignalStyle(signal: OISignal): string {
  switch (signal) {
    case "Long Build Up":   return "bg-profit/15 text-profit border-profit/30";
    case "Short Covering":  return "bg-warning/15 text-warning border-warning/30";
    case "Long Unwinding":  return "bg-orange-500/15 text-orange-400 border-orange-500/30";
    case "Short Build Up":  return "bg-loss/15 text-loss border-loss/30";
    default:                return "";
  }
}

/** Short label for badge */
export function oiSignalShort(signal: OISignal): string {
  switch (signal) {
    case "Long Build Up":  return "LBU";
    case "Short Covering": return "SCov";
    case "Long Unwinding": return "LU";
    case "Short Build Up": return "SBU";
    default:               return "";
  }
}
