/**
 * Tests for useTradingStoreSync.
 *
 * The hook mirrors the TanStack Query cache for funds + positions into
 * the Zustand tradingStore. Two contracts must hold:
 *   1. When useFunds / usePositions emit data, the corresponding
 *      updateFromFunds / updateFromPositions setters fire exactly once
 *      per data change.
 *   2. When data is undefined (loading state), no setter fires.
 *
 * The hook is called exactly once at the app root — its correctness is
 * the only thing that prevents the tradingStore mirror from drifting
 * from the TanStack cache.
 */

import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Funds, Position } from "@/types/api";

const mockUseFunds = vi.fn();
const mockUsePositions = vi.fn();
const mockUpdateFromFunds = vi.fn();
const mockUpdateFromPositions = vi.fn();

vi.mock("@/hooks/useFunds", () => ({
  useFunds: () => mockUseFunds(),
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => mockUsePositions(),
}));

vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: {
    getState: () => ({
      updateFromFunds: mockUpdateFromFunds,
      updateFromPositions: mockUpdateFromPositions,
    }),
  },
}));

// Imported after vi.mock so the mocks are in place when the hook pulls them.
import { useTradingStoreSync } from "@/hooks/useTradingStoreSync";

const FUNDS: Funds = {
  availableCash: 100000,
  usedMargin: 20000,
  totalBalance: 120000,
};

const POSITIONS: Position[] = [
  {
    symbol: "NIFTY25APRFUT",
    exchange: "NFO",
    product: "MIS",
    quantity: 50,
    averagePrice: 22000,
    ltp: 22100,
    pnl: 5000,
    pnlPercent: 0.45,
  },
];

describe("useTradingStoreSync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not fire setters while both queries are loading", () => {
    mockUseFunds.mockReturnValue({ data: undefined });
    mockUsePositions.mockReturnValue({ data: undefined });
    renderHook(() => useTradingStoreSync());
    expect(mockUpdateFromFunds).not.toHaveBeenCalled();
    expect(mockUpdateFromPositions).not.toHaveBeenCalled();
  });

  it("fires updateFromFunds exactly once per funds payload", () => {
    mockUseFunds.mockReturnValue({ data: FUNDS });
    mockUsePositions.mockReturnValue({ data: undefined });
    renderHook(() => useTradingStoreSync());
    expect(mockUpdateFromFunds).toHaveBeenCalledTimes(1);
    expect(mockUpdateFromFunds).toHaveBeenCalledWith(FUNDS);
    expect(mockUpdateFromPositions).not.toHaveBeenCalled();
  });

  it("fires updateFromPositions exactly once per positions payload", () => {
    mockUseFunds.mockReturnValue({ data: undefined });
    mockUsePositions.mockReturnValue({ data: POSITIONS });
    renderHook(() => useTradingStoreSync());
    expect(mockUpdateFromPositions).toHaveBeenCalledTimes(1);
    expect(mockUpdateFromPositions).toHaveBeenCalledWith(POSITIONS);
    expect(mockUpdateFromFunds).not.toHaveBeenCalled();
  });

  it("fires both setters when both queries have data", () => {
    mockUseFunds.mockReturnValue({ data: FUNDS });
    mockUsePositions.mockReturnValue({ data: POSITIONS });
    renderHook(() => useTradingStoreSync());
    expect(mockUpdateFromFunds).toHaveBeenCalledWith(FUNDS);
    expect(mockUpdateFromPositions).toHaveBeenCalledWith(POSITIONS);
  });

  it("does not re-fire setters on re-render when data reference is unchanged", () => {
    mockUseFunds.mockReturnValue({ data: FUNDS });
    mockUsePositions.mockReturnValue({ data: POSITIONS });
    const { rerender } = renderHook(() => useTradingStoreSync());
    rerender();
    rerender();
    expect(mockUpdateFromFunds).toHaveBeenCalledTimes(1);
    expect(mockUpdateFromPositions).toHaveBeenCalledTimes(1);
  });
});
