/**
 * ConditionScannerWidget.test.tsx — the declarative scanner panel.
 *
 * Pins the /v1/scanner wiring: prebuilt scans load into the selector, Run posts
 * the chosen key, results render with the response-driven Live/Sample badge
 * (the backend reports what it actually scanned), and failures surface.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

const mockPrebuilt = vi.fn();
const mockRun = vi.fn();
vi.mock("@/services/ftApi", () => ({
  getPrebuiltScans: (...a: unknown[]) => mockPrebuilt(...a),
  runPrebuiltScan: (...a: unknown[]) => mockRun(...a),
}));

import ConditionScannerWidget from "../ConditionScannerWidget";

function wrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

const SCANS = {
  scans: [
    {
      key: "rsi_oversold",
      name: "RSI Oversold",
      universe: "nifty50",
      timeframe: "1d",
      condition_count: 1,
      conditions: [{ label: "RSI below 30", indicator: "rsi", operator: "below", value: 30 }],
    },
  ],
};

const RUN_SAMPLE = {
  status: "success",
  is_sample_data: true,
  scan_name: "RSI Oversold",
  matched_count: 1,
  total_universe: 50,
  results: [
    {
      symbol: "RELIANCE", exchange: "NSE", ltp: 2890.5, change_pct: -1.2,
      matched_conditions: ["RSI below 30"], scan_time: "2026-06-12T10:00:00+00:00", score: 0.82,
    },
  ],
};

beforeEach(() => {
  mockPrebuilt.mockReset();
  mockRun.mockReset();
  mockPrebuilt.mockResolvedValue(SCANS);
  mockRun.mockResolvedValue(RUN_SAMPLE);
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  // Radix Select needs these in jsdom
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  window.HTMLElement.prototype.hasPointerCapture = vi.fn();
});

async function chooseScanAndRun() {
  // open the Radix select and pick the prebuilt scan
  fireEvent.click(await screen.findByRole("combobox", { name: /prebuilt scan/i }));
  fireEvent.click(await screen.findByRole("option", { name: "RSI Oversold" }));
  fireEvent.click(screen.getByRole("button", { name: /run/i }));
}

describe("ConditionScannerWidget", () => {
  it("renders the header and run hint", () => {
    render(<ConditionScannerWidget />, { wrapper: wrapper() });
    expect(screen.getByText("Condition Scanner")).toBeInTheDocument();
    expect(screen.getByText(/choose a prebuilt scan/i)).toBeInTheDocument();
  });

  it("runs a prebuilt scan and renders sample-badged results", async () => {
    render(<ConditionScannerWidget />, { wrapper: wrapper() });

    await chooseScanAndRun();

    // TanStack v5 passes a context object as mutationFn's 2nd arg — assert the
    // variables positionally.
    await waitFor(() => expect(mockRun).toHaveBeenCalledTimes(1));
    expect(mockRun.mock.calls[0][0]).toBe("rsi_oversold");
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText(/1 of 50 matched/)).toBeInTheDocument();
    // response-driven badge: the backend says it scanned sample bars
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.getByText("RSI below 30", { selector: "td *, td" })).toBeInTheDocument();
  });

  it("shows the Live badge when the backend scanned live data", async () => {
    mockRun.mockResolvedValue({ ...RUN_SAMPLE, is_sample_data: false });
    render(<ConditionScannerWidget />, { wrapper: wrapper() });

    await chooseScanAndRun();

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("shows the empty-match state honestly", async () => {
    mockRun.mockResolvedValue({ ...RUN_SAMPLE, matched_count: 0, results: [] });
    render(<ConditionScannerWidget />, { wrapper: wrapper() });

    await chooseScanAndRun();

    expect(await screen.findByText(/no symbols matched/i)).toBeInTheDocument();
  });

  it("surfaces a run failure verbatim", async () => {
    mockRun.mockRejectedValue(new Error("scanner backend offline"));
    render(<ConditionScannerWidget />, { wrapper: wrapper() });

    await chooseScanAndRun();

    expect(await screen.findByText(/scan failed: scanner backend offline/i)).toBeInTheDocument();
  });
});
