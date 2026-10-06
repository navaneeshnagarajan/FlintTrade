import { brokerAccountKey, findBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";

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
  read_only?: boolean;
}

/** Resolve only the exact selected, connected, trading-capable native account. */
export function pickNativeWriteTargetFromState(
  mode: string,
  _apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
  _hydrated = true,
): NativeWriteTarget | undefined {
  if (mode !== "live") return undefined;
  const active = findBrokerAccountMatch(accounts, activeAccountId);
  if (active?.source !== "native" || activeAccountId !== brokerAccountKey(active)
    || active.status !== "connected" || active.read_only === true) {
    return undefined;
  }
  return { broker: active.broker, accountId: active.account_id };
}

export function pickNativeBrokerOrderTargetFromState(
  mode: string,
  apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
  hydrated = true,
): NativeBrokerOrderTarget | undefined {
  const target = pickNativeWriteTargetFromState(mode, apiKey, accounts, activeAccountId, hydrated);
  return target ? { broker: target.broker, account_id: target.accountId } : undefined;
}

/** Missing, stale, read-only and retired account selections all fail closed. */
export function hasUnconfirmedNativeActiveWriteTarget(
  mode: string,
  apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
): boolean {
  return mode === "live" && !pickNativeWriteTargetFromState(mode, apiKey, accounts, activeAccountId);
}

export function pickNativeWriteTarget(mode: string, apiKey = ""): NativeWriteTarget | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return pickNativeWriteTargetFromState(mode, apiKey, accounts, activeAccountId);
}

export function nativeActiveWriteTargetIsUnconfirmed(mode: string, apiKey = ""): boolean {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return hasUnconfirmedNativeActiveWriteTarget(mode, apiKey, accounts, activeAccountId);
}

export const NATIVE_TARGET_NOT_READY_MESSAGE =
  "Your selected native broker is not available for live writes — its session may still "
  + "be establishing, may need re-authentication, or may be read-only. Wait a moment, "
  + "reconnect it, or choose a trading-capable broker session in Settings → Brokers.";

/** Every Live entrypoint requires an exact confirmed native selection. */
export function assertNativeWriteTargetReadyOrThrow(mode: string, apiKey = ""): void {
  if (nativeActiveWriteTargetIsUnconfirmed(mode, apiKey)) throw new Error(NATIVE_TARGET_NOT_READY_MESSAGE);
}

export function pickNativeBrokerOrderTarget(mode: string, apiKey = ""): NativeBrokerOrderTarget | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return pickNativeBrokerOrderTargetFromState(mode, apiKey, accounts, activeAccountId);
}
