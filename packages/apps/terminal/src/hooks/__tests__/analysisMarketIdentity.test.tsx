import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

const authority = vi.hoisted(() => ({ scope: "practice:native:dhan:A", connected: true, listeners: new Set<() => void>() }));
vi.mock("@/hooks/useDataScope", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
  useMarketDataScope: () => useSyncExternalStore((listener) => { authority.listeners.add(listener); return () => { authority.listeners.delete(listener); }; }, () => authority.scope),
  requireCurrentMarketDataScope: (scope: string) => {
    if (scope !== authority.scope) throw new Error("Authority changed");
  },
}; });
vi.mock("@/hooks/useBrokerConnected", () => ({ useBrokerConnected: () => authority.connected }));
vi.mock("@/hooks/useTrackBehavior", () => ({ useTrackBehavior: () => vi.fn() }));
vi.mock("@/lib/market", () => ({ isMarketHours: () => false }));
vi.mock("@/components/ui/GlassCard", () => ({ GlassCard: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock("@/services/api", () => ({ getHistory: vi.fn(), getMultiQuotes: vi.fn(), normaliseMultiQuotes: (rows: Array<{ data: unknown }>) => rows.map((row) => row.data) }));
vi.mock("@/services/ftApi", () => ({ getCandlestickPatterns: vi.fn() }));
vi.mock("@/services/ftApi.analysis", () => ({ getMultiTimeframe: vi.fn() }));
vi.mock("@/widgets/analysis/VWAPBands/api", () => ({ postVwapBands: vi.fn() }));

import { getHistory, getMultiQuotes } from "@/services/api";
import { getCandlestickPatterns } from "@/services/ftApi";
import { getMultiTimeframe } from "@/services/ftApi.analysis";
import { postVwapBands } from "@/widgets/analysis/VWAPBands/api";
import { EtfTab } from "@/routes/invest/tabs/EtfTab";
import MultiTimeframeWidget from "@/widgets/analysis/MultiTimeframe/MultiTimeframeWidget";
import VWAPBandsWidget from "@/widgets/analysis/VWAPBands/VWAPBandsWidget";
import { usePatternDetection } from "@/widgets/analysis/PatternDetection/usePatternDetection";

function switchAuthority(scope: string) {
  act(() => { authority.scope = scope; for (const listener of authority.listeners) listener(); });
}
function deferred<T>() {
  let resolve!: (data: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
const bars = Array.from({ length: 6 }, (_, i) => ({ timestamp: 1705290300 + i * 300, open: 22500, high: 22505, low: 22495, close: 22500 + i, volume: 1000 }));
const patterns = { is_sample_data: false, scan: { bar_count: 987, matches: [] } };
const mtf = { symbol: "NIFTY", confluence: 1, overall: "bullish" as const, signals: ["5m", "15m"].map((timeframe) => ({ timeframe, trend: "bullish" as const, rsi: 61.5, macd_histogram: 1, ema_position: "above" as const, strength: 1 })) };
const bands = { timestamps: bars.map(() => "2024-01-15T09:15:00"), vwap: bars.map(() => 12345.678), upper_1: bars.map(() => 12400), upper_2: bars.map(() => 12500), upper_3: bars.map(() => 12600), lower_1: bars.map(() => 12300), lower_2: bars.map(() => 12200), lower_3: bars.map(() => 12100) };
const quotes = [{ symbol: "NIFTYBEES", exchange: "NSE", data: { symbol: "NIFTYBEES", exchange: "NSE", ltp: 2897, open: 2800, high: 2900, low: 2790, close: 2800, prev_close: 2800, volume: 10 } }];

beforeEach(() => {
  vi.resetAllMocks();
  authority.scope = "practice:native:dhan:A";
  authority.connected = true;
  vi.mocked(getHistory).mockResolvedValue(bars);
  vi.mocked(getMultiQuotes).mockResolvedValue(quotes);
  vi.mocked(getCandlestickPatterns).mockResolvedValue(patterns);
  vi.mocked(getMultiTimeframe).mockResolvedValue(mtf);
  vi.mocked(postVwapBands).mockResolvedValue(bands);
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
});

describe("analysis market authority", () => {
  it("clears ETF account-A prices before B arrives and aborts the old quote observer", async () => {
    const Wrapper = wrapper();
    const view = render(<EtfTab />, { wrapper: Wrapper });
    await waitFor(() => expect(screen.getAllByText("₹2,897").length).toBeGreaterThan(0));
    const late = deferred<typeof quotes>();
    vi.mocked(getMultiQuotes).mockReturnValue(late.promise);
    switchAuthority("practice:native:upstox:B");
    view.rerender(<EtfTab />);
    expect(screen.queryByText("₹2,897")).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading ETF quotes" })).toBeInTheDocument();
    expect(screen.getByText(/fetching native quotes/)).toBeInTheDocument();
    expect(screen.queryByText(/live quotes/i)).not.toBeInTheDocument();
    expect(screen.queryByText("₹265")).not.toBeInTheDocument();
    await waitFor(() => expect(getMultiQuotes).toHaveBeenCalledTimes(2));
    expect(vi.mocked(getMultiQuotes).mock.calls[1][2]).toBe(authority.scope);
    await act(async () => late.resolve([{ ...quotes[0], data: { ...quotes[0].data, ltp: 3001 } }]));
    await waitFor(() => expect(screen.getAllByText("₹3,001").length).toBeGreaterThan(0));
    expect(screen.getByText(/live quotes via your native broker/)).toBeInTheDocument();
  });

  it("ignores a late ETF A response after a mode and account change", async () => {
    const late = deferred<typeof quotes>();
    vi.mocked(getMultiQuotes).mockReturnValue(late.promise);
    const view = render(<EtfTab />, { wrapper: wrapper() });
    await waitFor(() => expect(getMultiQuotes).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(getMultiQuotes).mock.calls[0][1]!;
    vi.mocked(getMultiQuotes).mockResolvedValue([]);
    switchAuthority("explore:mock");
    view.rerender(<EtfTab />);
    await waitFor(() => expect(getMultiQuotes).toHaveBeenCalledTimes(2));
    expect(signal.aborted).toBe(true);
    await act(async () => { late.resolve(quotes); });
    expect(screen.queryByText("₹2,897")).not.toBeInTheDocument();
  });

  it("clears cached candlestick results on the first B render", async () => {
    const hook = renderHook(() => usePatternDetection("NIFTY", "NSE_INDEX", authority.connected), { wrapper: wrapper() });
    await waitFor(() => expect(hook.result.current.data?.scan.bar_count).toBe(987));
    vi.mocked(getHistory).mockReturnValue(deferred<typeof bars>().promise);
    switchAuthority("practice:native:upstox:B");
    hook.rerender();
    expect(hook.result.current.data).toBeUndefined();
    await waitFor(() => expect(getHistory).toHaveBeenCalledTimes(2));
    expect(vi.mocked(getHistory).mock.calls[1][6]).toBe(authority.scope);
  });

  it("refuses late candlestick history before posting it for another authority", async () => {
    const late = deferred<typeof bars>();
    vi.mocked(getHistory).mockReturnValue(late.promise);
    const hook = renderHook(() => usePatternDetection("NIFTY", "NSE_INDEX", authority.connected), { wrapper: wrapper() });
    await waitFor(() => expect(getHistory).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(getHistory).mock.calls[0][5]!;
    vi.mocked(getHistory).mockReturnValue(deferred<typeof bars>().promise);
    switchAuthority("live:native:upstox:B");
    hook.rerender();
    await act(async () => { late.resolve(bars); });
    expect(signal.aborted).toBe(true);
    expect(getCandlestickPatterns).not.toHaveBeenCalled();
    expect(hook.result.current.data).toBeUndefined();
  });

  it("clears MTF live signals on the first account-B render", async () => {
    const view = render(<MultiTimeframeWidget />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.getAllByText("61.5")).toHaveLength(2);
    vi.mocked(getHistory).mockReturnValue(deferred<typeof bars>().promise);
    switchAuthority("practice:native:upstox:B");
    view.rerender(<MultiTimeframeWidget />);
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("61.5")).not.toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("ignores a late MTF computation after switching authority", async () => {
    const late = deferred<typeof mtf>();
    vi.mocked(getMultiTimeframe).mockReturnValue(late.promise);
    const view = render(<MultiTimeframeWidget />, { wrapper: wrapper() });
    await waitFor(() => expect(getMultiTimeframe).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(getMultiTimeframe).mock.calls[0][2]!;
    vi.mocked(getHistory).mockReturnValue(deferred<typeof bars>().promise);
    switchAuthority("explore:mock");
    view.rerender(<MultiTimeframeWidget />);
    await act(async () => { late.resolve(mtf); });
    expect(signal.aborted).toBe(true);
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("61.5")).not.toBeInTheDocument();
  });

  it("clears cached server VWAP bands on the first B render", async () => {
    const view = render(<VWAPBandsWidget />, { wrapper: wrapper() });
    await waitFor(() => expect(screen.getByText("12345.68")).toBeInTheDocument());
    vi.mocked(getHistory).mockReturnValue(deferred<typeof bars>().promise);
    switchAuthority("practice:native:upstox:B");
    view.rerender(<VWAPBandsWidget />);
    expect(screen.queryByText("12345.68")).not.toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("ignores a late VWAP calculation after account B replaces A", async () => {
    const late = deferred<typeof bands>();
    vi.mocked(postVwapBands).mockReturnValue(late.promise);
    const view = render(<VWAPBandsWidget />, { wrapper: wrapper() });
    await waitFor(() => expect(postVwapBands).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(postVwapBands).mock.calls[0][2]!;
    vi.mocked(getHistory).mockReturnValue(deferred<typeof bars>().promise);
    switchAuthority("practice:native:upstox:B");
    view.rerender(<VWAPBandsWidget />);
    await act(async () => { late.resolve(bands); });
    expect(signal.aborted).toBe(true);
    expect(screen.queryByText("12345.68")).not.toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });
});
