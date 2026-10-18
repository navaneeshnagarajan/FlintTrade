/** App-root mirror contract through real queries/stores; only API I/O is inert.
 * Fetch decoding and actual consumer coverage live in tradingStoreScope.transport.integration.
 */
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Funds, Position } from "@/types/api";
import { useTradingStoreSync } from "@/hooks/useTradingStoreSync";
import { useTradingStore } from "@/stores/tradingStore";
import { PRIMARY_SCOPE, setAccountRuntime, resetAccountRuntime } from "@/test-utils/accountQueryHarness";

const mockGetFunds = vi.hoisted(() => vi.fn());
const mockGetPositions = vi.hoisted(() => vi.fn());
vi.mock("@/services/api", () => ({
  getFunds: (...args: unknown[]) => mockGetFunds(...args),
  getPositionbook: (...args: unknown[]) => mockGetPositions(...args),
}));

const FUNDS: Funds = { availableCash: 100000, usedMargin: 20000, totalBalance: 120000 };
const POSITIONS: Position[] = [{ symbol: "NIFTY", exchange: "NFO", product: "MIS", quantity: 50, averagePrice: 22000, ltp: 22100, pnl: 5000, pnlPercent: 0.45 }];
const clients: QueryClient[] = [];
function mount(enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return renderHook(() => { useTradingStoreSync(enabled); return useTradingStore(); }, { wrapper });
}
beforeEach(() => {
  mockGetFunds.mockReset().mockImplementation(() => new Promise(() => {}));
  mockGetPositions.mockReset().mockImplementation(() => new Promise(() => {}));
  useTradingStore.getState().resetSessionState();
  setAccountRuntime();
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  resetAccountRuntime();
  useTradingStore.getState().resetSessionState();
});

describe("useTradingStoreSync", () => {
  it("publishes loading rather than real zero while both queries are pending", () => {
    const { result } = mount();
    expect(result.current).toMatchObject({ scopeKey: PRIMARY_SCOPE, fundsStatus: "loading", positionsStatus: "loading" });
  });

  it("does not read a disconnected Live account", () => {
    setAccountRuntime({ accounts: [] });
    const { result } = mount();
    expect(result.current).toMatchObject({ fundsStatus: "unavailable", positionsStatus: "unavailable" });
    expect(mockGetFunds).not.toHaveBeenCalled();
    expect(mockGetPositions).not.toHaveBeenCalled();
  });

  it("reads the sandbox in Practice without a Live connection", () => {
    setAccountRuntime({ accounts: [], mode: "practice" });
    const { result } = mount();
    expect(result.current.scopeKey).toBe("practice:sandbox:default");
    expect(mockGetFunds.mock.calls[0][0].identity).toMatchObject({ mode: "practice", brokerType: "sandbox", accountId: "default" });
  });

  it("keeps Explore on local sample data without account reads", () => {
    setAccountRuntime({ mode: "explore" });
    const { result } = mount();
    expect(result.current).toMatchObject({ fundsStatus: "unavailable", positionsStatus: "unavailable" });
    expect(mockGetFunds).not.toHaveBeenCalled();
    expect(mockGetPositions).not.toHaveBeenCalled();
  });

  it("never reads or publishes when the auth session is inactive", () => {
    const { result } = mount(false);
    expect(result.current).toMatchObject({ scopeKey: null, fundsStatus: "unavailable", positionsStatus: "unavailable" });
    expect(mockGetFunds).not.toHaveBeenCalled();
    expect(mockGetPositions).not.toHaveBeenCalled();
  });

  it("funds become ready without turning pending positions into real zero", async () => {
    mockGetFunds.mockResolvedValue(FUNDS);
    const { result } = mount();
    await waitFor(() => expect(result.current).toMatchObject({ availableMargin: 100000, usedMargin: 20000, fundsStatus: "ready", positionsStatus: "loading" }));
  });

  it("positions become ready without turning pending funds into real zero", async () => {
    mockGetPositions.mockResolvedValue(POSITIONS);
    const { result } = mount();
    await waitFor(() => expect(result.current).toMatchObject({ totalPnl: 5000, positionCount: 1, positionsStatus: "ready", fundsStatus: "loading" }));
  });

  it("binds both resources to the same immutable captured account context", async () => {
    mockGetFunds.mockResolvedValue(FUNDS);
    mockGetPositions.mockResolvedValue(POSITIONS);
    const { result } = mount();
    await waitFor(() => expect(result.current).toMatchObject({ totalPnl: 5000, availableMargin: 100000, fundsStatus: "ready", positionsStatus: "ready" }));
    expect(mockGetFunds.mock.calls[0][0]).toBe(mockGetPositions.mock.calls[0][0]);
    expect(Object.isFrozen(mockGetFunds.mock.calls[0][0])).toBe(true);
  });

  it("does not reacquire unchanged data when the root re-renders", async () => {
    mockGetFunds.mockResolvedValue(FUNDS);
    mockGetPositions.mockResolvedValue(POSITIONS);
    const { result, rerender } = mount();
    await waitFor(() => expect(result.current.positionsStatus).toBe("ready"));
    rerender(); rerender();
    expect(mockGetFunds).toHaveBeenCalledTimes(1);
    expect(mockGetPositions).toHaveBeenCalledTimes(1);
    expect(result.current).toMatchObject({ totalPnl: 5000, availableMargin: 100000 });
  });
});
