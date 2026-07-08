import { findBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";

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

/**
 * Pick the active native account for live writes.
 *
 * OpenAlgo remains primary: when an OpenAlgo-compatible API key is configured,
 * callers should keep using the bridge path. Native writes are selected only in
 * live mode, with no bridge key, and with a connected, trading-capable active
 * native account.
 *
 * `hydrated` is `connectionStore.openAlgoHydrated`. Until the OpenAlgo config
 * has been re-fetched over loopback after a page/webview reload, the in-memory
 * `apiKey` is empty regardless of whether the bridge is configured — so an
 * empty key here is NOT a reliable "no bridge" signal. During that window this
 * returns `undefined` (never picks a native target), so a bridge order can
 * never be silently diverted to a native account; live-order entrypoints
 * additionally block the request via {@link assertNativeWriteTargetReadyOrThrow}.
 */
export function pickNativeWriteTargetFromState(
  mode: string,
  apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
  hydrated: boolean,
): NativeWriteTarget | undefined {
  if (mode !== "live" || !hydrated || apiKey.trim().length > 0) return undefined;

  const active = findBrokerAccountMatch(accounts, activeAccountId);
  if (active?.source !== "native" || active.status !== "connected" || active.read_only === true) {
    return undefined;
  }
  return { broker: active.broker, accountId: active.account_id };
}

export function pickNativeBrokerOrderTargetFromState(
  mode: string,
  apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
  hydrated: boolean,
): NativeBrokerOrderTarget | undefined {
  const target = pickNativeWriteTargetFromState(mode, apiKey, accounts, activeAccountId, hydrated);
  if (!target) return undefined;
  return { broker: target.broker, account_id: target.accountId };
}

/**
 * True when native writes are in force (live mode, no bridge key) and the
 * operator's *selected* active account is native but not confirmed connected —
 * e.g. right after a reload, before the first account poll re-derives its live
 * status from the session, or when the selected native session is explicitly
 * read-only (Upstox Analytics tokens). Callers on the live-order path must fail
 * closed rather than fall through to the bare path, which the backend would
 * resolve to `brokers.execution.default` — silently routing the order to a
 * different target than the operator chose.
 */
export function hasUnconfirmedNativeActiveWriteTarget(
  mode: string,
  apiKey: string,
  accounts: NativeBrokerTargetAccount[],
  activeAccountId: string | null,
): boolean {
  if (mode !== "live" || apiKey.trim().length > 0) return false;
  const active = findBrokerAccountMatch(accounts, activeAccountId);
  return active?.source === "native" && (active.status !== "connected" || active.read_only === true);
}

export function pickNativeWriteTarget(mode: string, apiKey: string): NativeWriteTarget | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  const { openAlgoHydrated } = useConnectionStore.getState();
  return pickNativeWriteTargetFromState(mode, apiKey, accounts, activeAccountId, openAlgoHydrated);
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
  "Your selected native broker is not available for live writes — its session may still "
  + "be establishing, may need re-authentication, or may be read-only. Wait a moment, "
  + "reconnect it, or choose a trading-capable broker session in Settings → Brokers.";

/**
 * Shown when a live order is attempted before the OpenAlgo config has hydrated
 * (the post-reload window). Distinct from {@link NATIVE_TARGET_NOT_READY_MESSAGE}
 * so the operator is told to simply retry rather than to reconnect a broker.
 */
export const OPENALGO_CONFIG_LOADING_MESSAGE =
  "OpenAlgo configuration is still loading — your live order was not placed to avoid "
  + "routing it to the wrong broker. Wait a moment and try again.";

/**
 * Fail closed on EVERY live-order entrypoint. Throws when:
 *
 * 1. the OpenAlgo config has not yet hydrated in live mode — the in-memory
 *    `apiKey` is transiently empty after a reload, so bridge-vs-native routing
 *    cannot be resolved and a live order must not be routed either way; or
 * 2. the operator's selected active account is native but not confirmed
 *    connected, so no order path silently falls through to the bare route
 *    (which the backend resolves to `brokers.execution.default` — a different
 *    target than the operator chose).
 */
export function assertNativeWriteTargetReadyOrThrow(mode: string, apiKey: string): void {
  const { openAlgoHydrated } = useConnectionStore.getState();
  if (mode === "live" && !openAlgoHydrated) {
    throw new Error(OPENALGO_CONFIG_LOADING_MESSAGE);
  }
  if (nativeActiveWriteTargetIsUnconfirmed(mode, apiKey)) {
    throw new Error(NATIVE_TARGET_NOT_READY_MESSAGE);
  }
}

export function pickNativeBrokerOrderTarget(
  mode: string,
  apiKey: string,
): NativeBrokerOrderTarget | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  const { openAlgoHydrated } = useConnectionStore.getState();
  return pickNativeBrokerOrderTargetFromState(mode, apiKey, accounts, activeAccountId, openAlgoHydrated);
}
