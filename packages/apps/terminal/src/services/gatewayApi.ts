/**
 * FlintTrade Gateway REST API client.
 * Targets /ft-api/v1, proxied via /ft-api in dev (see vite.config.ts).
 * Handles broker account management, OAuth flows, OTP authentication.
 *
 * All requests go through the shared bare-/v1 FT helpers so gateway management
 * calls use the same auth headers and response/error parsing as the rest of the
 * terminal client.
 */

import { delV1, getV1, postV1, putV1 } from "@/services/ftApi.helpers";
import type { BrokerInfo, BrokerAccount, OAuthStartResponse } from "@/types/broker";

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

  addAccount: (
    broker: string,
    label: string,
    credentials: Record<string, string>,
  ) =>
    gateway(postV1<{ account: BrokerAccount }>("auth/credentials", {
      broker,
      label,
      credentials,
    })).then((r) => r.account),

  removeAccount: (accountId: string) =>
    gateway(delV1<{ status: string }>(`accounts/${encodeURIComponent(accountId)}`)),

  reconnectAccount: (accountId: string) =>
    gateway(postV1<{ account: BrokerAccount }>(`accounts/${encodeURIComponent(accountId)}/reconnect`)),

  setPrimary: (accountId: string) =>
    gateway(postV1<{ account: BrokerAccount }>(`accounts/${encodeURIComponent(accountId)}/set-primary`)),

  startOAuth: (broker: string, label: string) =>
    gateway(postV1<OAuthStartResponse>("auth/oauth/start", { broker, label })),

  requestOtp: (broker: string, accountId: string, clientId: string) =>
    gateway(postV1<{ status: string }>("auth/otp/request", {
      broker,
      account_id: accountId,
      client_id: clientId,
    })),

  verifyOtp: (broker: string, accountId: string, otp: string) =>
    gateway(postV1<{ account: BrokerAccount }>("auth/otp/verify", {
      // The route requires broker (400s without it) — thread it from the same
      // broker passed to requestOtp.
      broker,
      account_id: accountId,
      otp,
    })),
};
