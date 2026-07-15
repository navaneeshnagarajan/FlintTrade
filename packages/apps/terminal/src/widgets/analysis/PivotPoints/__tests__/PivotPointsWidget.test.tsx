/**
 * PivotPointsWidget.test.tsx
 *
 * Tests: render, pivot calculation, method tabs, price zone, sample data.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SAMPLE_PREV_DAY, SAMPLE_CURRENT_PRICE } from "../sampleData";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

const state = vi.hoisted(() => ({
  connected: false,
  mode: "live" as "explore" | "practice" | "live",
}));
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => state.connected,
}));
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (value: { mode: typeof state.mode }) => unknown) => selector({ mode: state.mode }),
}));

const mockGetHistory = vi.hoisted(() => vi.fn());
const mockGetQuotes = vi.hoisted(() => vi.fn());
vi.mock("@/services/api", () => ({
  getHistory: (...args: unknown[]) => mockGetHistory(...args),
  getQuotes: (...args: unknown[]) => mockGetQuotes(...args),
}));

import PivotPointsWidget from "../PivotPointsWidget";

const LIVE_PREVIOUS_DAY = {
  timestamp: "2026-07-10",
  open: 22950,
  high: 23100,
  low: 22800,
  close: 23025,
  volume: 1,
};

const LIVE_LATEST_DAY = {
  timestamp: "2026-07-11",
  open: 23025,
  high: 23200,
  low: 22900,
  close: 23150,
  volume: 1,
};

beforeEach(() => {
  state.connected = false;
  state.mode = "live";
  mockGetHistory.mockReset();
  mockGetQuotes.mockReset();
  mockGetHistory.mockResolvedValue([]);
  mockGetQuotes.mockResolvedValue({ ltp: LIVE_LATEST_DAY.close });
});

describe("PivotPointsWidget", () => {
  it("renders the widget header", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByText("Pivot Points")).toBeTruthy();
  });

  it("shows sample data badge when disconnected", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByText("sample data")).toBeTruthy();
  });

  it("never labels Explore responses as Live when a broker remains connected", async () => {
    state.connected = true;
    state.mode = "explore";

    render(<PivotPointsWidget />);

    expect(screen.getByText("sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mockGetHistory).not.toHaveBeenCalled();
      expect(mockGetQuotes).not.toHaveBeenCalled();
    });
  });

  it("labels successful sandbox-scoped inputs as Practice", async () => {
    state.mode = "practice";
    mockGetHistory.mockResolvedValue([LIVE_PREVIOUS_DAY, LIVE_LATEST_DAY]);
    mockGetQuotes.mockResolvedValue({ ltp: LIVE_LATEST_DAY.close });

    render(<PivotPointsWidget />);

    expect(await screen.findByText("Practice")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("renders OHLC input fields", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByLabelText("Previous day High")).toBeTruthy();
    expect(screen.getByLabelText("Previous day Low")).toBeTruthy();
    expect(screen.getByLabelText("Previous day Close")).toBeTruthy();
    expect(screen.getByLabelText("Previous day Open")).toBeTruthy();
  });

  it("renders method tabs for all five pivot methods", () => {
    render(<PivotPointsWidget />);
    // Use getAllByText because method names also appear in the footer summary
    expect(screen.getAllByText("Standard").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Fibonacci").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Woodie").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Camarilla").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("DeMark").length).toBeGreaterThanOrEqual(1);
  });

  it("renders level labels P, R1–R4, S1–S4 in the table", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByText("P")).toBeTruthy();
    expect(screen.getByText("R1")).toBeTruthy();
    expect(screen.getByText("S1")).toBeTruthy();
    expect(screen.getByText("R4")).toBeTruthy();
    expect(screen.getByText("S4")).toBeTruthy();
  });

  it("switches to Fibonacci method when tab is clicked", () => {
    render(<PivotPointsWidget />);
    // Target the tab button specifically by role
    const tabs = screen.getAllByRole("tab");
    const fibTab = tabs.find((t) => t.textContent === "Fibonacci");
    expect(fibTab).toBeTruthy();
    fireEvent.click(fibTab!);
    expect(fibTab!.getAttribute("aria-selected")).toBe("true");
  });

  it("shows current price label", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByText("Current price")).toBeTruthy();
  });

  it("renders the symbol selector with NIFTY as default", () => {
    render(<PivotPointsWidget />);
    const trigger = screen.getByLabelText("Select symbol");
    expect(trigger.textContent).toContain("NIFTY");
  });

  it("keeps the sample badge while connected live data is loading", () => {
    state.connected = true;
    mockGetHistory.mockReturnValue(new Promise(() => {}));
    mockGetQuotes.mockReturnValue(new Promise(() => {}));

    render(<PivotPointsWidget />);

    expect(screen.getByText("sample data")).toBeInTheDocument();
    expect(screen.getByLabelText("Previous day High")).toHaveValue(SAMPLE_PREV_DAY.high);
    expect(screen.getByText(new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(SAMPLE_CURRENT_PRICE))).toBeInTheDocument();
  });

  it("keeps sample provenance when history is too short", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue([LIVE_LATEST_DAY]);

    render(<PivotPointsWidget />);

    expect(await screen.findByText(
      new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(LIVE_LATEST_DAY.close),
    )).toBeInTheDocument();
    expect(screen.getByText("sample data")).toBeInTheDocument();
    expect(screen.getByLabelText("Previous day High")).toHaveValue(SAMPLE_PREV_DAY.high);
  });

  it("keeps sample provenance when history fails", async () => {
    state.connected = true;
    mockGetHistory.mockRejectedValue(new Error("History unavailable"));

    render(<PivotPointsWidget />);

    expect(await screen.findByText("History unavailable")).toBeInTheDocument();
    expect(screen.getByText("sample data")).toBeInTheDocument();
    expect(screen.getByLabelText("Previous day High")).toHaveValue(SAMPLE_PREV_DAY.high);
  });

  it("keeps sample provenance when the quote fails after live OHLC loads", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue([LIVE_PREVIOUS_DAY, LIVE_LATEST_DAY]);
    mockGetQuotes.mockRejectedValue(new Error("Quote unavailable"));

    render(<PivotPointsWidget />);

    await waitFor(() => expect(screen.getByLabelText("Previous day High")).toHaveValue(LIVE_PREVIOUS_DAY.high));
    expect(screen.getByText("sample data")).toBeInTheDocument();
    expect(screen.getByText(new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(SAMPLE_CURRENT_PRICE))).toBeInTheDocument();
  });

  it("shows Live only after both OHLC and current price are replaced", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue([LIVE_PREVIOUS_DAY, LIVE_LATEST_DAY]);
    mockGetQuotes.mockResolvedValue({ ltp: LIVE_LATEST_DAY.close });

    render(<PivotPointsWidget />);

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.queryByText("sample data")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Previous day High")).toHaveValue(LIVE_PREVIOUS_DAY.high);
    expect(screen.getAllByText(
      new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(LIVE_LATEST_DAY.close),
    ).length).toBeGreaterThan(0);
  });

  it("keeps sample provenance when history returns invalid OHLC", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue([
      { ...LIVE_PREVIOUS_DAY, high: 0 },
      LIVE_LATEST_DAY,
    ]);
    mockGetQuotes.mockResolvedValue({ ltp: LIVE_LATEST_DAY.close });

    render(<PivotPointsWidget />);

    await waitFor(() => expect(mockGetQuotes).toHaveBeenCalledTimes(1));
    expect(screen.getByText("sample data")).toBeInTheDocument();
    expect(screen.getByLabelText("Previous day High")).toHaveValue(SAMPLE_PREV_DAY.high);
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("clears live provenance when an OHLC input is edited", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue([LIVE_PREVIOUS_DAY, LIVE_LATEST_DAY]);
    mockGetQuotes.mockResolvedValue({ ltp: LIVE_LATEST_DAY.close });

    render(<PivotPointsWidget />);

    expect(await screen.findByText("Live")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Previous day High"), {
      target: { value: "23000" },
    });

    expect(screen.getByText("sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });
});
