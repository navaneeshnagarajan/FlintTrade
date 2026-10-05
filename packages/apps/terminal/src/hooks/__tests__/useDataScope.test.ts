import { describe, expect, it } from "vitest";

import {
  resolveDataScope,
  resolveMarketDataScope,
} from "@/hooks/useDataScope";
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
  it("keeps Explore synthetic with connected native accounts", () => {
    expect(resolveDataScope({
      mode: "explore",
      accounts: [account({})],
      activeAccountId: "native:dhan:A1",
    })).toBe("explore:mock");
  });

  it("keeps Practice on its account-independent sandbox", () => {
    expect(resolveDataScope({
      mode: "practice",
      accounts: [account({})],
      activeAccountId: "native:dhan:A1",
    })).toBe("practice:sandbox:default");
  });

  it("partitions Practice market data by its exact native account", () => {
    const accounts = [account({}), account({ account_id: "B1" })];
    expect(resolveMarketDataScope({ mode: "practice", accounts, activeAccountId: "native:dhan:A1" }))
      .toBe("practice:native:dhan:A1");
    expect(resolveMarketDataScope({ mode: "practice", accounts, activeAccountId: "native:dhan:B1" }))
      .toBe("practice:native:dhan:B1");
  });

  it("does not let stale transport credentials change native authority", () => {
    const input = { mode: "live" as const, accounts: [account({})], activeAccountId: "native:dhan:A1" };
    const emptyLegacyFields = { ...input, host: "", apiKey: "" };
    const retiredLegacyFields = { ...input, host: "https://retired.invalid", apiKey: "stale" };
    expect(resolveDataScope(emptyLegacyFields)).toBe("live:native:dhan:A1");
    expect(resolveDataScope(retiredLegacyFields)).toBe("live:native:dhan:A1");
  });

  it("distinguishes same-id native accounts by source and broker", () => {
    const accounts = [
      account({ broker: "dhan", account_id: "SHARED" }),
      account({ broker: "upstox", account_id: "SHARED" }),
    ];
    expect(resolveDataScope({
      mode: "live",
      accounts,
      activeAccountId: "native:upstox:SHARED",
    })).toBe("live:native:upstox:SHARED");
  });

  it("falls back to the primary connected native account", () => {
    expect(resolveDataScope({
      mode: "live",
      accounts: [
        account({ account_id: "D1", status: "disconnected" }),
        account({ account_id: "U1", broker: "upstox", is_primary: true }),
      ],
      activeAccountId: null,
    })).toBe("live:native:upstox:U1");
  });

  it("keeps an unselected primary account scope stable after it disconnects", () => {
    const connected = [
      account({ account_id: "A1", is_primary: true, status: "connected" }),
      account({ account_id: "B2", broker: "upstox", status: "connected" }),
    ];
    const disconnected = connected.map((candidate) =>
      candidate.account_id === "A1" ? { ...candidate, status: "disconnected" as const } : candidate,
    );

    const before = resolveDataScope({
      mode: "live",
      accounts: connected,
      activeAccountId: null,
    });
    const after = resolveDataScope({
      mode: "live",
      accounts: disconnected,
      activeAccountId: null,
    });

    expect(before).toBe("live:native:dhan:A1");
    expect(after).toBe(before);
  });

  it("keeps the only native account scope when no active or primary selector exists", () => {
    const connected = account({ is_primary: false, status: "connected" });
    const disconnected = { ...connected, status: "disconnected" as const };

    expect(resolveDataScope({
      mode: "live",
      accounts: [connected],
      activeAccountId: null,
    })).toBe("live:native:dhan:A1");
    expect(resolveDataScope({
      mode: "live",
      accounts: [disconnected],
      activeAccountId: null,
    })).toBe("live:native:dhan:A1");
  });

  it("does not reuse a different connected account when native identity is ambiguous", () => {
    expect(resolveDataScope({
      mode: "live",
      accounts: [
        account({ account_id: "A1", status: "disconnected", is_primary: false }),
        account({ account_id: "B2", broker: "upstox", status: "connected", is_primary: false }),
      ],
      activeAccountId: null,
    })).toBe("live:unconfigured");
  });
});
