import { StrictMode, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const market = vi.hoisted(() => ({
  scope: "live:native:dhan:A1",
  requests: [] as Array<{ signal: AbortSignal; scope: string; resolve: (data: unknown) => void }>,
}));
vi.mock("@/hooks/useDataScope", () => ({ useMarketDataScope: () => market.scope }));
vi.mock("@/stores/modeStore", () => ({ useModeStore: (select: (s: { mode: string }) => unknown) => select({ mode: market.scope.split(":")[0] }) }));
vi.mock("@/lib/market", () => ({ isMarketHours: () => false }));
vi.mock("@/services/api", () => ({
  getMultiQuotes: (_symbols: unknown, signal: AbortSignal, scope: string) => new Promise((resolve) => market.requests.push({ signal, scope, resolve })),
  normaliseMultiQuotes: (data: unknown) => data,
}));
vi.mock("@/widgets/utility/Scanner/sampleData", () => ({ SAMPLE_SECTOR_MOVERS: [] }));
import { useSectorMovers } from "../useSectorMovers";
import { useSectorMapData } from "../useSectorMapData";

function wrapper(strict = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{strict ? <StrictMode>{children}</StrictMode> : children}</QueryClientProvider>;
}
const quote = (ltp: number) => [{ symbol: "HDFCBANK", exchange: "NSE", ltp, prev_close: 100 }];
const readers: Array<{ name: string; useRead: () => { data: unknown }; empty: unknown }> = [
  { name: "sector movers", useRead: useSectorMovers, empty: [] },
  { name: "sector map", useRead: useSectorMapData, empty: null },
];
beforeEach(() => { market.scope = "live:native:dhan:A1"; market.requests = []; });
describe.each(readers)("$name scope", ({ useRead, empty }) => {
  it("hides cached A quotes before the first B request completes", async () => {
    const { result, rerender } = renderHook(useRead, { wrapper: wrapper() });
    await waitFor(() => expect(market.requests).toHaveLength(1));
    await act(async () => { market.requests[0].resolve(quote(110)); });
    await waitFor(() => expect(result.current.data).not.toEqual(empty));
    market.scope = "practice:native:upstox:B1";
    rerender();
    expect(result.current.data).toEqual(empty);
    await waitFor(() => expect(market.requests).toHaveLength(2));
    expect(market.requests[1].scope).toBe("practice:native:upstox:B1");
    await act(async () => { market.requests[1].resolve(quote(90)); });
    await waitFor(() => expect(JSON.stringify(result.current.data)).toContain("-10"));
  });
  it("aborts A on Explore and refuses its late response", async () => {
    const { result, rerender } = renderHook(useRead, { wrapper: wrapper() });
    await waitFor(() => expect(market.requests).toHaveLength(1));
    market.scope = "explore:mock";
    rerender();
    expect(market.requests[0].signal.aborted).toBe(true);
    await act(async () => { market.requests[0].resolve(quote(110)); });
    expect(result.current.data).toEqual(empty);
    expect(market.requests).toHaveLength(1);
  });
  it("survives StrictMode replay and cancels the final observer on unmount", async () => {
    const { result, unmount } = renderHook(useRead, { wrapper: wrapper(), reactStrictMode: true });
    await waitFor(() => expect(market.requests.some((request) => !request.signal.aborted)).toBe(true));
    expect(market.requests.some((request) => request.signal.aborted)).toBe(true);
    const active = market.requests.filter((request) => !request.signal.aborted).at(-1)!;
    unmount();
    expect(active.signal.aborted).toBe(true);
    await act(async () => { active.resolve(quote(110)); });
    expect(result.current.data).toEqual(empty);
  });
});
