import { describe, expect, it } from "vitest";
import {
  hasUnconfirmedNativeActiveWriteTarget,
  pickNativeBrokerOrderTargetFromState,
  pickNativeWriteTargetFromState,
} from "../brokerTargets";
import { brokerAccountKey } from "@/stores/brokerStore";

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

describe("brokerTargets", () => {
  it("uses a composite active native account for direct live writes", () => {
    const active = brokerAccountKey(nativeUpstox);

    expect(pickNativeWriteTargetFromState("live", "", [nativeDhan, nativeUpstox], active)).toEqual({
      broker: "upstox",
      accountId: "SHARED",
    });
    expect(pickNativeBrokerOrderTargetFromState("live", "", [nativeDhan, nativeUpstox], active)).toEqual({
      broker: "upstox",
      account_id: "SHARED",
    });
  });

  it("does not guess a native write target from an ambiguous legacy bare id", () => {
    expect(pickNativeWriteTargetFromState("live", "", [nativeDhan, nativeUpstox], "SHARED")).toBeUndefined();
    expect(hasUnconfirmedNativeActiveWriteTarget("live", "", [nativeDhan, nativeUpstox], "SHARED")).toBe(false);
  });

  it("still accepts a unique legacy bare native id", () => {
    expect(pickNativeWriteTargetFromState("live", "", [nativeUpstox], "SHARED")).toEqual({
      broker: "upstox",
      accountId: "SHARED",
    });
  });
});
