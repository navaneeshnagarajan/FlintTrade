/**
 * FlintTrade Gateway REST API client.
 * Targets /ft-api/v1, proxied via /ft-api in dev (see vite.config.ts).
 * Handles broker account management, OAuth flows, OTP authentication.
 */

import type { BrokerInfo, BrokerAccount, OAuthStartResponse } from "@/types/broker";

const BASE = "/ft-api/v1";

async function extractErrorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({})) as Record<string, unknown>;
  const msg = (body?.message ?? body?.error) as string | undefined;
  return msg ?? `HTTP ${res.status}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const msg = await extractErrorMessage(res);
    throw new Error(`Gateway: ${msg}`);
  }
  return (await res.json()) as T;
}

async function post<T>(path: string, body?: object): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const msg = await extractErrorMessage(res);
    throw new Error(`Gateway: ${msg}`);
  }
  return (await res.json()) as T;
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) {
    const msg = await extractErrorMessage(res);
    throw new Error(`Gateway: ${msg}`);
  }
  return (await res.json()) as T;
}

export const gatewayApi = {
  listBrokers: () =>
    get<{ brokers: BrokerInfo[] }>("/brokers").then((r) => r.brokers),

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
    del<{ status: string }>(`/accounts/${accountId}`),

  reconnectAccount: (accountId: string) =>
    post<{ account: BrokerAccount }>(`/accounts/${accountId}/reconnect`),

  setPrimary: (accountId: string) =>
    post<{ account: BrokerAccount }>(`/accounts/${accountId}/set-primary`),

  startOAuth: (broker: string, label: string) =>
    post<OAuthStartResponse>("/auth/oauth/start", { broker, label }),

  requestOtp: (broker: string, accountId: string, clientId: string) =>
    post<{ status: string }>("/auth/otp/request", {
      broker,
      account_id: accountId,
      client_id: clientId,
    }),

  verifyOtp: (accountId: string, otp: string) =>
    post<{ account: BrokerAccount }>("/auth/otp/verify", {
      account_id: accountId,
      otp,
    }),
};
