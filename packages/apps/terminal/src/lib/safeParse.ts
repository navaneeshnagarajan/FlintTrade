/**
 * safeParse — Zod-validated JSON.parse helpers.
 *
 * All localStorage / sessionStorage reads and SSE/WebSocket message parses that
 * produce typed values should go through one of these helpers. Raw
 * `JSON.parse(raw) as SomeType` casts bypass the type system at runtime; if
 * storage is corrupted or an API shape changes the app silently operates on
 * wrong data. These helpers make corruption visible and recoverable.
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Core helpers
// ---------------------------------------------------------------------------

/**
 * Safely parse a JSON string with zod validation.
 * Returns the validated data or `undefined` if parsing or validation fails.
 */
export function safeParse<T>(
  raw: string | null | undefined,
  schema: z.ZodType<T>,
): T | undefined {
  if (!raw) return undefined;
  try {
    const parsed: unknown = JSON.parse(raw);
    const result = schema.safeParse(parsed);
    return result.success ? result.data : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Safely parse with a fallback value instead of `undefined`.
 * Equivalent to `safeParse(raw, schema) ?? fallback`.
 */
export function safeParseOr<T>(
  raw: string | null | undefined,
  schema: z.ZodType<T>,
  fallback: T,
): T {
  return safeParse(raw, schema) ?? fallback;
}

// ---------------------------------------------------------------------------
// Commonly reused schemas (shared across multiple call sites)
// ---------------------------------------------------------------------------

/** `{ done?: boolean; token?: string }` — SSE stream tokens from /ft-api */
export const sseTokenSchema = z.object({
  done: z.boolean().optional(),
  token: z.string().optional(),
});

/**
 * Persisted OHLCV cache entry.
 * `data` matches `FlintChartOhlcvBar` from `@flinttrade/design-system`.
 * `timestamp` is the epoch ms when the cache was written.
 */
export const ohlcvBarSchema = z.object({
  timestamp: z.number(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().optional(),
});

export const ohlcvCacheSchema = z.object({
  data: z.array(ohlcvBarSchema),
  timestamp: z.number(),
  scope: z.string().min(1),
});

/** Raw WebSocket envelope from OpenAlgo port 8765 */
export const wsMessageSchema = z.record(z.string(), z.unknown());
