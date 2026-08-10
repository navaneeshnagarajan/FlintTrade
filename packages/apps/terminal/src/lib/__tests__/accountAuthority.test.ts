import { describe, expect, it, vi } from "vitest";

import * as accountQueryStateModule from "@/lib/accountQueryState";
import type { AccountAuthorityIdentity } from "@/hooks/useDataScope";

type GuardModule = {
  captureAccountAuthority?: (identity: AccountAuthorityIdentity) => AccountAuthorityIdentity;
  accountAuthorityMatches?: (
    expected: AccountAuthorityIdentity,
    current: AccountAuthorityIdentity,
  ) => boolean;
  runWithMatchingAccountAuthority?: <T>(
    expected: AccountAuthorityIdentity,
    getCurrent: () => AccountAuthorityIdentity,
    callback: () => T,
  ) => T | undefined;
  runGuardedAccountRefetch?: (
    canRefetch: boolean,
    refetch: () => unknown,
  ) => void;
};

const guards = accountQueryStateModule as GuardModule;

const A: AccountAuthorityIdentity = {
  mode: "live",
  scopeKey: "live:native:dhan:A1",
  brokerType: "dhan",
  accountId: "A1",
};

const changed = (
  field: keyof AccountAuthorityIdentity,
  value: string,
): AccountAuthorityIdentity => ({ ...A, [field]: value });

describe("immutable account authority guards", () => {
  it("captures an immutable copy rather than a mutable render object", () => {
    expect(guards.captureAccountAuthority).toBeTypeOf("function");
    const original = { ...A };
    const captured = guards.captureAccountAuthority!(original);

    original.accountId = "B2";

    expect(captured).toEqual(A);
    expect(Object.isFrozen(captured)).toBe(true);
  });

  it("runs a callback only while all four identity fields still match", () => {
    expect(guards.runWithMatchingAccountAuthority).toBeTypeOf("function");
    const callback = vi.fn(() => "ran");

    expect(guards.runWithMatchingAccountAuthority!(A, () => ({ ...A }), callback)).toBe("ran");
    expect(callback).toHaveBeenCalledTimes(1);

    for (const [field, value] of [
      ["mode", "practice"],
      ["scopeKey", "live:native:upstox:B2"],
      ["brokerType", "upstox"],
      ["accountId", "B2"],
    ] as const) {
      expect(guards.runWithMatchingAccountAuthority!(A, () => changed(field, value), callback)).toBeUndefined();
    }
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it("executes the refetch callback only when the latest read gate permits it", () => {
    expect(guards.runGuardedAccountRefetch).toBeTypeOf("function");
    const refetch = vi.fn();

    guards.runGuardedAccountRefetch!(false, refetch);
    expect(refetch).not.toHaveBeenCalled();

    guards.runGuardedAccountRefetch!(true, refetch);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("reports exact equality only when mode, scope, broker, and account all match", () => {
    expect(guards.accountAuthorityMatches).toBeTypeOf("function");
    expect(guards.accountAuthorityMatches!(A, { ...A })).toBe(true);
    expect(guards.accountAuthorityMatches!(A, changed("mode", "practice"))).toBe(false);
    expect(guards.accountAuthorityMatches!(A, changed("scopeKey", "live:native:upstox:B2"))).toBe(false);
    expect(guards.accountAuthorityMatches!(A, changed("brokerType", "upstox"))).toBe(false);
    expect(guards.accountAuthorityMatches!(A, changed("accountId", "B2"))).toBe(false);
  });
});
