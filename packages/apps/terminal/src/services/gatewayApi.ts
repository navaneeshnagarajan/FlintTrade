/**
 * FlintTrade Gateway REST API client.
 * Targets /ft-api/v1, proxied via /ft-api in dev (see vite.config.ts).
 * Handles legacy gateway account management and rate-limit settings only.
 * Broker connection flows live on the native /api/v1/native/accounts surface
 * or inside OpenAlgo; do not re-add direct /v1/auth/* connect calls here.
 *
 * All requests go through the shared bare-/v1 FT helpers so gateway management
 * calls use the same auth headers and response/error parsing as the rest of the
 * terminal client.
 */

import { delV1, getV1, postV1, putV1 } from "@/services/ftApi.helpers";
import type { BrokerInfo, BrokerAccount } from "@/types/broker";

async function gateway<T>(request: Promise<T>): Promise<T> {
  try {
    return await request;
  } catch (error) {
    if (error instanceof Error) throw new Error(`Gateway: ${error.message}`);
    throw error;
  }
}

/** Per-broker API rate limits in requests/sec (0 = unlimited). */
export type BrokerRateLimits = Record<string, { order: number; data: number }>;

export const gatewayApi = {
  listBrokers: () =>
    gateway(getV1<{ brokers: BrokerInfo[] }>("brokers")).then((r) => r.brokers),

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

  listAccounts: () =>
    gateway(getV1<{ accounts: BrokerAccount[] }>("accounts")).then((r) => r.accounts),

  removeAccount: (accountId: string) =>
    gateway(delV1<{ status: string }>(`accounts/${encodeURIComponent(accountId)}`)),

  reconnectAccount: (accountId: string) =>
    gateway(postV1<{ account: BrokerAccount }>(`accounts/${encodeURIComponent(accountId)}/reconnect`)),

  setPrimary: (accountId: string) =>
    gateway(postV1<{ account: BrokerAccount }>(`accounts/${encodeURIComponent(accountId)}/set-primary`)),
};
