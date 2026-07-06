import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LocalDataPanel } from "../LocalDataPanel";

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
          tick_count: 12345,
          watchlist: { quote: [{ exchange: "NSE_INDEX", symbol: "NIFTY" }], ltp: [], depth: [] },
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
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows recording status, tick count and capture watchlist", async () => {
    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("recording")).toBeInTheDocument();
    });
    expect(screen.getByText(/12,345 ticks this session/)).toBeInTheDocument();
    expect(screen.getByText(/NIFTY/)).toBeInTheDocument();
  });

  it("shows only non-empty local store tables", async () => {
    render(<LocalDataPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("ohlcv_1d")).toBeInTheDocument();
    });
    expect(screen.queryByText("ohlcv_1m")).not.toBeInTheDocument();
    expect(screen.getByText("5,000")).toBeInTheDocument();
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

  it("renders the bhavcopy fetch controls", () => {
    render(<LocalDataPanel />, { wrapper });

    expect(screen.getByLabelText("Bhavcopy start date")).toBeInTheDocument();
    expect(screen.getByLabelText("Bhavcopy end date")).toBeInTheDocument();
    expect(screen.getByText(/Fetch bhavcopies/)).toBeInTheDocument();
  });
});
