import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import InstrumentCompareWidget from "../InstrumentCompareWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("InstrumentCompareWidget", () => {
  it("renders widget header with correct title", () => {
    render(<InstrumentCompareWidget />);
    expect(screen.getByText("Instrument Compare")).toBeTruthy();
  });

  it("shows the Sample data badge when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<InstrumentCompareWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("still shows the Sample data badge when connected (no live source wired)", () => {
    // The overlay series are built entirely from SAMPLE_SERIES; no history/quote
    // endpoint is wired yet, so a connected user must still see the disclosure.
    mockUseBrokerConnected.mockReturnValue(true);
    render(<InstrumentCompareWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("exposes the sample-data disclosure to assistive tech", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    render(<InstrumentCompareWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toHaveAttribute(
      "aria-label",
      "Showing sample data; no live data source is wired yet",
    );
    expect(badge).toHaveAttribute("role", "status");
  });

  it("renders 4 symbol input slots", () => {
    render(<InstrumentCompareWidget />);
    const inputs = screen.getAllByRole("textbox");
    expect(inputs.length).toBe(4);
  });

  it("renders default symbols NIFTY and BANKNIFTY in inputs", () => {
    render(<InstrumentCompareWidget />);
    const niftyInput = screen.getByDisplayValue("NIFTY");
    expect(niftyInput).toBeTruthy();
    const bankInput = screen.getByDisplayValue("BANKNIFTY");
    expect(bankInput).toBeTruthy();
  });

  it("renders SVG comparison chart when symbols are set", () => {
    render(<InstrumentCompareWidget />);
    expect(screen.getByRole("img", { name: /instrument comparison chart/i })).toBeTruthy();
  });

  it("renders comparison through the shared Flint multi-line chart primitive", () => {
    render(<InstrumentCompareWidget />);
    const chart = screen.getByRole("img", { name: /instrument comparison chart/i });
    expect(chart).toHaveAttribute("data-flint-chart", "multi-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-line-series]").length).toBeGreaterThanOrEqual(2);
  });

  it("shows active count in header", () => {
    render(<InstrumentCompareWidget />);
    // Default: NIFTY + BANKNIFTY = 2 active
    expect(screen.getByText(/2\/4 active/i)).toBeTruthy();
  });

  it("can update a symbol input", () => {
    render(<InstrumentCompareWidget />);
    const inputs = screen.getAllByRole("textbox");
    fireEvent.change(inputs[2], { target: { value: "finnifty" } });
    expect(screen.getByDisplayValue("FINNIFTY")).toBeTruthy();
  });

  it("clears a symbol when X button is clicked", () => {
    render(<InstrumentCompareWidget />);
    const clearButtons = screen.getAllByLabelText(/Clear instrument/i);
    fireEvent.click(clearButtons[0]);
    expect(screen.queryByDisplayValue("NIFTY")).toBeNull();
  });

  it("renders legend rows for active instruments", () => {
    render(<InstrumentCompareWidget />);
    expect(screen.getByText("% change from open")).toBeTruthy();
  });
});

describe("InstrumentCompareWidget — no invented series", () => {
  it("names a symbol it has no series for instead of drawing a fabricated line", () => {
    // This used to synthesise `100 + idx * 0.5` for any unknown symbol, so
    // typing a real ticker produced a smooth rising line that read as that
    // instrument's performance. A "Sample data" badge does not excuse a
    // fabricated series attributed to a named instrument.
    render(<InstrumentCompareWidget />);

    const firstSlot = screen.getAllByRole("textbox")[0];
    fireEvent.change(firstSlot, { target: { value: "RELIANCE" } });

    expect(screen.getByRole("note").textContent).toContain("RELIANCE");
    expect(screen.getByRole("note").textContent).toMatch(/no live price source/i);
  });
});
