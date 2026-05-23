import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

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
import GreeksHeatmapWidget from "../GreeksHeatmapWidget";
import { SAMPLE_GREEKS_HEATMAP_DATA } from "../GreeksHeatmapWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("GreeksHeatmapWidget", () => {
  it("renders header with widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    expect(screen.getByText("Greeks Heatmap")).toBeTruthy();
  });

  it("shows Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("still shows Sample data badge when connected — no live endpoint yet", () => {
    // Per the widget header comment, the /api/v1/analysis/greeks-heatmap
    // backend route doesn't exist; the badge stays visible at all times
    // to avoid lying about the source of the data once a broker connects.
    mockConnected.mockReturnValue(true);
    render(<GreeksHeatmapWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("renders Greek toggle buttons", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    // Greek toggle group is role=group; check button roles inside it
    const group = screen.getByRole("group", { name: "Select Greek" });
    expect(group.querySelector("button[aria-pressed]")).toBeTruthy();
    expect(screen.getAllByText("Delta").length).toBeGreaterThan(0);
    expect(screen.getByText("Gamma")).toBeTruthy();
    expect(screen.getByText("Theta")).toBeTruthy();
    expect(screen.getByText("Vega")).toBeTruthy();
  });

  it("Delta button is pressed by default", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    const group = screen.getByRole("group", { name: "Select Greek" });
    const deltaBtn = group.querySelector("button[aria-pressed='true']");
    expect(deltaBtn?.textContent).toBe("Delta");
  });

  it("clicking Gamma toggles its pressed state", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    const group = screen.getByRole("group", { name: "Select Greek" });
    const gammaBtn = Array.from(group.querySelectorAll("button")).find(
      (b) => b.textContent === "Gamma",
    )!;
    expect(gammaBtn.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(gammaBtn);
    expect(gammaBtn.getAttribute("aria-pressed")).toBe("true");
  });

  it("renders heatmap grid cells for all expiries and strikes", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    const cells = screen.getAllByRole("gridcell");
    // 3 expiries × 9 strikes = 27 cells
    expect(cells.length).toBe(27);
  });

  it("renders symbol selector with expected options", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    const trigger = screen.getByLabelText("Select symbol");
    expect(trigger).toBeTruthy();
    // shadcn Select trigger shows current value; default is NIFTY
    expect(trigger.textContent).toContain("NIFTY");
  });

  it("refresh button is disabled when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    const btn = screen.getByLabelText("Refresh Greeks heatmap");
    expect(btn).toBeTruthy();
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("footer shows expiry and strike counts", () => {
    mockConnected.mockReturnValue(false);
    render(<GreeksHeatmapWidget />);
    expect(screen.getByText(/3 expiries/i)).toBeTruthy();
    expect(screen.getByText(/9 strikes/i)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_GREEKS_HEATMAP_DATA", () => {
  it("has 3 expiry rows", () => {
    expect(SAMPLE_GREEKS_HEATMAP_DATA).toHaveLength(3);
  });

  it("each row has 9 strike cells", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      expect(row.cells).toHaveLength(9);
    }
  });

  it("each row has at least one ATM cell", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      const atm = row.cells.find((c) => c.moneyness === "ATM");
      expect(atm).toBeDefined();
    }
  });

  it("delta values are between 0 and 1", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      for (const cell of row.cells) {
        expect(cell.delta).toBeGreaterThanOrEqual(0);
        expect(cell.delta).toBeLessThanOrEqual(1);
      }
    }
  });

  it("theta values are non-positive (cost)", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      for (const cell of row.cells) {
        expect(cell.theta).toBeLessThanOrEqual(0);
      }
    }
  });

  it("vega values are non-negative", () => {
    for (const row of SAMPLE_GREEKS_HEATMAP_DATA) {
      for (const cell of row.cells) {
        expect(cell.vega).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("near expiry has higher average gamma than back month (term structure)", () => {
    const avgGamma = (row: (typeof SAMPLE_GREEKS_HEATMAP_DATA)[0]) =>
      row.cells.reduce((s, c) => s + c.gamma, 0) / row.cells.length;
    // Average over all strikes to smooth out random noise
    const nearAvg = avgGamma(SAMPLE_GREEKS_HEATMAP_DATA[0]);
    const backAvg = avgGamma(SAMPLE_GREEKS_HEATMAP_DATA[2]);
    expect(nearAvg).toBeGreaterThan(backAvg);
  });
});
