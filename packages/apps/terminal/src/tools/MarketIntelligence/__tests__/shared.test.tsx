import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
}));

import { useLiveSelector } from "../shared";

describe("useLiveSelector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("accepts only non-blank string expiries", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: [null, 0, "", "   ", " 2026-07-30 "] });

    const { result } = renderHook(() => useLiveSelector());

    await waitFor(() => expect(result.current.state.expiryLoading).toBe(false));
    expect(result.current.state.expiries).toEqual(["2026-07-30"]);
    expect(result.current.state.expiry).toBe("2026-07-30");
  });

  it("clears the prior expiry and expiry list when the next identity lookup fails", async () => {
    apiMocks.getExpiry.mockResolvedValueOnce({ expiry: ["2026-07-30"] });
    const { result } = renderHook(() => useLiveSelector());
    await waitFor(() => expect(result.current.state.expiry).toBe("2026-07-30"));

    apiMocks.getExpiry.mockRejectedValueOnce(new Error("expiry unavailable"));
    act(() => result.current.setSymbol("BANKNIFTY"));

    expect(result.current.state.expiry).toBeNull();
    expect(result.current.state.expiries).toEqual([]);
    await waitFor(() => expect(result.current.state.expiryLoading).toBe(false));
    expect(result.current.state.expiry).toBeNull();
    expect(result.current.state.expiries).toEqual([]);
  });

  it("never renders an expiry from the previous contract identity", async () => {
    apiMocks.getExpiry
      .mockResolvedValueOnce({ expiry: ["2026-07-30"] })
      .mockReturnValueOnce(new Promise(() => {}));
    const snapshots: Array<{ symbol: string; expiry: string | null }> = [];
    const { result } = renderHook(() => {
      const selector = useLiveSelector();
      snapshots.push({
        symbol: selector.state.symbol,
        expiry: selector.state.expiry,
      });
      return selector;
    });
    await waitFor(() => expect(result.current.state.expiry).toBe("2026-07-30"));

    snapshots.length = 0;
    act(() => result.current.setSymbol("BANKNIFTY"));

    expect(snapshots).not.toContainEqual({ symbol: "BANKNIFTY", expiry: "2026-07-30" });
    expect(result.current.state).toMatchObject({
      symbol: "BANKNIFTY",
      expiry: null,
      expiries: [],
      expiryLoading: true,
    });
  });
});
