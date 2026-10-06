import { beforeEach, describe, expect, it } from "vitest";
import { useBrokerStore } from "@/stores/brokerStore";
import {
  assertNativeWriteTargetReadyOrThrow,
  NATIVE_TARGET_NOT_READY_MESSAGE,
  pickNativeWriteTargetFromState,
} from "../brokerTargets";
import type { BrokerAccount } from "@/types/broker";
const account = (overrides: Partial<BrokerAccount> = {}): BrokerAccount => ({
  account_id: "A1", broker: "dhan", source: "native", label: "Dhan", status: "connected",
  connected_at: null, error_message: null, is_primary: true, ...overrides,
});
beforeEach(() => useBrokerStore.setState({ accounts: [], activeAccountId: null }));
describe("native write target", () => {
  it("routes the exact composite account with no connection credential gate", () => {
    expect(pickNativeWriteTargetFromState("live", "", [account()], "native:dhan:A1"))
      .toEqual({ broker: "dhan", accountId: "A1" });
  });
  it.each(["practice", "explore"])("never routes real writes in %s", (mode) => {
    expect(pickNativeWriteTargetFromState(mode, "", [account()], "native:dhan:A1")).toBeUndefined();
    expect(() => assertNativeWriteTargetReadyOrThrow(mode)).not.toThrow();
  });
  it.each([account({ status: "disconnected" }), account({ read_only: true }), account({ source: "gateway" })])
    ("rejects an unavailable or retired selection", (selected) => {
      useBrokerStore.setState({ accounts: [selected], activeAccountId: `${selected.source}:dhan:A1` });
      expect(() => assertNativeWriteTargetReadyOrThrow("live")).toThrow(NATIVE_TARGET_NOT_READY_MESSAGE);
    });
  it("rejects no selected account even when another native account is connected", () => {
    useBrokerStore.setState({ accounts: [account()], activeAccountId: null });
    expect(() => assertNativeWriteTargetReadyOrThrow("live")).toThrow(NATIVE_TARGET_NOT_READY_MESSAGE);
  });
  it("rejects even an unambiguous bare account selector", () => {
    expect(pickNativeWriteTargetFromState("live", "", [account()], "A1")).toBeUndefined();
  });
  it("rejects ambiguous old bare ids and preserves broker identity", () => {
    const accounts = [account(), account({ broker: "upstox" })];
    expect(pickNativeWriteTargetFromState("live", "", accounts, "A1")).toBeUndefined();
    expect(pickNativeWriteTargetFromState("live", "", accounts, "native:upstox:A1"))
      .toEqual({ broker: "upstox", accountId: "A1" });
  });
});
