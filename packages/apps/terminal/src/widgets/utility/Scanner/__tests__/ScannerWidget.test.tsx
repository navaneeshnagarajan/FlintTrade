/**
 * ScannerWidget.test.tsx — render + interaction tests for the Pre-Market Scanner.
 *
 * Gap Scan and Volume run real backend prebuilt scans (mocked here); the
 * response's own is_sample_data flag drives the Live / Sample badge. OI Change
 * and Sectors remain disclosed sample tables.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import "@testing-library/jest-dom";

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

// Suppress ResizeObserver noise
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// Mock the scanner client — the widget must consume the shared ftApi surface.
const mockRunPrebuiltScan = vi.fn();
vi.mock("@/services/ftApi", () => ({
  runPrebuiltScan: (key: string) => mockRunPrebuiltScan(key) as Promise<unknown>,
}));

import ScannerWidget from "../ScannerWidget";

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function sampleRun(overrides: Record<string, unknown> = {}) {
  return {
    status: "success",
    is_sample_data: true,
    scan_name: "Pre-Market Movers",
    matched_count: 2,
    total_universe: 50,
    results: [
      {
        symbol: "TATAMOTORS",
        exchange: "NSE",
        ltp: 985.4,
        change_pct: 2.1,
        matched_conditions: ["gap_up above 0.5"],
        scan_time: "2026-07-19T09:00:00Z",
        score: 82,
      },
      {
        symbol: "RELIANCE",
        exchange: "NSE",
        ltp: 2985.0,
        change_pct: -0.6,
        matched_conditions: ["volume_spike above 1.5"],
        scan_time: "2026-07-19T09:00:00Z",
        score: 64,
      },
    ],
    ...overrides,
  };
}

describe("ScannerWidget", () => {
  beforeEach(() => {
    mockRunPrebuiltScan.mockReset();
    mockRunPrebuiltScan.mockResolvedValue(sampleRun());
  });

  it("renders scanner header and tabs", async () => {
    render(<ScannerWidget />, { wrapper: createWrapper() });
    expect(screen.getByText("Scanner")).toBeInTheDocument();
    expect(screen.getByText("Gap Scan")).toBeInTheDocument();
    expect(screen.getByText("OI Change")).toBeInTheDocument();
    expect(screen.getAllByText("Volume").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Sectors")).toBeInTheDocument();
    await screen.findByText("TATAMOTORS");
  });

  it("runs the pre-market prebuilt scan on the default Gap tab", async () => {
    render(<ScannerWidget />, { wrapper: createWrapper() });
    expect(await screen.findByText("TATAMOTORS")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(mockRunPrebuiltScan).toHaveBeenCalledWith("pre_market_movers");
  });

  it("badges a sample-data scan from the response flag", async () => {
    render(<ScannerWidget />, { wrapper: createWrapper() });
    expect(
      await screen.findByText(/Sample scan — connect a broker read account/i),
    ).toBeInTheDocument();
  });

  it("badges a live scan with its name and match counts", async () => {
    mockRunPrebuiltScan.mockResolvedValue(sampleRun({ is_sample_data: false }));
    render(<ScannerWidget />, { wrapper: createWrapper() });
    expect(await screen.findByText(/Live scan — Pre-Market Movers/i)).toBeInTheDocument();
    expect(screen.getByText(/2 of 50 matched/i)).toBeInTheDocument();
  });

  it("drops the banner entirely when a scan fails — no stale Live claim over an error body", async () => {
    mockRunPrebuiltScan.mockRejectedValue(new Error("Backend offline"));
    render(<ScannerWidget />, { wrapper: createWrapper() });
    await screen.findByText("Scan failed.", {}, { timeout: 5000 });
    expect(screen.queryByText(/Live scan/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sample scan/i)).not.toBeInTheDocument();
  });

  it("reports a failed scan honestly", async () => {
    mockRunPrebuiltScan.mockRejectedValue(new Error("Backend offline"));
    render(<ScannerWidget />, { wrapper: createWrapper() });
    // The widget retries a failed scan once before surfacing the error, so
    // give the find a window beyond the retry delay.
    expect(await screen.findByText("Scan failed.", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText("Backend offline")).toBeInTheDocument();
  });

  it("shows an honest empty state when nothing matches", async () => {
    mockRunPrebuiltScan.mockResolvedValue(
      sampleRun({ matched_count: 0, results: [], is_sample_data: false }),
    );
    render(<ScannerWidget />, { wrapper: createWrapper() });
    expect(
      await screen.findByText(/No matches in the scan universe right now/i),
    ).toBeInTheDocument();
  });

  it("runs the volume-breakout prebuilt scan on the Volume tab", async () => {
    render(<ScannerWidget />, { wrapper: createWrapper() });
    const nav = screen.getByLabelText("Scanner tabs");
    const volumeTab = nav.querySelector("button:nth-child(3)");
    expect(volumeTab).not.toBeNull();
    fireEvent.click(volumeTab!);
    await screen.findByText("TATAMOTORS");
    expect(mockRunPrebuiltScan).toHaveBeenCalledWith("volume_breakout");
  });

  it("keeps the OI Change tab as a disclosed sample table", () => {
    render(<ScannerWidget />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("OI Change"));
    expect(screen.getByText("NIFTY 24200 CE")).toBeInTheDocument();
    expect(
      screen.getByText(/Sample data — no live source exists for this scan yet/i),
    ).toBeInTheDocument();
  });

  it("keeps the Sectors tab as a disclosed sample table in Explore", () => {
    render(<ScannerWidget />, { wrapper: createWrapper() });
    fireEvent.click(screen.getByText("Sectors"));
    expect(screen.getByText("Auto")).toBeInTheDocument();
    expect(screen.getByText("Banking")).toBeInTheDocument();
    expect(
      screen.getByText(/Sample data — leave Explore and connect OpenAlgo/i),
    ).toBeInTheDocument();
  });

  it("offers a re-run control only on live-scan tabs", async () => {
    render(<ScannerWidget />, { wrapper: createWrapper() });
    await screen.findByText("TATAMOTORS");
    expect(screen.getByLabelText("Re-run scan")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Sectors"));
    expect(screen.queryByLabelText("Re-run scan")).not.toBeInTheDocument();
  });

  it("renders Add to Watchlist buttons on live scan rows", async () => {
    render(<ScannerWidget />, { wrapper: createWrapper() });
    await screen.findByText("TATAMOTORS");
    const addButtons = screen.getAllByLabelText(/Add .* to watchlist/i);
    expect(addButtons.length).toBeGreaterThan(0);
  });
});
