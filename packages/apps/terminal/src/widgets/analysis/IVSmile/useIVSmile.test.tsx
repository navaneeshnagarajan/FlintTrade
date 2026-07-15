import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  getFtIVSmile: vi.fn(),
}));

vi.mock("@/services/ftApi", () => ({
  getFtIVSmile: apiMocks.getFtIVSmile,
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

import { useIVSmile } from "./useIVSmile";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useIVSmile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getFtIVSmile.mockResolvedValue({ curves: [] });
  });

  it.each([
    undefined,
    [],
    ["", "   "],
  ])("stays disabled without a valid nonblank expiry (%s)", (expiries) => {
    const { result } = renderHook(
      () => useIVSmile("NIFTY", "NFO", expiries, true),
      { wrapper },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(apiMocks.getFtIVSmile).not.toHaveBeenCalled();
  });

  it("trims and filters expiries before querying", async () => {
    renderHook(
      () => useIVSmile("NIFTY", "NFO", ["", " 2026-07-30 ", "   ", "2026-08-06"], true),
      { wrapper },
    );

    await waitFor(() => expect(apiMocks.getFtIVSmile).toHaveBeenCalledOnce());
    expect(apiMocks.getFtIVSmile).toHaveBeenCalledWith(
      "NIFTY",
      "NFO",
      ["2026-07-30", "2026-08-06"],
      expect.any(AbortSignal),
    );
  });

  it("aborts an in-flight request when its observer unmounts", async () => {
    apiMocks.getFtIVSmile.mockReturnValue(new Promise(() => {}));
    const { unmount } = renderHook(
      () => useIVSmile("NIFTY", "NFO", ["2026-07-30"], true),
      { wrapper },
    );
    await waitFor(() => expect(apiMocks.getFtIVSmile).toHaveBeenCalledOnce());
    const signal = apiMocks.getFtIVSmile.mock.calls[0]?.[3] as AbortSignal;

    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
