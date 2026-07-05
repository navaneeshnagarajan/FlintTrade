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

/**
 * True when native writes are in force (live mode, no bridge key) and the
 * operator's *selected* active account is native but not confirmed connected —
 * e.g. right after a reload, before the first account poll re-derives its live
 * status from the session. Callers on the live-order path must fail closed
 * rather than fall through to the bare path, which the backend would resolve to
 * `brokers.execution.default` — silently routing the order to a different target
 * than the operator chose.
 */
export function hasUnconfirmedNativeActiveWriteTarget(
  mode: string,
  apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
): boolean {
  if (mode !== "live" || apiKey.trim().length > 0) return false;
  const active = accounts.find((account) => isBrokerAccountMatch(account, activeAccountId));
  return active?.source === "native" && active.status !== "connected";
}

export function pickNativeWriteTarget(mode: string, apiKey: string): NativeWriteTarget | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return pickNativeWriteTargetFromState(mode, apiKey, accounts, activeAccountId);
}

/**
 * Store-reading wrapper for {@link hasUnconfirmedNativeActiveWriteTarget}.
 */
export function nativeActiveWriteTargetIsUnconfirmed(mode: string, apiKey: string): boolean {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return hasUnconfirmedNativeActiveWriteTarget(mode, apiKey, accounts, activeAccountId);
}

/** Standard fail-closed message shown when a native write target isn't ready. */
export const NATIVE_TARGET_NOT_READY_MESSAGE =
  "Your selected native broker isn't connected yet — its session is still being "
  + "established (this can happen right after a reload). Wait a moment and retry, or "
  + "reconnect it in Settings → Brokers.";

/**
 * Fail closed on EVERY live-order entrypoint: throw if the operator's selected
 * active account is native but not confirmed connected, so no order path silently
 * falls through to the bare route (which the backend resolves to
 * brokers.execution.default — a different target than the operator chose).
 */
export function assertNativeWriteTargetReadyOrThrow(mode: string, apiKey: string): void {
  if (nativeActiveWriteTargetIsUnconfirmed(mode, apiKey)) {
    throw new Error(NATIVE_TARGET_NOT_READY_MESSAGE);
  }
}

export function pickNativeBrokerOrderTarget(
  mode: string,
  apiKey: string,
): NativeBrokerOrderTarget | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return pickNativeBrokerOrderTargetFromState(mode, apiKey, accounts, activeAccountId);
}
