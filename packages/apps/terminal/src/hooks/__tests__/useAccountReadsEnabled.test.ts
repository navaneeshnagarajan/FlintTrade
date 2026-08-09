import { describe, expect, it } from "vitest";

import {
  resolveAccountReadsEnabled,
  resolveScopedAccountReadsEnabled,
} from "@/hooks/useAccountReadsEnabled";
import type { BrokerAccount } from "@/types/broker";

const account = (overrides: Partial<BrokerAccount>): BrokerAccount => ({
  source: "native",
  account_id: "A1",
  broker: "dhan",
  label: "Primary",
  is_primary: true,
  status: "connected",
  connected_at: null,
  error_message: null,
  ...overrides,
});

describe("resolveAccountReadsEnabled", () => {
  it("keeps Explore on its labelled sample feed", () => {
    expect(resolveAccountReadsEnabled("explore", false)).toBe(false);
    expect(resolveAccountReadsEnabled("explore", true)).toBe(false);
  });

  it("reads the local sandbox in Practice without a broker connection", () => {
    expect(resolveAccountReadsEnabled("practice", false)).toBe(true);
    expect(resolveAccountReadsEnabled("practice", true)).toBe(true);
  });

  it("requires a connected broker for Live account reads", () => {
    expect(resolveAccountReadsEnabled("live", false)).toBe(false);
    expect(resolveAccountReadsEnabled("live", true)).toBe(true);
  });
});

describe("resolveScopedAccountReadsEnabled", () => {
  it("does not let another connected native account enable a disconnected primary source", () => {
    expect(resolveScopedAccountReadsEnabled({
      mode: "live",
      apiKey: "",
      openAlgoStatus: "disconnected",
      activeAccountId: null,
      accounts: [
        account({ status: "disconnected" }),
        account({
          account_id: "B2",
          broker: "upstox",
          label: "Secondary",
          is_primary: false,
        }),
      ],
    })).toBe(false);
  });

  it("follows the explicitly selected native account without cross-account reuse", () => {
    const accounts = [
      account({ status: "disconnected" }),
      account({
        account_id: "B2",
        broker: "upstox",
        label: "Secondary",
        is_primary: false,
      }),
    ];

    expect(resolveScopedAccountReadsEnabled({
      mode: "live",
      apiKey: "",
      openAlgoStatus: "disconnected",
      activeAccountId: "native:upstox:B2",
      accounts,
    })).toBe(true);
  });

  it("uses OpenAlgo connection truth whenever OpenAlgo owns the data scope", () => {
    expect(resolveScopedAccountReadsEnabled({
      mode: "live",
      apiKey: "configured-key",
      openAlgoStatus: "disconnected",
      activeAccountId: null,
      accounts: [account({})],
    })).toBe(false);
    expect(resolveScopedAccountReadsEnabled({
      mode: "live",
      apiKey: "configured-key",
      openAlgoStatus: "connected",
      activeAccountId: null,
      accounts: [account({ status: "disconnected" })],
    })).toBe(true);
  });
});
