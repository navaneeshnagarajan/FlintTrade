import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LocalDataPanel } from "../LocalDataPanel";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function mockFetch(routes: Record<string, unknown>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const [path, payload] of Object.entries(routes)) {
      if (url.includes(path)) {
        return {
          ok: true,
          json: async () => payload,
        } as Response;
      }
    }
    return { ok: false, json: async () => ({}) } as Response;
  });
}

describe("LocalDataPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/data/ticks/status": {
        status: "success",
        data: {
          enabled: true,
          running: true,
          connected: true,
          tick_count: 12345,
          persisted_tick_count: 12300,
          pending_tick_count: 45,
          dropped_tick_count: 7,
          watchlist: {
            ltp: [
              { exchange: "NSE_INDEX", symbol: "NIFTY" },
              { exchange: "NSE", symbol: "RELIANCE" },
            ],
            quote: [
              { exchange: "NSE_INDEX", symbol: "NIFTY" },
              { exchange: "NSE_INDEX", symbol: "BANKNIFTY" },
            ],
            depth: [
              { exchange: "NSE", symbol: "RELIANCE" },
              { exchange: "MCX", symbol: "GOLD" },
            ],
          },
        },
      },
      "/v1/historify/bars/summary": {
        status: "success",
        data: {
          tables: {
            ohlcv_1d: { rows: 5000, symbols: 12, first: "2025-01-01 00:00:00", last: "2026-07-04 00:00:00" },
            ohlcv_1m: { rows: 0, symbols: 0, first: null, last: null },
          },
        },
      },
      "/v1/historify/bhavcopy/download": {
        status: "success",
        data: { saved_count: 1, error_count: 0, dest_dir: "/tmp/bhavcopy" },
      },
    }));
    useAuthStore.setState({ token: null });
    useConnectionStore.setState({ apiKey: "" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows recording status, tick count and capture watchlist", async () => {
    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("recording")).toBeInTheDocument();
    });
    expect(screen.getByText(/12,300 persisted/)).toBeInTheDocument();
    expect(screen.getByText(/12,345 received/)).toBeInTheDocument();
    expect(screen.getByText(/45 pending/)).toBeInTheDocument();
    expect(screen.getByText(/7 dropped/)).toBeInTheDocument();
    expect(screen.getByText(/12,300 persisted/)).toHaveTextContent(
      /NIFTY, RELIANCE, BANKNIFTY, GOLD$/,
    );
  });

  it("shows only non-empty local store tables", async () => {
    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("ohlcv_1d")).toBeInTheDocument();
    });
    expect(screen.queryByText("ohlcv_1m")).not.toBeInTheDocument();
    expect(screen.getByText("5,000")).toBeInTheDocument();
  });

  it("uses authenticated helpers for tick, OHLCV, and bhavcopy requests", async () => {
    useAuthStore.setState({ token: "terminal-jwt" });
    useConnectionStore.setState({ apiKey: "terminal-api-key" });
    render(<LocalDataPanel />, { wrapper });

    await screen.findByText("ohlcv_1d");
    fireEvent.click(screen.getByRole("button", { name: /Fetch bhavcopies/i }));

    const activeFetch = vi.mocked(globalThis.fetch);
    await waitFor(() => {
      expect(activeFetch.mock.calls.some(([url]) => (
        String(url).includes("/v1/historify/bhavcopy/download")
      ))).toBe(true);
    });

    for (const path of [
      "/api/v1/data/ticks/status",
      "/v1/historify/bars/summary",
      "/v1/historify/bhavcopy/download",
    ]) {
      const call = activeFetch.mock.calls.find(([url]) => String(url).includes(path));
      expect(call?.[1]?.headers).toEqual(expect.objectContaining({
        Authorization: "Bearer terminal-jwt",
        "X-API-Key": "terminal-api-key",
      }));
    }
  });

  it("surfaces the backend OHLCV summary error instead of showing an empty store", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/v1/historify/bars/summary")) {
        return {
          ok: false,
          status: 503,
          json: async () => ({ message: "OHLCV store is locked" }),
        } as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          status: "success",
          data: {
            enabled: false,
            running: false,
            connected: false,
            tick_count: 0,
            watchlist: {},
          },
        }),
      } as Response;
    }));

    render(<LocalDataPanel />, { wrapper });

    expect(await screen.findByText("OHLCV store is locked")).toBeInTheDocument();
    expect(screen.queryByText(/Nothing downloaded yet/)).not.toBeInTheDocument();
  });

  it("shows the off hint when capture is disabled", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/data/ticks/status": {
        status: "success",
        data: { enabled: false, running: false, tick_count: 0, watchlist: {}, hint: "Set FLINTTRADE_TICK_CAPTURE=1" },
      },
      "/v1/historify/bars/summary": { status: "success", data: { tables: {} } },
    }));

    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("off")).toBeInTheDocument();
    });
    expect(screen.getByText(/FLINTTRADE_TICK_CAPTURE=1/)).toBeInTheDocument();
  });

  it("shows reconnecting rather than recording when the enabled recorder is disconnected", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/data/ticks/status": {
        status: "success",
        data: {
          enabled: true,
          running: true,
          connected: false,
          last_error: "OpenAlgo connection refused",
          tick_count: 0,
          watchlist: {},
        },
      },
      "/v1/historify/bars/summary": { status: "success", data: { tables: {} } },
    }));

    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("reconnecting")).toBeInTheDocument();
    });
    expect(screen.queryByText("recording")).not.toBeInTheDocument();
    expect(screen.getByText("OpenAlgo connection refused")).toBeInTheDocument();
  });

  it("shows degraded rather than recording for a connected control error", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/data/ticks/status": {
        status: "success",
        data: {
          enabled: true,
          running: true,
          connected: true,
          last_error: "Partial subscription failure: NSE:BAD",
          tick_count: 10,
          watchlist: {},
        },
      },
      "/v1/historify/bars/summary": { status: "success", data: { tables: {} } },
    }));

    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("degraded")).toBeInTheDocument();
    });
    expect(screen.queryByText("recording")).not.toBeInTheDocument();
    expect(screen.getByText("Partial subscription failure: NSE:BAD")).toBeInTheDocument();
  });

  it("shows connecting when the enabled recorder has no connection error", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/data/ticks/status": {
        status: "success",
        data: { enabled: true, running: true, connected: false, tick_count: 0, watchlist: {} },
      },
      "/v1/historify/bars/summary": { status: "success", data: { tables: {} } },
    }));

    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("connecting")).toBeInTheDocument();
    });
    expect(screen.queryByText("recording")).not.toBeInTheDocument();
  });

  it("shows stopped error state without claiming recording", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/data/ticks/status": {
        status: "success",
        data: {
          enabled: true,
          running: false,
          connected: false,
          last_error: "Authentication failed",
          tick_count: 0,
          watchlist: {},
        },
      },
      "/v1/historify/bars/summary": { status: "success", data: { tables: {} } },
    }));

    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("error")).toBeInTheDocument();
    });
    expect(screen.queryByText("recording")).not.toBeInTheDocument();
    expect(screen.getByText("Authentication failed")).toBeInTheDocument();
  });

  it("shows stopped when capture is enabled but no recorder task is running", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/data/ticks/status": {
        status: "success",
        data: { enabled: true, running: false, connected: false, tick_count: 0, watchlist: {} },
      },
      "/v1/historify/bars/summary": { status: "success", data: { tables: {} } },
    }));

    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("stopped")).toBeInTheDocument();
    });
    expect(screen.queryByText("recording")).not.toBeInTheDocument();
  });

  it("shows checking while tick status is pending", () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/data/ticks/status")) {
        return new Promise<Response>(() => {});
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ status: "success", data: { tables: {} } }),
      } as Response);
    }));

    render(<LocalDataPanel />, { wrapper });

    expect(screen.getByText("checking")).toBeInTheDocument();
    expect(screen.queryByText("off")).not.toBeInTheDocument();
    expect(screen.queryByText(/FLINTTRADE_TICK_CAPTURE=1/)).not.toBeInTheDocument();
  });

  it("shows unavailable when tick status fetch is rejected", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/data/ticks/status")) {
        return Promise.reject(new Error("backend unavailable"));
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ status: "success", data: { tables: {} } }),
      } as Response);
    }));

    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("unavailable")).toBeInTheDocument();
    });
    expect(screen.queryByText("off")).not.toBeInTheDocument();
    expect(screen.queryByText(/FLINTTRADE_TICK_CAPTURE=1/)).not.toBeInTheDocument();
  });

  it("shows unavailable when tick status response is non-ok", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/data/ticks/status")) {
        return { ok: false, json: async () => ({}) } as Response;
      }
      return {
        ok: true,
        json: async () => ({ status: "success", data: { tables: {} } }),
      } as Response;
    }));

    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("unavailable")).toBeInTheDocument();
    });
    expect(screen.queryByText("off")).not.toBeInTheDocument();
    expect(screen.queryByText(/FLINTTRADE_TICK_CAPTURE=1/)).not.toBeInTheDocument();
  });

  it("renders the bhavcopy fetch controls", () => {
    render(<LocalDataPanel />, { wrapper });

    expect(screen.getByLabelText("Bhavcopy start date")).toBeInTheDocument();
    expect(screen.getByLabelText("Bhavcopy end date")).toBeInTheDocument();
    expect(screen.getByText(/Fetch bhavcopies/)).toBeInTheDocument();
  });
});
