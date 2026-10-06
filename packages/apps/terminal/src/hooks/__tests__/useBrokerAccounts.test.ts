import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBrokerAccounts } from "../useBrokerAccounts";
import { useBrokerStore } from "@/stores/brokerStore";
import type { NativeAccount } from "@/services/ftApi.native";
const native = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/services/ftApi.native", () => ({ listNativeAccounts: native.list }));
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) { return createElement(QueryClientProvider, { client }, children); }
const account: NativeAccount = { adapter_id: "dhan", account_id: "A1", has_session: true, is_primary: true };
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  native.list.mockReset().mockResolvedValue([account]);
  useBrokerStore.setState({ accounts: [], activeAccountId: null });
});
afterEach(() => client.clear());
describe("native account poll", () => {
  it("does not read accounts in an unauthenticated or Explore session", async () => {
    renderHook(() => useBrokerAccounts(false), { wrapper });
    await act(async () => {});
    expect(native.list).not.toHaveBeenCalled();
    expect(useBrokerStore.getState().accounts).toEqual([]);
  });
  it("normalises native sessions and forwards the cancellation signal", async () => {
    renderHook(() => useBrokerAccounts(), { wrapper });
    await waitFor(() => expect(useBrokerStore.getState().accounts).toContainEqual(expect.objectContaining({ source: "native", broker: "dhan", account_id: "A1", status: "connected" })));
    expect(native.list).toHaveBeenCalledWith(expect.any(AbortSignal));
  });
  it("does not publish a late response after the session is disabled", async () => {
    let resolve!: (accounts: NativeAccount[]) => void;
    native.list.mockReturnValue(new Promise<NativeAccount[]>((done) => { resolve = done; }));
    const { rerender } = renderHook(({ enabled }) => useBrokerAccounts(enabled), { wrapper, initialProps: { enabled: true } });
    await waitFor(() => expect(native.list).toHaveBeenCalledOnce());
    rerender({ enabled: false });
    await act(async () => { resolve([account]); });
    expect(useBrokerStore.getState().accounts).toEqual([]);
  });
  it("marks retained native identity unavailable when discovery fails", async () => {
    const { result } = renderHook(() => useBrokerAccounts(), { wrapper });
    await waitFor(() => expect(useBrokerStore.getState().accounts).toHaveLength(1));
    useBrokerStore.getState().setActiveAccount("native:dhan:A1");
    native.list.mockRejectedValue(new Error("Native session discovery unavailable"));
    await act(async () => { await result.current.refetch(); });
    await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
    expect(useBrokerStore.getState().activeAccountId).toBe("native:dhan:A1");
    expect(useBrokerStore.getState().accounts[0]).toMatchObject({ source: "native", status: "error" });
  });
  it("recovers the same account and synchronises empty results", async () => {
    const { result } = renderHook(() => useBrokerAccounts(), { wrapper });
    await waitFor(() => expect(useBrokerStore.getState().accounts).toHaveLength(1));
    native.list.mockResolvedValue([]);
    await act(async () => { await result.current.refetch(); });
    await waitFor(() => expect(useBrokerStore.getState().accounts).toEqual([]));
  });
  it("retains the composite source and broker for same-id accounts", async () => {
    native.list.mockResolvedValue([account, { ...account, adapter_id: "upstox" }]);
    renderHook(() => useBrokerAccounts(), { wrapper });
    await waitFor(() => expect(useBrokerStore.getState().accounts).toHaveLength(2));
    useBrokerStore.getState().setActiveAccount("native:upstox:A1");
    expect(useBrokerStore.getState().getActiveAccount()?.broker).toBe("upstox");
  });
});
