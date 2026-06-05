import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// The widget renders deterministic SAMPLE data only — no live backend endpoint
// is wired yet, so it no longer reads `useBrokerConnected`. The mock below is
// kept (defensively) so a future broker-connection signal cannot silently
// resurrect the old "hide the Sample badge when connected" deception.

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import VWAPBandsWidget from "../VWAPBandsWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockConnected.mockReturnValue(false);
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("VWAPBandsWidget", () => {
  it("renders the widget title", () => {
    render(<VWAPBandsWidget />);
    expect(screen.getByText("VWAP Bands")).toBeTruthy();
  });

  it("shows the 'Sample data' badge in explore mode (disconnected)", () => {
    mockConnected.mockReturnValue(false);
    render(<VWAPBandsWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("keeps the 'Sample data' badge visible even when broker connected", () => {
    // The widget has no live data source wired yet — it must NOT pretend the
    // sample bars become real once a broker connects. The badge stays put.
    mockConnected.mockReturnValue(true);
    render(<VWAPBandsWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("badge is an honest, screen-reader-announced status with an explanatory title", () => {
    render(<VWAPBandsWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toHaveAttribute("role", "status");
    expect(badge).toHaveAttribute(
      "aria-label",
      "Showing sample data; no live backend endpoint yet",
    );
    expect(badge.getAttribute("title")).toMatch(/no live data wired yet/i);
  });

  it("does not render a deceptive live-looking refresh affordance", () => {
    // The old 30s "auto-refresh" only slept and bumped a clock — it implied
    // the fake data was live. No refresh button / "last updated" clock now.
    render(<VWAPBandsWidget />);
    expect(screen.queryByRole("button", { name: /refresh VWAP data/i })).toBeNull();
  });

  it("renders VWAP stat labels", () => {
    render(<VWAPBandsWidget />);
    // "VWAP" and "Price" each appear in both the stat card and the band legend
    expect(screen.getAllByText("VWAP").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Price").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/VWAP/i).length).toBeGreaterThan(0);
  });

  it("renders symbol selector button defaulting to NIFTY", () => {
    render(<VWAPBandsWidget />);
    expect(screen.getByRole("button", { name: /selected symbol: NIFTY/i })).toBeTruthy();
  });

  it("opens symbol dropdown and shows all symbols", () => {
    render(<VWAPBandsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /selected symbol/i }));
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
    expect(screen.getByText("RELIANCE")).toBeTruthy();
    expect(screen.getByText("HDFCBANK")).toBeTruthy();
  });

  it("renders band legend entries", () => {
    render(<VWAPBandsWidget />);
    expect(screen.getByText("± 1σ")).toBeTruthy();
    expect(screen.getByText("± 2σ")).toBeTruthy();
    expect(screen.getByText("± 3σ")).toBeTruthy();
  });

  it("renders VWAP through the shared Flint banded-line primitive", () => {
    render(<VWAPBandsWidget />);
    const chart = screen.getByRole("img", { name: /vwap bands chart/i });
    expect(chart).toHaveAttribute("data-flint-chart", "banded-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-banded-line-band]").length).toBe(3);
    expect(chart.querySelectorAll("[data-banded-line-series]").length).toBeGreaterThanOrEqual(2);
  });

  it("renders band legend swatches without local SVG", () => {
    const { container } = render(<VWAPBandsWidget />);
    expect(container.querySelector('svg[width="16"][height="8"]')).not.toBeInTheDocument();
  });
});
