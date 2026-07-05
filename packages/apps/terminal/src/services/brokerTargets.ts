import { isBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";

export interface NativeWriteTarget {
  broker: string;
  accountId: string;
}

export interface NativeBrokerOrderTarget {
  broker: string;
  account_id: string;
}

export interface NativeBrokerTargetAccount {
  account_id: string;
  broker: string;
  source?: "gateway" | "native";
  status?: string;
}

/**
 * Pick the active native account for live writes.
 *
 * OpenAlgo remains primary: when an OpenAlgo-compatible API key is configured,
 * callers should keep using the bridge path. Native writes are selected only in
 * live mode, with no bridge key, and with a connected active native account.
 */
export function pickNativeWriteTargetFromState(
  mode: string,
  apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
): NativeWriteTarget | undefined {
  if (mode !== "live" || apiKey.trim().length > 0) return undefined;

  const active = accounts.find((account) => isBrokerAccountMatch(account, activeAccountId));
  if (active?.source !== "native" || active.status !== "connected") return undefined;
  return { broker: active.broker, accountId: active.account_id };
}

export function pickNativeBrokerOrderTargetFromState(
  mode: string,
  apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
): NativeBrokerOrderTarget | undefined {
  const target = pickNativeWriteTargetFromState(mode, apiKey, accounts, activeAccountId);
  if (!target) return undefined;
  return { broker: target.broker, account_id: target.accountId };
}

export function pickNativeWriteTarget(mode: string, apiKey: string): NativeWriteTarget | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return pickNativeWriteTargetFromState(mode, apiKey, accounts, activeAccountId);
}

export function pickNativeBrokerOrderTarget(
  mode: string,
  apiKey: string,
): NativeBrokerOrderTarget | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return pickNativeBrokerOrderTargetFromState(mode, apiKey, accounts, activeAccountId);
}
