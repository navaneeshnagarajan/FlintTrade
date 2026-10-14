import { RING_BUFFER_DEFAULTS } from '@reticlehq/core';

/** Explicit per-session live-capture budgets. Omission retains published defaults. */
export interface CaptureRetention {
  maxEvents: number;
  maxAgeMs: number;
  maxBytes: number;
}
export const CAPTURE_RETENTION_LIMITS: Readonly<CaptureRetention> = Object.freeze({
  maxEvents: 100000,
  maxAgeMs: 600000,
  maxBytes: 67108864,
});
export const DEFAULT_CAPTURE_RETENTION: Readonly<CaptureRetention> = Object.freeze({
  maxEvents: RING_BUFFER_DEFAULTS.MAX_EVENTS,
  maxAgeMs: RING_BUFFER_DEFAULTS.MAX_AGE_MS,
  maxBytes: RING_BUFFER_DEFAULTS.MAX_BYTES,
});

/** Reject malformed/partial budgets; never silently fall back after an explicit request. */
export function captureRetention(value: unknown): Readonly<CaptureRetention> {
  if (value === undefined) return DEFAULT_CAPTURE_RETENTION;
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('captureRetention must be a complete bounded budget');
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(CAPTURE_RETENTION_LIMITS) as (keyof CaptureRetention)[];
  if (Object.keys(record).length !== keys.length) throw new Error('captureRetention has unknown/missing fields');
  for (const key of keys) {
    const n = record[key];
    if (typeof n !== 'number' || !Number.isSafeInteger(n) || n < 1 || n > CAPTURE_RETENTION_LIMITS[key]) {
      throw new Error(`captureRetention.${key} must be a positive integer <= ${CAPTURE_RETENTION_LIMITS[key]}`);
    }
  }
  return Object.freeze({maxEvents: record['maxEvents'] as number, maxAgeMs: record['maxAgeMs'] as number, maxBytes: record['maxBytes'] as number});
}

/** Read only at daemon startup, before any listener/state owner is opened. */
export function resolveCaptureRetention(option: unknown, env: string | undefined): Readonly<CaptureRetention> {
  if (option !== undefined) return captureRetention(option);
  if (env === undefined) return captureRetention(undefined);
  let parsed: unknown;
  try { parsed = JSON.parse(env); } catch { throw new Error('RETICLE_CAPTURE_RETENTION must be JSON'); }
  return captureRetention(parsed);
}
