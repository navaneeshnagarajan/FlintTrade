import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    getPositionbook: vi.fn(() => Promise.resolve([])),
    getFunds: vi.fn(() => Promise.resolve({ availableCash: 0, usedMargin: 0, totalBalance: 0 })),
  };
});

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getPositionbook, getFunds } from "@/services/api";
import type { Position, Funds } from "@/types/api";
import RiskDashboardWidget, {
  SAMPLE_RISK_DATA,
  computeLiveRisk,
} from "../RiskDashboardWidget";

import type { TrafficLight } from "../RiskDashboardWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockPositions = getPositionbook as ReturnType<typeof vi.fn>;
const mockFunds = getFunds as ReturnType<typeof vi.fn>;

function renderWidget(ui: ReactElement = <RiskDashboardWidget />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  mockConnected.mockReturnValue(false);
  mockPositions.mockReset();
  mockPositions.mockResolvedValue([]);
  mockFunds.mockReset();
  mockFunds.mockResolvedValue({ availableCash: 0, usedMargin: 0, totalBalance: 0 });
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("RiskDashboardWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Risk Dashboard")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", () => {
    mockConnected.mockReturnValue(true);
    renderWidget();
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders overall status banner", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    const banner = screen.getByLabelText(/Overall risk status/i);
    expect(banner).toBeTruthy();
  });

  it("renders risk metrics section", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByLabelText("Risk metrics")).toBeTruthy();
  });

  it("renders all sample metric labels", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    for (const m of SAMPLE_RISK_DATA.metrics) {
      expect(screen.getByText(m.label)).toBeTruthy();
    }
  });

  it("renders legend with three traffic light levels", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText(/Within limits/i)).toBeTruthy();
    expect(screen.getByText(/Approaching/i)).toBeTruthy();
    expect(screen.getByText(/Breached/i)).toBeTruthy();
  });

  it("renders metric cards with aria labels", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    for (const m of SAMPLE_RISK_DATA.metrics) {
      const card = screen.getByLabelText(new RegExp(m.label, "i"));
      expect(card).toBeTruthy();
    }
  });

  it("renders metric gauges through the shared Flint radial gauge primitive", () => {
    mockConnected.mockReturnValue(false);
    const { container } = renderWidget();
    const gauges = container.querySelectorAll('[data-flint-chart="radial-gauge"]');
    expect(gauges.length).toBe(SAMPLE_RISK_DATA.metrics.length);
  });
});

// ---------------------------------------------------------------------------
// Sample data / logic tests
// ---------------------------------------------------------------------------

describe("SAMPLE_RISK_DATA", () => {
  it("has 5 metrics", () => {
    expect(SAMPLE_RISK_DATA.metrics).toHaveLength(5);
  });

  it("each metric has a valid traffic light level", () => {
    const valid: TrafficLight[] = ["green", "amber", "red"];
    for (const m of SAMPLE_RISK_DATA.metrics) {
      expect(valid).toContain(m.level);
    }
  });

  it("usagePct is between 0 and 100 for all metrics", () => {
    for (const m of SAMPLE_RISK_DATA.metrics) {
      expect(m.usagePct).toBeGreaterThanOrEqual(0);
      expect(m.usagePct).toBeLessThanOrEqual(100);
    }
  });

  it("margin metric has percentage unit", () => {
    const margin = SAMPLE_RISK_DATA.metrics.find((m) => m.id === "margin");
    expect(margin).toBeDefined();
    expect(margin?.unit).toBe("%");
  });

  it("overall level is the worst of individual levels", () => {
    const hasRed  = SAMPLE_RISK_DATA.metrics.some((m) => m.level === "red");
    const hasAmber = SAMPLE_RISK_DATA.metrics.some((m) => m.level === "amber");
    if (hasRed) {
      expect(SAMPLE_RISK_DATA.overallLevel).toBe("red");
    } else if (hasAmber) {
      expect(SAMPLE_RISK_DATA.overallLevel).toBe("amber");
    } else {
      expect(SAMPLE_RISK_DATA.overallLevel).toBe("green");
    }
  });

  it("all metric ids are unique", () => {
    const ids = SAMPLE_RISK_DATA.metrics.map((m) => m.id);
    const unique = new Set(ids);
    expect(unique.size).toBe(ids.length);
  });
});

// ---------------------------------------------------------------------------
// computeLiveRisk — real data only, no fabricated greeks
// ---------------------------------------------------------------------------

const POS: Position[] = [
  { symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 2500, ltp: 2510, pnl: 100, pnlPercent: 0.4 },
  { symbol: "TCS", exchange: "NSE", product: "MIS", quantity: -5, averagePrice: 3000, ltp: 2990, pnl: 50, pnlPercent: 0.3 },
];
const FUNDS: Funds = { availableCash: 40_000, usedMargin: 60_000, totalBalance: 100_000 };

describe("computeLiveRisk", () => {
  it("gauges only Margin Utilised; never fabricates greeks metrics", () => {
    const ids = computeLiveRisk(POS, FUNDS).metrics.map((m) => m.id);
    expect(ids).toEqual(["margin"]);
    expect(ids).not.toContain("delta");
    expect(ids).not.toContain("theta");
    expect(ids).not.toContain("maxloss");
  });

  it("shows Total Exposure as an informational stat, not a balance-limited gauge", () => {
    const data = computeLiveRisk(POS, FUNDS);
    // Not a gauge metric (avoids the false-red-vs-balance verdict under leverage).
    expect(data.metrics.find((m) => m.id === "exposure")).toBeUndefined();
    const exposure = data.infoStats?.find((s) => s.label === "Total Exposure");
    expect(exposure).toBeDefined();
    expect(exposure!.value).toBeTruthy();
  });

  it("margin utilised gauge is usedMargin / totalBalance", () => {
    const margin = computeLiveRisk(POS, FUNDS).metrics.find((m) => m.id === "margin")!;
    expect(margin.value).toBeCloseTo(60); // 60k / 100k
  });

  it("does not gauge a spurious red when funds have not loaded (totalBalance 0)", () => {
    const data = computeLiveRisk(POS, undefined);
    // No margin gauge without funds → no metric can flip the banner to red.
    expect(data.metrics).toHaveLength(0);
    expect(data.overallLevel).toBe("green");
    // Margin shown as an honest "—" info stat instead of a fake 0%.
    expect(data.infoStats?.find((s) => s.label === "Margin Utilised")?.value).toBe("—");
  });

  it("is all-clear (green) when flat with no funds", () => {
    const data = computeLiveRisk([], undefined);
    expect(data.overallLevel).toBe("green");
  });
});

describe("RiskDashboardWidget (connected)", () => {
  it("fetches positions + funds only when connected", async () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockPositions).not.toHaveBeenCalled();
    expect(mockFunds).not.toHaveBeenCalled();

    mockConnected.mockReturnValue(true);
    renderWidget();
    await waitFor(() => expect(mockPositions).toHaveBeenCalled());
    await waitFor(() => expect(mockFunds).toHaveBeenCalled());
  });

  it("does not render fabricated greeks metrics when connected", async () => {
    mockConnected.mockReturnValue(true);
    mockPositions.mockResolvedValue(POS);
    mockFunds.mockResolvedValue(FUNDS);
    renderWidget();
    expect(await screen.findByText("Total Exposure")).toBeTruthy();
    expect(screen.getByText("Margin Utilised")).toBeTruthy();
    // The sample-only greeks metrics must NOT appear for a live user.
    expect(screen.queryByText("Net Delta")).toBeNull();
    expect(screen.queryByText("Net Theta")).toBeNull();
    expect(screen.queryByText("Max Loss")).toBeNull();
  });

  it("shows the honest note about unwired greeks metrics when connected", async () => {
    mockConnected.mockReturnValue(true);
    mockPositions.mockResolvedValue(POS);
    mockFunds.mockResolvedValue(FUNDS);
    renderWidget();
    expect(await screen.findByText(/option-greeks feed/i)).toBeTruthy();
  });
});
