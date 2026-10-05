import { StrictMode, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const market = vi.hoisted(() => ({
  scope: "live:native:dhan:A1",
  requests: [] as Array<{ kind: string; signal: AbortSignal; scope: string; resolve: (data: unknown) => void }>,
}));
vi.mock("@/hooks/useDataScope", () => ({ useMarketDataScope: () => market.scope }));
vi.mock("@/lib/market", () => ({ isMarketHours: () => false }));
function pending(kind: string, signal: AbortSignal, scope: string) {
  return new Promise((resolve) => { market.requests.push({ kind, signal, scope, resolve }); });
}
vi.mock("@/services/api", () => ({
  getDepth: (_symbol: string, _exchange: string, signal: AbortSignal, scope: string) => pending("depth", signal, scope),
  getOptionChain: (_symbol: string, _exchange: string, _expiry: string, signal: AbortSignal, scope: string) => pending("chain", signal, scope),
}));

import { useDepthData } from "../useDepthData";
import { useOptionChain } from "../useOptionChain";

function wrapper(strict = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>
    {strict ? <StrictMode>{children}</StrictMode> : children}
  </QueryClientProvider>;
}
const readers: Array<{ name: string; useRead: () => { data: unknown } }> = [
  { name: "depth", useRead: () => useDepthData("NIFTY", "NFO") },
  { name: "option chain", useRead: () => useOptionChain("NIFTY", "NFO", "2026-10-29") },
];

beforeEach(() => { market.scope = "live:native:dhan:A1"; market.requests = []; });

describe.each(readers)("$name market authority", ({ useRead }) => {
  it("hides cached account-A data during the first render under account B", async () => {
    const { result, rerender } = renderHook(useRead, { wrapper: wrapper() });
    await waitFor(() => expect(market.requests).toHaveLength(1));
    await act(async () => { market.requests[0].resolve({ account: "A" }); });
    await waitFor(() => expect(result.current.data).toEqual({ account: "A" }));
    market.scope = "live:native:upstox:B1";
    rerender();
    expect(result.current.data).toBeUndefined();
    await waitFor(() => expect(market.requests).toHaveLength(2));
    expect(market.requests[1].scope).toBe("live:native:upstox:B1");
    await act(async () => { market.requests[1].resolve({ account: "B" }); });
    await waitFor(() => expect(result.current.data).toEqual({ account: "B" }));
  });

  it("aborts an old account request and ignores its late response after a mode change", async () => {
    const { result, rerender } = renderHook(useRead, { wrapper: wrapper() });
    await waitFor(() => expect(market.requests).toHaveLength(1));
    const old = market.requests[0];
    market.scope = "explore:mock";
    rerender();
    await waitFor(() => expect(market.requests).toHaveLength(2));
    expect(old.signal.aborted).toBe(true);
    expect(market.requests[1].scope).toBe("explore:mock");
    await act(async () => { market.requests[1].resolve({ account: "Example" }); });
    await waitFor(() => expect(result.current.data).toEqual({ account: "Example" }));
    await act(async () => { old.resolve({ account: "A" }); });
    expect(result.current.data).toEqual({ account: "Example" });
  });

  it("restores a live observer after StrictMode replay and aborts on unmount", async () => {
    const { result, unmount } = renderHook(useRead, { wrapper: wrapper(), reactStrictMode: true });
    await waitFor(() => expect(market.requests.some((request) => !request.signal.aborted)).toBe(true));
    expect(market.requests.some((request) => request.signal.aborted)).toBe(true);
    const active = market.requests.filter((request) => !request.signal.aborted).at(-1)!;
    expect(active.scope).toBe("live:native:dhan:A1");
    unmount();
    expect(active.signal.aborted).toBe(true);
    await act(async () => { active.resolve({ account: "Retired observer" }); });
    expect(result.current.data).toBeUndefined();
  });
});
