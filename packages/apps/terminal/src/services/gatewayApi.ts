/**
 * FlintTrade Gateway REST API client.
 * Targets /ft-api/v1, proxied via /ft-api in dev (see vite.config.ts).
 * Handles broker account management, OAuth flows, OTP authentication.
 *
 * All requests attach the shared auth context via {@link buildHeaders} — the
 * backend's G9 guard requires the operator's session JWT on every gateway
 * management write (accounts, credentials, OAuth start, rate-limit config).
 */

import { buildHeaders } from "@/services/ftApi.helpers";
import type { BrokerInfo, BrokerAccount, OAuthStartResponse } from "@/types/broker";

const BASE = "/ft-api/v1";

async function extractErrorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({})) as Record<string, unknown>;
  const msg = (body?.message ?? body?.error) as string | undefined;
  return msg ?? `HTTP ${res.status}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: buildHeaders(false) });
  if (!res.ok) {
    const msg = await extractErrorMessage(res);
    throw new Error(`Gateway: ${msg}`);
  }
  return (await res.json()) as T;
}

async function post<T>(path: string, body?: object): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: buildHeaders(true),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const msg = await extractErrorMessage(res);
    throw new Error(`Gateway: ${msg}`);
  }
  return (await res.json()) as T;
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE", headers: buildHeaders(false) });
  if (!res.ok) {
    const msg = await extractErrorMessage(res);
    throw new Error(`Gateway: ${msg}`);
  }
  return (await res.json()) as T;
}

async function put<T>(path: string, body?: object): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: buildHeaders(true),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const msg = await extractErrorMessage(res);
    throw new Error(`Gateway: ${msg}`);
  }
  return (await res.json()) as T;
}

/** Per-broker API rate limits in requests/sec (0 = unlimited). */
export type BrokerRateLimits = Record<string, { order: number; data: number }>;

export const gatewayApi = {
  listBrokers: () =>
    get<{ brokers: BrokerInfo[] }>("/brokers").then((r) => r.brokers),

  /** Live effective per-broker API rate limits (requests/sec). */
  getRateLimits: () =>
    get<{ limits: BrokerRateLimits }>("/rate-limits").then((r) => r.limits),

  /** Set a broker's order/data rate limit; applies live + persists. */
  setRateLimit: (brokerId: string, order: number | undefined, data: number | undefined) =>
    put<{ limits: BrokerRateLimits }>("/rate-limits", {
      broker_id: brokerId,
      ...(order !== undefined ? { order } : {}),
      ...(data !== undefined ? { data } : {}),
    }).then((r) => r.limits),

  listAccounts: () =>
    get<{ accounts: BrokerAccount[] }>("/accounts").then((r) => r.accounts),

  addAccount: (
    broker: string,
    label: string,
    credentials: Record<string, string>,
  ) =>
    post<{ account: BrokerAccount }>("/auth/credentials", {
      broker,
      label,
      credentials,
    }).then((r) => r.account),

  removeAccount: (accountId: string) =>
    del<{ status: string }>(`/accounts/${encodeURIComponent(accountId)}`),

  reconnectAccount: (accountId: string) =>
    post<{ account: BrokerAccount }>(`/accounts/${encodeURIComponent(accountId)}/reconnect`),

  setPrimary: (accountId: string) =>
    post<{ account: BrokerAccount }>(`/accounts/${encodeURIComponent(accountId)}/set-primary`),

  startOAuth: (broker: string, label: string) =>
    post<OAuthStartResponse>("/auth/oauth/start", { broker, label }),

  requestOtp: (broker: string, accountId: string, clientId: string) =>
    post<{ status: string }>("/auth/otp/request", {
      broker,
      account_id: accountId,
      client_id: clientId,
    }),

  verifyOtp: (broker: string, accountId: string, otp: string) =>
    post<{ account: BrokerAccount }>("/auth/otp/verify", {
      // The route requires broker (400s without it) — thread it from the same
      // broker passed to requestOtp.
      broker,
      account_id: accountId,
      otp,
    }),
};
