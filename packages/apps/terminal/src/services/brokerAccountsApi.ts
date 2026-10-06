import {
  listNativeAccounts,
  removeNativeAccount,
  reloginNativeAccount,
  setPrimaryNativeAccount,
  type NativeAccount,
} from "@/services/ftApi.native";
import { resolveNativeDataAccount } from "@/lib/marketDataScope";
import type { AccountStatus, BrokerAccount } from "@/types/broker";

export type BrokerAccountRef = Pick<BrokerAccount, "account_id" | "broker" | "source">;
export interface NativeReadAccountRef {
  adapter_id: string;
  account_id: string;
  is_primary: boolean;
}

function nativeStatus(account: NativeAccount): AccountStatus {
  if (account.has_session === true) return "connected";
  if (account.needs_relogin === true) return "token_expired";
  if (account.login_retryable === true) return "disconnected";
  return "disconnected";
}

export function nativeToBrokerAccount(account: NativeAccount): BrokerAccount {
  return {
    account_id: account.account_id,
    broker: account.adapter_id,
    label: account.label || account.account_id,
    status: nativeStatus(account),
    connected_at: null,
    error_message: account.login_error ?? null,
    is_primary: !!account.is_primary,
    source: "native",
    expires_at: account.expires_at ?? null,
    read_only: !!account.read_only,
    read_smoke_ok: account.read_smoke_ok === true,
    needs_relogin: !!account.needs_relogin,
    login_retryable: !!account.login_retryable,
  };
}

export async function listNativeBrokerAccounts(signal?: AbortSignal): Promise<BrokerAccount[]> {
  return (await listNativeAccounts(signal)).map(nativeToBrokerAccount);
}

export async function listBrokerAccounts(
  _previous: BrokerAccount[] = [],
  signal?: AbortSignal,
): Promise<BrokerAccount[]> {
  return listNativeBrokerAccounts(signal);
}

export async function listLiveNativeReadAccounts(signal?: AbortSignal): Promise<NativeReadAccountRef[]> {
  return (await listNativeAccounts(signal))
    .filter((account) => account.has_session === true)
    .map((account) => ({
      adapter_id: account.adapter_id,
      account_id: account.account_id,
      is_primary: !!account.is_primary,
    }));
}

export function selectNativeReadAccount(
  accounts: NativeReadAccountRef[],
  brokerAccounts: BrokerAccount[],
  activeAccountId: string | null,
): NativeReadAccountRef | undefined {
  const selected = resolveNativeDataAccount(brokerAccounts, activeAccountId);
  if (!selected) return undefined;
  // Intersect the chosen identity with fresh live sessions. Never fall back to
  // another account when that identity has no session: its data would appear
  // under the wrong selection and cache key.
  return accounts.find((account) => (
    account.account_id === selected.account_id && account.adapter_id === selected.broker
  ));
}

export async function removeBrokerAccount(account: BrokerAccountRef, idempotencyKey: string): Promise<void> {
  if (account.source === "native") {
    await removeNativeAccount(account.broker, account.account_id, idempotencyKey);
    return;
  }
  throw new Error("Only native broker accounts are supported.");
}

export async function reconnectBrokerAccount(account: BrokerAccountRef, idempotencyKey: string): Promise<void> {
  if (account.source === "native") {
    await reloginNativeAccount(account.broker, account.account_id, undefined, idempotencyKey);
    return;
  }
  throw new Error("Only native broker accounts are supported.");
}

export async function setPrimaryBrokerAccount(account: BrokerAccountRef, idempotencyKey: string): Promise<void> {
  if (account.source === "native") {
    await setPrimaryNativeAccount(account.broker, account.account_id, idempotencyKey);
    return;
  }
  throw new Error("Only native broker accounts are supported.");
}
