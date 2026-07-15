import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  getGammaDensityData: vi.fn(),
}));

vi.mock("@/services/ftApi", () => ({
  getGammaDensityData: apiMocks.getGammaDensityData,
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

import { useGammaDensity } from "../useGammaDensity";

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useGammaDensity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getGammaDensityData.mockResolvedValue({ strikes: [] });
  });

  it("does not request gamma density without an authoritative expiry", async () => {
    const { result } = renderHook(
      () => useGammaDensity("NIFTY", "NFO", "", true),
      { wrapper: createWrapper() },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(apiMocks.getGammaDensityData).not.toHaveBeenCalled();
  });

  it("passes the selected expiry to the live request", async () => {
    renderHook(
      () => useGammaDensity("NIFTY", "NFO", "2099-07-30", true),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(apiMocks.getGammaDensityData).toHaveBeenCalledWith("NIFTY", "NFO", "2099-07-30");
    });
  });
});
