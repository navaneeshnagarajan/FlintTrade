/** Actual Watchlist + Chart effects, stores and clients; only canvas/HTTP are inert. */
import { Activity, StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { useAuthStore } from "@/stores/authStore";
import { resetAccountRuntime, setAccountRuntime } from "@/test-utils/accountQueryHarness";
import WatchlistWidget from "@/widgets/utility/Watchlist/WatchlistWidget";
import ChartWidget from "@/widgets/analysis/Chart/ChartWidget";

// jsdom cannot supply a canvas. Keep the real chart initialiser and effect
// lifetime: mock only the external library's drawing handles, not its callers.
vi.mock("lightweight-charts", async (original) => {
  const library = await original<typeof import("lightweight-charts")>();
  const timeScale = {
    fitContent: vi.fn(), setVisibleLogicalRange: vi.fn(), setVisibleRange: vi.fn(),
    subscribeVisibleLogicalRangeChange: vi.fn(), unsubscribeVisibleLogicalRangeChange: vi.fn(),
    subscribeVisibleTimeRangeChange: vi.fn(), unsubscribeVisibleTimeRangeChange: vi.fn(),
    coordinateToTime: vi.fn(), timeToCoordinate: vi.fn(),
  };
  return { ...library,
    createChart: () => ({
      addSeries: () => ({ setData: vi.fn(), applyOptions: vi.fn(), priceScale: () => ({ applyOptions: vi.fn() }), createPriceLine: vi.fn(), removePriceLine: vi.fn() }),
      applyOptions: vi.fn(), priceScale: () => ({ applyOptions: vi.fn() }),
      timeScale: () => timeScale, removeSeries: vi.fn(), remove: vi.fn(),
      subscribeCrosshairMove: vi.fn(), unsubscribeCrosshairMove: vi.fn(),
      subscribeClick: vi.fn(), unsubscribeClick: vi.fn(), panes: () => [],
    }),
    createSeriesMarkers: () => ({ setMarkers: vi.fn() }),
  };
});

const REFUSAL = "Credential store unavailable.";
let requests: Array<{ signal: AbortSignal; reply: (response: Response) => void; completed: boolean }>;
let failures: string[];
let client: QueryClient;
let calls: ReturnType<typeof observeCalls>;
const panel = { id: "r34-watchlist", updateParameters: () => {} };

function observeCalls() {
  // These spies call through unchanged, proving every original consumer runs.
  return { watchlist: vi.spyOn(api, "getMultiQuotes"), intervals: vi.spyOn(api, "getIntervals"), quote: vi.spyOn(api, "getQuotes"), history: vi.spyOn(api, "getHistory") };
}
function release(index: number, empty = false) {
  requests[index].completed = true;
  requests[index].reply(new Response(JSON.stringify(empty
    ? { status: "success", data: { accounts: [] } }
    : { status: "error", message: REFUSAL }), {
    status: empty ? 200 : 503, headers: { "Content-Type": "application/json" },
  }));
}
function view(mode: "visible" | "hidden" = "visible", chart = true) {
  return <StrictMode><QueryClientProvider client={client}>
    <Activity mode={mode}><WatchlistWidget api={panel} />{chart && <ChartWidget />}</Activity>
  </QueryClientProvider></StrictMode>;
}

beforeEach(() => {
  localStorage.clear();
  setAccountRuntime({ accounts: [], mode: "practice" });
  useAuthStore.setState({ status: "logged-in", token: null, username: "Synthetic" });
  requests = []; failures = [];
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  calls = observeCalls();
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init: RequestInit = {}) => {
    try {
      expect(String(input)).toBe("/ft-api/api/v1/native/accounts");
      expect(init.method ?? "GET").toBe("GET");
      expect(init.body).toBeUndefined();
      expect(init.signal).toBeInstanceOf(AbortSignal);
      return new Promise<Response>((reply) => {
        const signal = init.signal!;
        requests.push({ signal, reply, completed: false });
        // Deliberately ignore cancellation: the real decoder must fence bodies.
      });
    } catch (error) { failures.push(String(error)); throw error; }
  });
});

afterEach(async () => {
  cleanup();
  await act(async () => { requests.forEach((r, i) => { if (!r.completed) release(i); }); });
  client.clear(); resetAccountRuntime();
  useAuthStore.setState({ status: "logged-out", token: null, username: null });
  vi.restoreAllMocks(); vi.unstubAllGlobals();
  expect(failures).toEqual([]);
});

describe("settled Terminal Activity discovery ownership", () => {
  it.each([false, true])("acquires history after the current interval generation, empty census=%s", async (empty) => {
    const mounted = render(view());
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(calls.watchlist).toHaveBeenCalledTimes(2);
    expect(calls.intervals).toHaveBeenCalledTimes(2);
    expect(calls.quote).toHaveBeenCalledTimes(2);
    expect(calls.history).not.toHaveBeenCalled();
    await act(async () => { release(0, empty); release(1, empty); });
    await waitFor(() => expect(calls.history).toHaveBeenCalledOnce());
    expect(requests).toHaveLength(3);
    await act(async () => release(2, empty));
    if (!empty) expect(screen.getByTitle(REFUSAL)).toBeVisible();
    expect(requests.filter(r => r.completed && !r.signal.aborted)).toHaveLength(2);

    mounted.rerender(view("hidden"));
    mounted.rerender(view("visible"));
    await waitFor(() => expect(calls.intervals).toHaveBeenCalledTimes(4));
    // A settled previous interval scope is not a lease for this activation.
    // Hold the actual new HTTP body; history must remain causally downstream.
    expect(calls.history).toHaveBeenCalledOnce();
    expect(calls.watchlist).toHaveBeenCalledTimes(4);
    expect(calls.quote).toHaveBeenCalledTimes(4);
    expect(requests).toHaveLength(5);
    expect(requests[4].signal.aborted).toBe(false);
    await act(async () => { release(3, empty); release(4, empty); });
    await waitFor(() => expect(calls.history).toHaveBeenCalledTimes(2));
    expect(requests).toHaveLength(6);
    await act(async () => release(5, empty));
    if (!empty) expect(screen.getByTitle(REFUSAL)).toBeVisible();
    expect(requests.slice(3).filter(r => r.completed && !r.signal.aborted)).toHaveLength(2);
    expect(requests.filter(r => r.completed && !r.signal.aborted)).toHaveLength(4);
  });

  it("keeps the current owner's ordinary interval-timeout fallback on return", async () => {
    const mounted = render(view());
    await waitFor(() => expect(requests).toHaveLength(2));
    await act(async () => { release(0); release(1); });
    await waitFor(() => expect(calls.history).toHaveBeenCalledOnce());
    await act(async () => release(2));
    mounted.rerender(view("hidden"));
    mounted.rerender(view("visible"));
    await waitFor(() => expect(calls.intervals).toHaveBeenCalledTimes(4));
    expect(calls.history).toHaveBeenCalledOnce();
    // No fixture reply: let the unchanged product timer settle its fallback.
    await waitFor(() => expect(calls.history).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect(calls.intervals.mock.calls[3][0]?.aborted).toBe(true);
    expect(requests[4].signal.aborted).toBe(false);
  });
});
