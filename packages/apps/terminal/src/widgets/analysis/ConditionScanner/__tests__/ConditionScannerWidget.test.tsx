/**
 * ConditionScannerWidget.test.tsx — the canonical scanner panel.
 *
 * This suite is the union of the old ConditionScanner suite and the retired
 * `scanner` ("Pre-Market Scanner") suite (merge 2.17). Carried over in intent:
 *   - the retired widget pinned that its two HARD-CODED keys reached the
 *     client (`pre_market_movers`, `volume_breakout`). Those keys are no
 *     longer hard-coded anywhere — they are two of the eight the backend
 *     serves — so the pins moved to the panel-params path, which is what a
 *     saved `scanner` panel now restores through;
 *   - the sample/live provenance banners, and the invariant that a failed run
 *     leaves NO banner and NO rows behind (a mutation keeps its last payload
 *     while it errors);
 *   - the Add-to-watchlist row action, now pinned to actually land on the
 *     canonical multi-tab key rather than merely to render;
 *   - the sectors table and its Explore-mode disclosure.
 * New here: sortable columns, the OI handoff (unusual OI has ONE home, in OI
 * Analytics — this widget must never fetch it), and params round-tripping.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

const mockPrebuilt = vi.fn();
const mockRun = vi.fn();
const mockUnusualOI = vi.fn();
vi.mock("@/services/ftApi", () => ({
  getPrebuiltScans: (...a: unknown[]) => mockPrebuilt(...a),
  runPrebuiltScan: (...a: unknown[]) => mockRun(...a),
  // Present so the "never fetches unusual OI" pin can fail loudly if a future
  // edit re-adds the retired OI tab's fetch through either client module.
  getUnusualOI: (...a: unknown[]) => mockUnusualOI(...a),
}));
vi.mock("@/services/ftApi.analysis", () => ({
  getUnusualOI: (...a: unknown[]) => mockUnusualOI(...a),
}));

// The sectors view derives from a NIFTY 50 quote sweep; keep it off the network.
const mockMultiQuotes = vi.fn(() => Promise.resolve([]));
vi.mock("@/services/api", () => ({
  getMultiQuotes: (...a: unknown[]) => mockMultiQuotes(...(a as [])),
  normaliseMultiQuotes: (raw: unknown) => (Array.isArray(raw) ? raw : []),
}));

import ConditionScannerWidget from "../ConditionScannerWidget";
import { LS_KEY_MULTI } from "@/widgets/utility/Watchlist/types";

function wrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

function renderWidget(params: Record<string, unknown> = {}) {
  return render(
    <ConditionScannerWidget {...makeDockviewPanelProps({ params })} />,
    { wrapper: wrapper() },
  );
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
    {
      key: "pre_market_movers",
      name: "Pre-Market Movers",
      universe: "nifty50",
      timeframe: "1d",
      condition_count: 1,
      conditions: [{ label: "Gap up above 0.5", indicator: "gap_up", operator: "above", value: 0.5 }],
    },
    {
      key: "volume_breakout",
      name: "Volume Breakout",
      universe: "nifty50",
      timeframe: "1d",
      condition_count: 1,
      conditions: [{ label: "Volume spike above 1.5", indicator: "volume_spike", operator: "above", value: 1.5 }],
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

/** Two rows, deliberately NOT in change_pct order, for the sorting pin. */
const RUN_TWO_ROWS = {
  ...RUN_SAMPLE,
  matched_count: 2,
  results: [
    {
      symbol: "TATAMOTORS", exchange: "NSE", ltp: 985.4, change_pct: 2.1,
      matched_conditions: ["Gap up above 0.5"], scan_time: "2026-07-19T09:00:00Z", score: 0.82,
    },
    {
      symbol: "RELIANCE", exchange: "NSE", ltp: 2890.5, change_pct: -1.2,
      matched_conditions: ["RSI below 30"], scan_time: "2026-07-19T09:00:00Z", score: 0.64,
    },
  ],
};

beforeEach(() => {
  mockPrebuilt.mockReset();
  mockRun.mockReset();
  mockUnusualOI.mockReset();
  mockPrebuilt.mockResolvedValue(SCANS);
  mockRun.mockResolvedValue(RUN_SAMPLE);
  localStorage.clear();
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  // Radix Select needs these in jsdom
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  window.HTMLElement.prototype.hasPointerCapture = vi.fn();
});

async function chooseScanAndRun(name = "RSI Oversold") {
  // open the Radix select and pick the prebuilt scan
  fireEvent.click(await screen.findByRole("combobox", { name: /prebuilt scan/i }));
  fireEvent.click(await screen.findByRole("option", { name }));
  fireEvent.click(screen.getByRole("button", { name: /run/i }));
}

describe("ConditionScannerWidget", () => {
  it("renders the header and run hint", () => {
    renderWidget();
    expect(screen.getByText("Condition Scanner")).toBeInTheDocument();
    expect(screen.getByText(/choose a prebuilt scan/i)).toBeInTheDocument();
  });

  it("runs a prebuilt scan and renders sample-badged results", async () => {
    renderWidget();

    await chooseScanAndRun();

    // TanStack v5 passes a context object as mutationFn's 2nd arg — assert the
    // variables positionally.
    await waitFor(() => expect(mockRun).toHaveBeenCalledTimes(1));
    expect(mockRun.mock.calls[0][0]).toBe("rsi_oversold");
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText(/1 of 50 matched/)).toBeInTheDocument();
    // response-driven badge: the backend says it scanned sample bars
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    // …and the absorbed banner, which names the remedy the badge only carries
    // in a tooltip.
    expect(
      screen.getByText(/Sample scan — connect a broker read account/i),
    ).toBeInTheDocument();
    expect(screen.getByText("RSI below 30", { selector: "td *, td" })).toBeInTheDocument();
  });

  it("shows the Live badge and banner when the backend scanned live data", async () => {
    mockRun.mockResolvedValue({ ...RUN_SAMPLE, is_sample_data: false });
    renderWidget();

    await chooseScanAndRun();

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.getByText(/Live scan — the backend scanned real broker OHLCV/i)).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("badges a run with no provenance flag as sample, never Live", async () => {
    // Fail-closed: the affirmative "Live scan" claim needs an explicit false.
    const { is_sample_data: _omitted, ...noProvenance } = RUN_SAMPLE;
    mockRun.mockResolvedValue(noProvenance);
    renderWidget();

    await chooseScanAndRun();

    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.getByText(/Sample scan — connect a broker read account/i)).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText(/Live scan/i)).not.toBeInTheDocument();
  });

  it("shows the empty-match state honestly", async () => {
    mockRun.mockResolvedValue({ ...RUN_SAMPLE, matched_count: 0, results: [] });
    renderWidget();

    await chooseScanAndRun();

    expect(await screen.findByText(/no symbols matched/i)).toBeInTheDocument();
  });

  it("surfaces a run failure verbatim", async () => {
    mockRun.mockRejectedValue(new Error("scanner backend offline"));
    renderWidget();

    await chooseScanAndRun();

    expect(await screen.findByText(/scan failed: scanner backend offline/i)).toBeInTheDocument();
  });

  it("drops the badge, banner and rows when a re-run fails — no stale Live claim", async () => {
    mockRun.mockResolvedValue({ ...RUN_SAMPLE, is_sample_data: false });
    renderWidget();

    await chooseScanAndRun();
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();

    mockRun.mockRejectedValue(new Error("backend offline"));
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(await screen.findByText(/scan failed: backend offline/i)).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText(/Live scan/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sample scan/i)).not.toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();
  });

  // --- Retired `scanner` id: its two keys now arrive as panel params --------

  it("preselects and runs the scan named in params.scan (retired Gap tab)", async () => {
    mockRun.mockResolvedValue({ ...RUN_TWO_ROWS, scan_name: "Pre-Market Movers" });
    renderWidget({ view: "scans", scan: "pre_market_movers" });

    // (positional: TanStack v5 hands mutationFn a context object as arg 2)
    await waitFor(() => expect(mockRun).toHaveBeenCalledTimes(1));
    expect(mockRun.mock.calls[0][0]).toBe("pre_market_movers");
    expect(await screen.findByText("TATAMOTORS")).toBeInTheDocument();
    // the selector shows the saved scan, so the panel reopens where it was
    expect(screen.getByRole("combobox", { name: /prebuilt scan/i })).toHaveTextContent(
      "Pre-Market Movers",
    );
  });

  it("preselects and runs volume_breakout from params.scan (retired Volume tab)", async () => {
    mockRun.mockResolvedValue({ ...RUN_TWO_ROWS, scan_name: "Volume Breakout" });
    renderWidget({ scan: "volume_breakout" });

    await waitFor(() => expect(mockRun).toHaveBeenCalledTimes(1));
    expect(mockRun.mock.calls[0][0]).toBe("volume_breakout");
  });

  it("runs nothing on mount without params.scan", async () => {
    renderWidget();
    await screen.findByRole("combobox", { name: /prebuilt scan/i });
    expect(mockRun).not.toHaveBeenCalled();
  });

  // --- Absorbed: sortable tables -------------------------------------------

  it("sorts result rows by a clicked column header", async () => {
    mockRun.mockResolvedValue(RUN_TWO_ROWS);
    renderWidget({ scan: "pre_market_movers" });

    expect(await screen.findByText("TATAMOTORS")).toBeInTheDocument();
    const bodyRows = () => screen.getAllByRole("row").slice(1);
    expect(within(bodyRows()[0]).getByText("TATAMOTORS")).toBeInTheDocument();

    // Numeric columns sort descending first in TanStack Table.
    fireEvent.click(screen.getByText("Chg %"));
    await waitFor(() =>
      expect(screen.getByRole("columnheader", { name: /chg %/i })).toHaveAttribute(
        "aria-sort",
        "descending",
      ),
    );
    expect(within(bodyRows()[0]).getByText("TATAMOTORS")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Chg %"));
    await waitFor(() =>
      expect(within(bodyRows()[0]).getByText("RELIANCE")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("columnheader", { name: /chg %/i }),
    ).toHaveAttribute("aria-sort", "ascending");
  });

  // --- Absorbed: Add to watchlist (write-through, not just a badge) ---------

  it("adds a matched symbol to the canonical watchlist store", async () => {
    mockRun.mockResolvedValue(RUN_TWO_ROWS);
    renderWidget({ scan: "pre_market_movers" });

    const addBtn = await screen.findByLabelText("Add TATAMOTORS to watchlist");
    fireEvent.click(addBtn);

    expect(await screen.findByText("Added")).toBeInTheDocument();
    // the fix that matters: it lands on the multi-tab key the Watchlist reads,
    // not the legacy single-list key it used to write.
    const stored = localStorage.getItem(LS_KEY_MULTI);
    expect(stored).toContain("TATAMOTORS");
  });

  // --- Absorbed: sectors view (temporary home) ------------------------------

  it("keeps the sectors view as a disclosed sample table in Explore", async () => {
    renderWidget();

    fireEvent.click(screen.getByRole("button", { name: "Sectors" }));

    expect(await screen.findByText("Auto")).toBeInTheDocument();
    expect(screen.getByText("Banking")).toBeInTheDocument();
    expect(
      screen.getByText(/Sample data — leave Explore and connect OpenAlgo/i),
    ).toBeInTheDocument();
    // scan controls belong to the scans view only
    expect(screen.queryByRole("button", { name: /^run$/i })).not.toBeInTheDocument();
  });

  it("opens on the sectors view when params.view says so", async () => {
    renderWidget({ view: "sectors" });
    expect(await screen.findByText("Auto")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /prebuilt scan/i })).not.toBeInTheDocument();
  });

  // --- OI: handoff, not a third rendering ----------------------------------

  describe("unusual OI", () => {
    const seen: CustomEvent[] = [];
    const listener = (e: Event) => seen.push(e as CustomEvent);

    beforeEach(() => {
      seen.length = 0;
      window.addEventListener("flinttrade:addWidget", listener);
    });
    afterEach(() => window.removeEventListener("flinttrade:addWidget", listener));

    it("hands off to the OI Analytics signals view instead of re-rendering it", async () => {
      renderWidget();

      fireEvent.click(screen.getByLabelText("Open unusual OI in OI Analytics"));

      expect(seen).toHaveLength(1);
      expect(seen[0].detail).toEqual({
        widgetId: "oichart",
        title: "OI Analytics",
        props: { view: "signals" },
      });
    });

    it("never fetches unusual OI itself", async () => {
      renderWidget();
      await chooseScanAndRun();
      await screen.findByText("RELIANCE");
      fireEvent.click(screen.getByLabelText("Open unusual OI in OI Analytics"));
      fireEvent.click(screen.getByRole("button", { name: "Sectors" }));

      expect(mockUnusualOI).not.toHaveBeenCalled();
    });
  });
});
