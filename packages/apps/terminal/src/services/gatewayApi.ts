/**
 * FlintTrade Gateway REST API client.
 * Targets /ft-api/v1, proxied via /ft-api in dev (see vite.config.ts).
 * Handles native broker rate-limit settings.
 * Broker connection flows use the native /api/v1/native/accounts surface.
 *
 * All requests go through the shared bare-/v1 FT helpers so gateway management
 * calls use the same auth headers and response/error parsing as the rest of the
 * terminal client.
 */

import { FtApiError, getV1, putV1 } from "@/services/ftApi.helpers";

async function gateway<T>(request: Promise<T>): Promise<T> {
  try {
    return await request;
  } catch (error) {
    if (error instanceof FtApiError) throw new FtApiError(`Gateway: ${error.message}`, error.status, error.data);
    if (error instanceof Error) throw new Error(`Gateway: ${error.message}`);
    throw error;
  }
}

/** Per-broker API rate limits in requests/sec (0 = unlimited). */
export type BrokerRateLimits = Record<string, { order: number; data: number }>;

export const gatewayApi = {
  /** Live effective per-broker API rate limits (requests/sec). */
  getRateLimits: () =>
    gateway(getV1<{ limits: BrokerRateLimits }>("rate-limits")).then((r) => r.limits),

  /** Set a broker's order/data rate limit; applies live + persists. */
  setRateLimit: (brokerId: string, order: number | undefined, data: number | undefined) =>
    gateway(putV1<{ limits: BrokerRateLimits }>("rate-limits", {
      broker_id: brokerId,
      ...(order !== undefined ? { order } : {}),
      ...(data !== undefined ? { data } : {}),
    })).then((r) => r.limits),

};
