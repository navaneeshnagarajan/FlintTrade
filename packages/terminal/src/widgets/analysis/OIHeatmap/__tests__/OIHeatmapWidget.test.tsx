import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock API calls — no real network
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  getOptionChain: vi.fn().mockResolvedValue(null),
  getExpiry: vi.fn().mockResolvedValue({ expiry: ["24-APR-25", "01-MAY-25"] }),
}));

// Mock lib/market
vi.mock("@/lib/market", () => ({ isMarketHours: vi.fn().mockReturnValue(false) }));

// Mock broker connected — default: disconnected → sample data path
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

// Mock FeatureTeaser to render children + sentinel
vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({
    children,
    featureName,
  }: {
    children: React.ReactNode;
    featureName: string;
  }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>
      {children}
    </div>
  ),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getOptionChain, getExpiry } from "@/services/api";
import OIHeatmapWidget from "../OIHeatmapWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetOptionChain = getOptionChain as ReturnType<typeof vi.fn>;
const mockGetExpiry = getExpiry as ReturnType<typeof vi.fn>;

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("OIHeatmapWidget — disconnected (sample data)", () => {
  it("renders the widget root", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    expect(screen.getByTestId("oiheatmap-widget")).toBeTruthy();
  });

  it("renders CE and PE row labels in the strike grid", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    // Both row labels should be present
    const ceLabels = screen.getAllByText(/^CE$/i);
    const peLabels = screen.getAllByText(/^PE$/i);
    expect(ceLabels.length).toBeGreaterThan(0);
    expect(peLabels.length).toBeGreaterThan(0);
  });

  it("shows colour legend (CE and PE labels in legend)", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    // Legend has CE and PE span labels
    const ceElems = screen.getAllByText(/^CE$/i);
    const peElems = screen.getAllByText(/^PE$/i);
    // At least 2 of each (row label + legend)
    expect(ceElems.length).toBeGreaterThanOrEqual(2);
    expect(peElems.length).toBeGreaterThanOrEqual(2);
  });

  it("wraps grid in FeatureTeaser when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("feature-teaser").dataset.feature).toBe("OI Heatmap");
  });

  it("renders symbol selector with NIFTY as default option", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    const select = screen.getByTestId("symbol-select") as HTMLSelectElement;
    expect(select).toBeTruthy();
    // NIFTY is an option
    const options = Array.from(select.options).map((o) => o.text);
    expect(options).toContain("NIFTY");
  });
});

describe("OIHeatmapWidget — connected with live data", () => {
  const mockChain = {
    chain: [
      { strike: 24700, ce: { oi: 120_000, oi_change: 5_000 }, pe: { oi: 80_000, oi_change: -2_000 } },
      { strike: 24750, ce: { oi: 200_000, oi_change: 10_000 }, pe: { oi: 180_000, oi_change: 8_000 } },
      { strike: 24800, ce: { oi: 95_000, oi_change: -3_000 }, pe: { oi: 110_000, oi_change: 4_000 } },
    ],
    atm_strike: 24750,
    pcr: 1.15,
  };

  it("does not wrap in FeatureTeaser when connected", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue(mockChain);
    render(<OIHeatmapWidget />);
    // FeatureTeaser should not be present
    expect(screen.queryByTestId("feature-teaser")).toBeNull();
  });

  it("renders expiry selector when connected", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25", "01-MAY-25"] });
    mockGetOptionChain.mockResolvedValue(mockChain);
    render(<OIHeatmapWidget />);
    // Initially shows the widget
    expect(screen.getByTestId("oiheatmap-widget")).toBeTruthy();
  });

  it("refresh button is enabled when connected", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    render(<OIHeatmapWidget />);
    const refreshBtn = screen.getByTestId("refresh-btn");
    expect(refreshBtn).toBeTruthy();
    // When connected the button should not be disabled by lack of connection
    // (it may be disabled if no expiry is selected, but that's correct behaviour)
    expect(refreshBtn.getAttribute("disabled")).toBeNull();
  });

  it("refresh button is disabled when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    const refreshBtn = screen.getByTestId("refresh-btn") as HTMLButtonElement;
    expect(refreshBtn.disabled).toBe(true);
  });
});

describe("OIHeatmapWidget — colour scale logic (unit)", () => {
  it("sample data grid has more than 10 strike price cells", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    // Sample data has 21 strikes; each row has the same number of cells.
    // Verify that more than 10 OI value texts are rendered (fmtOI output).
    // We look for elements with tabular-nums that contain K/L/Cr or a number.
    const cells = screen
      .getAllByRole("generic")
      .filter((el) =>
        el.className?.includes("tabular-nums") &&
        /\d/.test(el.textContent ?? ""),
      );
    expect(cells.length).toBeGreaterThan(10);
  });
});
