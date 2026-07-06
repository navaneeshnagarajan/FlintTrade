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
    needs_relogin: !!account.needs_relogin,
    login_retryable: !!account.login_retryable,
  };
}

export async function listGatewayBrokerAccounts(): Promise<BrokerAccount[]> {
  return gatewayApi.listAccounts();
}

export async function listBrokerAccounts(previous: BrokerAccount[] = []): Promise<BrokerAccount[]> {
  const [gatewayResult, nativeResult] = await Promise.allSettled([
    listGatewayBrokerAccounts(),
    listNativeAccounts(),
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
    ? nativeResult.value.map(nativeToBrokerAccount)
    : previous.filter((a) => a.source === "native");
  return [...gatewayAccounts, ...nativeAccounts];
}

export async function listLiveNativeReadAccounts(): Promise<NativeReadAccountRef[]> {
  return (await listNativeAccounts())
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
  if (active && (active.source ?? "gateway") === "native") {
    const selected = accounts.find((account) => (
      account.account_id === active.account_id && account.adapter_id === active.broker
    ));
    if (selected) return selected;
  }
  return accounts.find((account) => account.is_primary) ?? accounts[0];
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
