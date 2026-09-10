/**
 * Time-of-day greeting for the home Welcome card.
 *
 * Buckets are Asia/Kolkata wall-clock hours via {@link istParts}, not the
 * browser's local ``getHours()``. A host in US Pacific at 12:01 IST is still
 * the previous evening locally — that is FT-HOME-001.
 *
 *   00:00–11:59 IST → Good morning
 *   12:00–16:59 IST → Good afternoon
 *   17:00–23:59 IST → Good evening
 */

import { istParts } from "@/lib/ist";

/**
 * Return the IST morning / afternoon / evening greeting for an instant.
 *
 * @param date - Instant to greet; defaults to now.
 * @returns British-English greeting for that Asia/Kolkata hour.
 */
export function getIstGreeting(date: Date = new Date()): string {
  const { hour } = istParts(date);
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}
