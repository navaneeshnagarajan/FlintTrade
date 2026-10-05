import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";
import { useBrokerConnected, useDirectBrokerConnected } from "../useBrokerConnected";
const poll = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useBrokerAccounts", () => ({ useBrokerAccounts: poll }));
const account = (status: BrokerAccount["status"], source: BrokerAccount["source"] = "native"): BrokerAccount => ({
  broker: "dhan", account_id: "A1", label: "Dhan", status, source, connected_at: null,
  error_message: null, is_primary: true,
});
beforeEach(() => {
  useModeStore.setState({ mode: "live" });
  useBrokerStore.setState({ accounts: [], activeAccountId: null });
  useConnectionStore.setState({ status: "disconnected" });
  poll.mockClear();
});
describe("native broker connectivity", () => {
  it.each([useBrokerConnected, useDirectBrokerConnected])("requires a confirmed native session", (hook) => {
    const { result } = renderHook(hook);
    expect(result.current).toBe(false);
    act(() => useBrokerStore.setState({ accounts: [account("connected")] }));
    expect(result.current).toBe(true);
    act(() => useBrokerStore.setState({ accounts: [account("token_expired")] }));
    expect(result.current).toBe(false);
  });
  it.each(["disconnected", "error", "authenticating", "token_expired"] as const)("rejects native %s status", (status) => {
    useBrokerStore.setState({ accounts: [account(status)] });
    expect(renderHook(useBrokerConnected).result.current).toBe(false);
  });
  it("ignores retired connected snapshots and stale generic connection state", () => {
    useBrokerStore.setState({ accounts: [account("connected", "gateway")] });
    useConnectionStore.setState({ status: "connected" });
    expect(renderHook(useBrokerConnected).result.current).toBe(false);
  });
  it("keeps Explore independent of a connected live session", () => {
    useBrokerStore.setState({ accounts: [account("connected")] });
    useModeStore.setState({ mode: "explore" });
    expect(renderHook(useBrokerConnected).result.current).toBe(false);
  });
  it("uses the shared store without mounting account polling", () => {
    renderHook(useBrokerConnected); renderHook(useDirectBrokerConnected);
    expect(poll).not.toHaveBeenCalled();
  });
});
