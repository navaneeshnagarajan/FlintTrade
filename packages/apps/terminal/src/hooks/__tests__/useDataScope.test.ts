import { describe, expect, it } from "vitest";

import { connectionScopeFingerprint, resolveDataScope } from "@/hooks/useDataScope";
import type { BrokerAccount } from "@/types/broker";

function account(overrides: Partial<BrokerAccount>): BrokerAccount {
  return {
    account_id: "A1",
    broker: "dhan",
    label: "Primary",
    status: "connected",
    connected_at: null,
    error_message: null,
    is_primary: false,
    source: "native",
    ...overrides,
  };
}

describe("resolveDataScope", () => {
  it("keeps Explore synthetic even when OpenAlgo is configured", () => {
    expect(resolveDataScope({
      mode: "explore",
      host: "http://127.0.0.1:5000",
      apiKey: "configured",
      accounts: [account({})],
      activeAccountId: "native:dhan:A1",
    })).toBe("explore:mock");
  });

  it("keeps Practice on its account-independent sandbox", () => {
    expect(resolveDataScope({
      mode: "practice",
      host: "http://127.0.0.1:5000",
      apiKey: "configured",
      accounts: [account({})],
      activeAccountId: "native:dhan:A1",
    })).toBe("practice:sandbox:default");
  });

  it("isolates OpenAlgo caches by host and key without retaining either value", () => {
    const first = resolveDataScope({
      mode: "live",
      host: "http://127.0.0.1:5000/",
      apiKey: "configured",
      accounts: [account({})],
      activeAccountId: "native:dhan:A1",
    });
    const second = resolveDataScope({
      mode: "live",
      host: "http://127.0.0.1:5001",
      apiKey: "configured",
      accounts: [account({})],
      activeAccountId: "native:dhan:A1",
    });
    const third = resolveDataScope({
      mode: "live",
      host: "http://127.0.0.1:5000",
      apiKey: "replacement",
      accounts: [account({})],
      activeAccountId: "native:dhan:A1",
    });

    expect(first).toMatch(/^live:openalgo:[0-9a-f]{16}$/);
    expect(first).not.toContain("configured");
    expect(first).not.toContain("127.0.0.1");
    expect(new Set([first, second, third])).toHaveLength(3);
    expect(connectionScopeFingerprint("http://127.0.0.1:5000/", "configured"))
      .toBe(connectionScopeFingerprint("http://127.0.0.1:5000", "configured"));
  });

  it("distinguishes same-id native accounts by source and broker", () => {
    const accounts = [
      account({ broker: "dhan", account_id: "SHARED" }),
      account({ broker: "upstox", account_id: "SHARED" }),
    ];
    expect(resolveDataScope({
      mode: "live",
      host: "",
      apiKey: "",
      accounts,
      activeAccountId: "native:upstox:SHARED",
    })).toBe("live:native:upstox:SHARED");
  });

  it("falls back to the primary connected native account", () => {
    expect(resolveDataScope({
      mode: "live",
      host: "",
      apiKey: "",
      accounts: [
        account({ account_id: "D1", status: "disconnected" }),
        account({ account_id: "U1", broker: "upstox", is_primary: true }),
      ],
      activeAccountId: null,
    })).toBe("live:native:upstox:U1");
  });
});
