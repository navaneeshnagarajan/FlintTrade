import type { SectorReturn, TF } from "./types";
import { TF_KEY } from "./types";

export function getThemeColor(varName: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
}

export function getReturnValue(item: SectorReturn, tf: TF): number | null {
  return item[TF_KEY[tf]] as number | null;
}

export function formatReturn(v: number | null): string {
  if (v === null) return "--";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function formatCr(v: number): string {
  if (Math.abs(v) >= 10000) return `₹${(v / 10000).toFixed(0)}k Cr`;
  if (Math.abs(v) >= 1000) return `₹${(v / 1000).toFixed(1)}k Cr`;
  return `₹${v.toFixed(0)} Cr`;
}

export function netColor(v: number): string {
  return v >= 0 ? "text-profit" : "text-loss";
}

export function formatOINum(v: number): string {
  if (Math.abs(v) >= 10000000) return `${(v / 10000000).toFixed(2)} Cr`;
  if (Math.abs(v) >= 100000) return `${(v / 100000).toFixed(2)} L`;
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)} K`;
  return v.toString();
}
