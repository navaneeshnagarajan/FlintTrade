/** Actual Watchlist + Chart effects, stores and clients; only canvas/HTTP are inert. */
import { Activity, StrictMode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { useTimings } from "@/hooks/useMarketStatus";
import { queryClient as productionQueryClient } from "@/providers/QueryProvider";
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
function release(index: number, malformed = false) {
  requests[index].completed = true;
  requests[index].reply(new Response(JSON.stringify(malformed
    ? { status: "success", data: {} }
    : { status: "error", message: REFUSAL }), {
    status: malformed ? 200 : 503, headers: { "Content-Type": "application/json" },
  }));
}
function view(mode: "visible" | "hidden" = "visible", chart = true) {
  return <StrictMode><QueryClientProvider client={client}>
    <Activity mode={mode}><WatchlistWidget api={panel} />{chart && <ChartWidget />}</Activity>
  </QueryClientProvider></StrictMode>;
}

function ShellConsumers() {
  const accounts = useBrokerAccounts();
  const timings = useTimings();
  return <><output aria-label="accounts error">{accounts.error?.message}</output>
    <output aria-label="timings error">{timings.error?.message}</output></>;
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

describe("mounted Terminal discovery ownership", () => {
  it.each([false, true])("preserves both shell retry owners with startup connection retirement=%s", async (retireConnection) => {
    // Use the actual production retry policy (two retries, existing delays).
    client = productionQueryClient;
    client.clear();
    render(<StrictMode><QueryClientProvider client={client}><ShellConsumers /></QueryClientProvider></StrictMode>);
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0].signal.aborted).toBe(true);
    await act(async () => {
      if (retireConnection) useConnectionStore.getState().setStatus("connected");
      release(0); release(1);
    });
    for (const count of [3, 4]) {
      await waitFor(() => expect(requests).toHaveLength(count), { timeout: 4000 });
      await act(async () => release(count - 1));
    }
    await waitFor(() => {
      expect(client.getQueryState(["broker", "accounts"])).toMatchObject({ status: "error", fetchStatus: "idle", fetchFailureCount: 3 });
      expect(client.getQueryState(["timings"])).toMatchObject({ status: "error", fetchStatus: "idle", fetchFailureCount: 3 });
      expect(screen.getByLabelText("accounts error")).toHaveTextContent(REFUSAL);
      expect(screen.getByLabelText("timings error")).toHaveTextContent(REFUSAL);
    });
    expect(requests.map((r) => r.signal.aborted)).toEqual([true, retireConnection, false, false]);
    expect(requests.filter((r) => r.completed && !r.signal.aborted)).toHaveLength(retireConnection ? 2 : 3);
  });

  it("coalesces the first real effects, then separately acquires history after intervals settle", async () => {
    render(view());
    await waitFor(() => {
      expect(calls.watchlist).toHaveBeenCalledTimes(2);
      expect(calls.intervals).toHaveBeenCalledTimes(2);
      expect(calls.quote).toHaveBeenCalledTimes(2);
    });
    expect(calls.history).not.toHaveBeenCalled();
    // StrictMode retires its first generation. The actual surviving trio share
    // one flight; history is causally later and must not reuse its error.
    expect(requests).toHaveLength(2);
    expect(requests.map((r) => r.signal.aborted)).toEqual([true, false]);
    await act(async () => { release(0); release(1); });
    await waitFor(() => expect(calls.history).toHaveBeenCalledOnce());
    expect(requests).toHaveLength(3);
    await act(async () => release(2));
    expect(screen.getByTitle(REFUSAL)).toBeVisible();
    expect(requests.filter((r) => !r.signal.aborted && r.completed)).toHaveLength(2);
  });

  it("Activity hide retires the held generation and return cannot reuse its decoded success", async () => {
    const mounted = render(view());
    await waitFor(() => expect(requests).toHaveLength(2));
    mounted.rerender(view("hidden"));
    expect(requests.every((r) => r.signal.aborted)).toBe(true);
    mounted.rerender(view("visible"));
    // StrictMode reconnects the returned Activity effects twice as well; the
    // observed first return flight is aborted, not a completed discovery.
    await waitFor(() => expect(calls.intervals).toHaveBeenCalledTimes(4));
    expect(requests).toHaveLength(4);
    expect(requests.map((r) => r.signal.aborted)).toEqual([true, true, true, false]);
    await act(async () => {
      requests[1].completed = true;
      requests[1].reply(new Response(JSON.stringify({ data: { accounts: [] } })));
      release(0); release(2);
    });
    expect(calls.history).not.toHaveBeenCalled();
    expect(requests[3].signal.aborted).toBe(false);
    await act(async () => release(3));
    await waitFor(() => expect(calls.history).toHaveBeenCalledOnce());
    expect(requests).toHaveLength(5);
    await act(async () => release(4));
    expect(screen.getByTitle(REFUSAL)).toBeVisible();
  });

  it("closing Chart leaves Watchlist's borrower alive and malformed discovery visible", async () => {
    const mounted = render(view());
    await waitFor(() => expect(requests).toHaveLength(2));
    mounted.rerender(view("visible", false));
    expect(requests[1].signal.aborted).toBe(false);
    await act(async () => { release(0); release(1, true); });
    expect(screen.getByTitle("Native account discovery is unavailable or malformed.")).toBeVisible();
    expect(calls.history).not.toHaveBeenCalled();
    expect(requests).toHaveLength(2);
  });
});
