import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// When connected, the widget fetches the live IV smile (getFtIVSmile) and
// derives the aligned greek grid. We mock it so we can exercise the live
// ("Live" badge) and sample ("Sample data") paths.

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/ftApi.analysis", () => ({
  getFtIVSmile: vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getFtIVSmile } from "@/services/ftApi.analysis";
import GreeksHeatmapWidget from "../GreeksHeatmapWidget";
import { SAMPLE_GREEKS_HEATMAP_DATA } from "../GreeksHeatmapWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetSmile = getFtIVSmile as ReturnType<typeof vi.fn>;

function liveSmile() {
  return {
    underlying: "NIFTY",
    spot_price: 22000,
    curves: [
      {
        expiry: "17-APR-26",
        days_to_expiry: 8,
        atm_iv: 0.15,
        atm_strike: 22000,
        skew_25delta: 0.02,
        points: [
          { strike: 21800, call_iv: 0.16, put_iv: 0.165, moneyness: 0.991 },
          { strike: 22000, call_iv: 0.15, put_iv: 0.15, moneyness: 1.0 },
          { strike: 22200, call_iv: 0.145, put_iv: 0.148, moneyness: 1.009 },
        ],
      },
    ],
  };
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <GreeksHeatmapWidget />
    </QueryClientProvider>,
  );
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  mockConnected.mockReturnValue(false);
  mockGetSmile.mockResolvedValue({ underlying: "NIFTY", spot_price: 0, curves: [] });
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("GreeksHeatmapWidget", () => {
  it("renders header with widget title", () => {
    renderWidget();
    expect(screen.getByText("Greeks Heatmap")).toBeTruthy();
  });

  it("shows Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not fetch the IV smile when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockGetSmile).not.toHaveBeenCalled();
  });

  it("flips to a Live badge once the IV smile yields a greek grid", async () => {
    mockConnected.mockReturnValue(true);
    mockGetSmile.mockResolvedValue(liveSmile());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(mockGetSmile).toHaveBeenCalled();
  });

  it("falls back to Sample data when connected but the IV smile has no curves", async () => {
    mockConnected.mockReturnValue(true);
    mockGetSmile.mockResolvedValue({ underlying: "NIFTY", spot_price: 0, curves: [] });
    renderWidget();

    await waitFor(() => expect(mockGetSmile).toHaveBeenCalled());
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("renders Greek toggle buttons", () => {
    renderWidget();
    const group = screen.getByRole("group", { name: "Select Greek" });
    expect(group.querySelector("button[aria-pressed]")).toBeTruthy();
    expect(screen.getAllByText("Delta").length).toBeGreaterThan(0);
    expect(screen.getByText("Gamma")).toBeTruthy();
    expect(screen.getByText("Theta")).toBeTruthy();
    expect(screen.getByText("Vega")).toBeTruthy();
  });

  it("Delta button is pressed by default", () => {
    renderWidget();
    const group = screen.getByRole("group", { name: "Select Greek" });
    const deltaBtn = group.querySelector("button[aria-pressed='true']");
    expect(deltaBtn?.textContent).toBe("Delta");
  });

  it("clicking Gamma toggles its pressed state", () => {
    renderWidget();
    const group = screen.getByRole("group", { name: "Select Greek" });
    const gammaBtn = Array.from(group.querySelectorAll("button")).find(
      (b) => b.textContent === "Gamma",
    )!;
    expect(gammaBtn.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(gammaBtn);
    expect(gammaBtn.getAttribute("aria-pressed")).toBe("true");
  });

  it("renders heatmap grid cells for all expiries and strikes (sample mode)", () => {
    renderWidget();
    const cells = screen.getAllByRole("gridcell");
    // 3 expiries × 9 strikes = 27 cells
    expect(cells.length).toBe(27);
  });

  it("renders symbol selector with expected options", () => {
    renderWidget();
    const trigger = screen.getByLabelText("Select symbol");
    expect(trigger).toBeTruthy();
    expect(trigger.textContent).toContain("NIFTY");
  });

  it("does not render a dead refresh button (removed deceptive affordance)", () => {
    renderWidget();
    expect(screen.queryByLabelText("Refresh Greeks heatmap")).toBeNull();
  });

  it("footer shows expiry and strike counts (sample mode)", () => {
    renderWidget();
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
