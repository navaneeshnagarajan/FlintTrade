import { gatewayApi } from "@/services/gatewayApi";
import {
  listNativeAccounts,
  removeNativeAccount,
  reloginNativeAccount,
  setPrimaryNativeAccount,
  type NativeAccount,
} from "@/services/ftApi.native";
import { findBrokerAccountMatch } from "@/stores/brokerStore";
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
    needs_relogin: !!account.needs_relogin,
    login_retryable: !!account.login_retryable,
  };
}

export async function listGatewayBrokerAccounts(signal?: AbortSignal): Promise<BrokerAccount[]> {
  return gatewayApi.listAccounts(signal);
}

export async function listNativeBrokerAccounts(signal?: AbortSignal): Promise<BrokerAccount[]> {
  return (await listNativeAccounts(signal)).map(nativeToBrokerAccount);
}

export async function listBrokerAccounts(
  previous: BrokerAccount[] = [],
  signal?: AbortSignal,
): Promise<BrokerAccount[]> {
  const [gatewayResult, nativeResult] = await Promise.allSettled([
    listGatewayBrokerAccounts(signal),
    listNativeBrokerAccounts(signal),
  ]);

  if (gatewayResult.status === "rejected" && nativeResult.status === "rejected") {
    throw gatewayResult.reason instanceof Error
      ? gatewayResult.reason
      : new Error("Could not list broker accounts");
  }

  const gatewayAccounts = gatewayResult.status === "fulfilled"
    ? gatewayResult.value
    : previous.filter((a) => a.source !== "native");
  const nativeAccounts = nativeResult.status === "fulfilled"
    ? nativeResult.value
    : previous.filter((a) => a.source === "native");
  return [...gatewayAccounts, ...nativeAccounts];
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
  const active = findBrokerAccountMatch(brokerAccounts, activeAccountId);
  if (activeAccountId) {
    if (!active || (active.source ?? "gateway") !== "native") return undefined;
    const selected = accounts.find((account) => (
      account.account_id === active.account_id && account.adapter_id === active.broker
    ));
    // Fail closed when the SELECTED native account has no live session (daily
    // token lapsed, dropped after a probe error): silently falling back to the
    // primary/first account would render a DIFFERENT real account's funds and
    // positions under the operator's selection with no affordance. Returning
    // undefined lets the caller surface the needs-relogin state instead.
    return selected;
  }

  const nativeBrokerAccounts = brokerAccounts.filter((account) => account.source === "native");
  const selectedBrokerAccount = nativeBrokerAccounts.find((account) => account.is_primary)
    ?? (nativeBrokerAccounts.length === 1 ? nativeBrokerAccounts[0] : undefined);
  if (!selectedBrokerAccount) return undefined;
  return accounts.find((account) => (
    account.account_id === selectedBrokerAccount.account_id
    && account.adapter_id === selectedBrokerAccount.broker
  ));
}

export async function removeBrokerAccount(account: BrokerAccountRef): Promise<void> {
  if (account.source === "native") {
    await removeNativeAccount(account.broker, account.account_id);
    return;
  }
  await gatewayApi.removeAccount(account.account_id);
}

export async function reconnectBrokerAccount(account: BrokerAccountRef): Promise<void> {
  if (account.source === "native") {
    await reloginNativeAccount(account.broker, account.account_id);
    return;
  }
  await gatewayApi.reconnectAccount(account.account_id);
}

export async function setPrimaryBrokerAccount(account: BrokerAccountRef): Promise<void> {
  if (account.source === "native") {
    await setPrimaryNativeAccount(account.broker, account.account_id);
    return;
  }
  await gatewayApi.setPrimary(account.account_id);
}
