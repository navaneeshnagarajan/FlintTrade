import { describe, it, expect, beforeEach } from "vitest";
import { brokerAccountKey, useBrokerStore } from "../brokerStore";
import type { BrokerAccount } from "@/types/broker";

const makeAccount = (overrides: Partial<BrokerAccount> = {}): BrokerAccount => ({
  account_id: "acc-1",
  broker: "zerodha",
  label: "Primary",
  status: "connected",
  connected_at: "2026-03-24T10:00:00Z",
  error_message: null,
  is_primary: false,
  ...overrides,
});

describe("brokerStore", () => {
  beforeEach(() => {
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
  });

  it("initial state has empty accounts", () => {
    const state = useBrokerStore.getState();
    expect(state.accounts).toEqual([]);
    expect(state.activeAccountId).toBeNull();
  });

  it("setAccounts replaces all", () => {
    const a1 = makeAccount({ account_id: "acc-1" });
    const a2 = makeAccount({ account_id: "acc-2" });
    useBrokerStore.getState().setAccounts([a1, a2]);
    expect(useBrokerStore.getState().accounts).toHaveLength(2);
    expect(useBrokerStore.getState().accounts[0].account_id).toBe("acc-1");
    expect(useBrokerStore.getState().accounts[1].account_id).toBe("acc-2");
  });

  it("setAccounts clears the active account when a poll no longer returns it", () => {
    const active = makeAccount({ account_id: "acc-1", broker: "dhan", source: "native" });
    const replacement = makeAccount({ account_id: "acc-2", broker: "upstox", source: "native" });
    useBrokerStore.getState().setAccounts([active]);
    useBrokerStore.getState().setActiveAccount(brokerAccountKey(active));

    useBrokerStore.getState().setAccounts([replacement]);

    expect(useBrokerStore.getState().activeAccountId).toBeNull();
  });

  it("setAccounts preserves the active account when a refreshed poll still returns it", () => {
    const active = makeAccount({ account_id: "acc-1", broker: "dhan", source: "native" });
    const refreshed = makeAccount({
      account_id: "acc-1",
      broker: "dhan",
      label: "Dhan refreshed",
      source: "native",
    });
    const activeKey = brokerAccountKey(active);
    useBrokerStore.getState().setAccounts([active]);
    useBrokerStore.getState().setActiveAccount(activeKey);

    useBrokerStore.getState().setAccounts([refreshed]);

    expect(useBrokerStore.getState().activeAccountId).toBe(activeKey);
  });

  it("addAccount appends", () => {
    const a1 = makeAccount({ account_id: "acc-1" });
    useBrokerStore.getState().addAccount(a1);
    const a2 = makeAccount({ account_id: "acc-2" });
    useBrokerStore.getState().addAccount(a2);
    expect(useBrokerStore.getState().accounts).toHaveLength(2);
  });

  it("removeAccount filters by id", () => {
    const a1 = makeAccount({ account_id: "acc-1" });
    const a2 = makeAccount({ account_id: "acc-2" });
    useBrokerStore.getState().setAccounts([a1, a2]);
    useBrokerStore.getState().removeAccount("acc-1");
    const { accounts } = useBrokerStore.getState();
    expect(accounts).toHaveLength(1);
    expect(accounts[0].account_id).toBe("acc-2");
  });

  it("removeAccount clears activeAccountId if removed", () => {
    const a1 = makeAccount({ account_id: "acc-1" });
    useBrokerStore.getState().addAccount(a1);
    useBrokerStore.getState().setActiveAccount("acc-1");
    expect(useBrokerStore.getState().activeAccountId).toBe("acc-1");
    useBrokerStore.getState().removeAccount("acc-1");
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
  });

  it("removeAccount can target one broker-aware account when ids collide", () => {
    const dhan = makeAccount({ account_id: "shared", broker: "dhan", label: "Dhan", source: "native" });
    const upstox = makeAccount({ account_id: "shared", broker: "upstox", label: "Upstox", source: "native" });
    useBrokerStore.getState().setAccounts([dhan, upstox]);
    useBrokerStore.getState().setActiveAccount(brokerAccountKey(upstox));

    useBrokerStore.getState().removeAccount(brokerAccountKey(upstox));

    expect(useBrokerStore.getState().accounts).toEqual([dhan]);
    expect(useBrokerStore.getState().activeAccountId).toBeNull();
  });

  it("updateAccount merges partial", () => {
    const a1 = makeAccount({ account_id: "acc-1", status: "connected" });
    useBrokerStore.getState().addAccount(a1);
    useBrokerStore.getState().updateAccount("acc-1", {
      status: "error",
      error_message: "Session expired",
    });
    const updated = useBrokerStore.getState().accounts[0];
    expect(updated.status).toBe("error");
    expect(updated.error_message).toBe("Session expired");
    expect(updated.broker).toBe("zerodha");
  });

  it("setActiveAccount", () => {
    useBrokerStore.getState().setActiveAccount("acc-42");
    expect(useBrokerStore.getState().activeAccountId).toBe("acc-42");
  });

  it("getPrimaryAccount returns primary", () => {
    const regular = makeAccount({ account_id: "acc-1", is_primary: false });
    const primary = makeAccount({ account_id: "acc-2", is_primary: true });
    useBrokerStore.getState().setAccounts([regular, primary]);
    const result = useBrokerStore.getState().getPrimaryAccount();
    expect(result?.account_id).toBe("acc-2");
  });

  it("getActiveAccount returns by activeAccountId", () => {
    const a1 = makeAccount({ account_id: "acc-1" });
    const a2 = makeAccount({ account_id: "acc-2" });
    useBrokerStore.getState().setAccounts([a1, a2]);
    useBrokerStore.getState().setActiveAccount("acc-2");
    const result = useBrokerStore.getState().getActiveAccount();
    expect(result?.account_id).toBe("acc-2");
  });

  it("getActiveAccount resolves broker-aware keys before legacy ids", () => {
    const dhan = makeAccount({ account_id: "shared", broker: "dhan", label: "Dhan", source: "native" });
    const upstox = makeAccount({ account_id: "shared", broker: "upstox", label: "Upstox", source: "native" });
    useBrokerStore.getState().setAccounts([dhan, upstox]);
    useBrokerStore.getState().setActiveAccount(brokerAccountKey(upstox));

    const result = useBrokerStore.getState().getActiveAccount();

    expect(result?.broker).toBe("upstox");
  });

  it("getActiveAccount returns undefined when no match", () => {
    const a1 = makeAccount({ account_id: "acc-1" });
    useBrokerStore.getState().addAccount(a1);
    useBrokerStore.getState().setActiveAccount("acc-999");
    const result = useBrokerStore.getState().getActiveAccount();
    expect(result).toBeUndefined();
  });
});
