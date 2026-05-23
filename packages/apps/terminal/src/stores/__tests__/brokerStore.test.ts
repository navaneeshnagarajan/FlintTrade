import { describe, it, expect, beforeEach } from "vitest";
import { useBrokerStore } from "../brokerStore";
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

  it("getActiveAccount returns undefined when no match", () => {
    const a1 = makeAccount({ account_id: "acc-1" });
    useBrokerStore.getState().addAccount(a1);
    useBrokerStore.getState().setActiveAccount("acc-999");
    const result = useBrokerStore.getState().getActiveAccount();
    expect(result).toBeUndefined();
  });
});
