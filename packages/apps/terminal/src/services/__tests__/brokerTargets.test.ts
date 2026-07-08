import { beforeEach, describe, expect, it } from "vitest";
import {
  assertNativeWriteTargetReadyOrThrow,
  hasUnconfirmedNativeActiveWriteTarget,
  NATIVE_TARGET_NOT_READY_MESSAGE,
  OPENALGO_CONFIG_LOADING_MESSAGE,
  pickNativeBrokerOrderTargetFromState,
  pickNativeWriteTargetFromState,
} from "../brokerTargets";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import type { BrokerAccount } from "@/types/broker";

const nativeUpstox = {
  account_id: "SHARED",
  broker: "upstox",
  source: "native" as const,
  status: "connected",
};

const nativeDhan = {
  account_id: "SHARED",
  broker: "dhan",
  source: "native" as const,
  status: "connected",
};

/** Build a full BrokerAccount for driving the real broker store in assert tests. */
function brokerAccount(overrides: Partial<BrokerAccount>): BrokerAccount {
  return {
    account_id: "U1",
    broker: "upstox",
    label: "Upstox",
    status: "connected",
    connected_at: null,
    error_message: null,
    is_primary: false,
    source: "native",
    ...overrides,
  };
}

describe("brokerTargets", () => {
  it("uses a composite active native account for direct live writes", () => {
    const active = brokerAccountKey(nativeUpstox);

    expect(pickNativeWriteTargetFromState("live", "", [nativeDhan, nativeUpstox], active, true)).toEqual({
      broker: "upstox",
      accountId: "SHARED",
    });
    expect(pickNativeBrokerOrderTargetFromState("live", "", [nativeDhan, nativeUpstox], active, true)).toEqual({
      broker: "upstox",
      account_id: "SHARED",
    });
  });

  it("does not guess a native write target from an ambiguous legacy bare id", () => {
    expect(pickNativeWriteTargetFromState("live", "", [nativeDhan, nativeUpstox], "SHARED", true)).toBeUndefined();
    expect(hasUnconfirmedNativeActiveWriteTarget("live", "", [nativeDhan, nativeUpstox], "SHARED")).toBe(false);
  });

  it("still accepts a unique legacy bare native id", () => {
    expect(pickNativeWriteTargetFromState("live", "", [nativeUpstox], "SHARED", true)).toEqual({
      broker: "upstox",
      accountId: "SHARED",
    });
  });

  it("fails closed for a selected read-only native account", () => {
    const readOnlyUpstox = { ...nativeUpstox, read_only: true };
    const active = brokerAccountKey(readOnlyUpstox);

    expect(pickNativeWriteTargetFromState("live", "", [readOnlyUpstox], active, true)).toBeUndefined();
    expect(pickNativeBrokerOrderTargetFromState("live", "", [readOnlyUpstox], active, true)).toBeUndefined();
    expect(hasUnconfirmedNativeActiveWriteTarget("live", "", [readOnlyUpstox], active)).toBe(true);
  });

  // ---- OpenAlgo hydration window (the apiKey-drop regression) ----

  it("never picks a native target while the OpenAlgo config is still hydrating", () => {
    // Post-reload the in-memory apiKey is transiently "" even when the OpenAlgo
    // bridge is the configured target. Picking the connected native account here
    // is exactly the HIGH: a bridge order would be silently diverted to native.
    const active = brokerAccountKey(nativeUpstox);

    expect(pickNativeWriteTargetFromState("live", "", [nativeUpstox], active, false)).toBeUndefined();
    expect(pickNativeBrokerOrderTargetFromState("live", "", [nativeUpstox], active, false)).toBeUndefined();
  });

  it("resumes native routing once hydration completes with a genuinely empty bridge key", () => {
    const active = brokerAccountKey(nativeUpstox);

    expect(pickNativeWriteTargetFromState("live", "", [nativeUpstox], active, true)).toEqual({
      broker: "upstox",
      accountId: "SHARED",
    });
  });
});

describe("assertNativeWriteTargetReadyOrThrow", () => {
  beforeEach(() => {
    useConnectionStore.setState(useConnectionStore.getInitialState());
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
  });

  it("blocks a live order until the OpenAlgo config has hydrated", () => {
    // Fresh store: openAlgoHydrated is false. A live order must fail closed with
    // the loading message rather than route on an empty apiKey.
    expect(useConnectionStore.getState().openAlgoHydrated).toBe(false);
    expect(() => assertNativeWriteTargetReadyOrThrow("live", "")).toThrow(OPENALGO_CONFIG_LOADING_MESSAGE);
  });

  it("does not block non-live orders during the hydration window", () => {
    expect(() => assertNativeWriteTargetReadyOrThrow("practice", "")).not.toThrow();
    expect(() => assertNativeWriteTargetReadyOrThrow("explore", "")).not.toThrow();
  });

  it("stops blocking once hydration completes", () => {
    useConnectionStore.getState().setOpenAlgoHydrated(true);
    expect(() => assertNativeWriteTargetReadyOrThrow("live", "")).not.toThrow();
  });

  it("throws the native-not-ready message (not the loading message) for an unconfirmed native account after hydration", () => {
    useConnectionStore.getState().setOpenAlgoHydrated(true);
    const disconnected = brokerAccount({ account_id: "U1", broker: "upstox", status: "disconnected" });
    useBrokerStore.setState({
      accounts: [disconnected],
      activeAccountId: brokerAccountKey(disconnected),
    });

    expect(() => assertNativeWriteTargetReadyOrThrow("live", "")).toThrow(NATIVE_TARGET_NOT_READY_MESSAGE);
  });
});
