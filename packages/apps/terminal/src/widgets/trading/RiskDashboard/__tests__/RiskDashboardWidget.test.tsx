/**
 * Tests for the merged Risk widget (component id `riskdashboard`).
 *
 * Carries every honesty pin from BOTH merged widgets:
 *   - from Risk Dashboard: computeLiveRisk is the single metric source, the
 *     margin-only gauge, exposure as an info stat, no spurious red at zero
 *     balance, and no fabricated greeks;
 *   - from Risk Panel: a position row never stands in for lot usage, an order
 *     count never stands in for an order rate, local settings are references
 *     rather than enforced limits, and the status wording only claims what the
 *     widget observes.
 *
 * Plus the pins the merge itself creates: ONE threshold set for every band, and
 * a sample that cannot promise a metric the live path is unable to produce.
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: () => ({ data: [] }),
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

// The MTM target/stop-loss references the widget renders as bars are the same
// settingsStore.riskLimits values MTM Monitor plots as chart price lines.
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      riskLimits: {
        maxPositionLots: 10,
        mtmStoploss: 5000,
        mtmTarget: 10000,
        maxOrdersPerMinute: 20,
      },
    }),
}));

vi.mock("zustand/react/shallow", () => ({
  useShallow: (fn: unknown) => fn,
}));

import { getPositionbook, getFunds } from "@/services/api";
import { totalPositionMtm } from "@/lib/pnl";
import type { Position, Funds } from "@/types/api";
import RiskWidget, {
  SAMPLE_RISK_DATA,
  computeLiveRisk,
  levelForUsage,
} from "../RiskDashboardWidget";

import type { TrafficLight } from "../RiskDashboardWidget";
import {
  resetAccountRuntime,
  setAccountRuntime,
} from "@/test-utils/accountQueryHarness";

const mockPositions = getPositionbook as ReturnType<typeof vi.fn>;
const mockFunds = getFunds as ReturnType<typeof vi.fn>;

const POS: Position[] = [
  { symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 2500, ltp: 2510, pnl: 100, pnlPercent: 0.4 },
  { symbol: "TCS", exchange: "NSE", product: "MIS", quantity: -5, averagePrice: 3000, ltp: 2990, pnl: 50, pnlPercent: 0.3 },
];
const FUNDS: Funds = { availableCash: 40_000, usedMargin: 60_000, totalBalance: 100_000 };

/** One position marked 2500 rupees down — exactly 50% of the 5000 local stop. */
const POS_HALF_STOP: Position[] = [
  { symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 2500, ltp: 2250, pnl: -2500, pnlPercent: -10 },
];

/** 3600 down — 72% of the 5000 local stop: amber under 70/90, green under 80/95. */
const POS_72PCT_STOP: Position[] = [
  { symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 2500, ltp: 2140, pnl: -3600, pnlPercent: -14.4 },
];

function renderWidget(ui: ReactElement = <RiskWidget />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

/** Render with a live scope and the given book/funds already resolving. */
function renderLive(positions: Position[] = POS, funds: Funds = FUNDS) {
  setAccountRuntime({ mode: "live" });
  mockPositions.mockResolvedValue(positions);
  mockFunds.mockResolvedValue(funds);
  return renderWidget();
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  setAccountRuntime({ accounts: [], mode: "explore" });
  mockPositions.mockReset();
  mockPositions.mockResolvedValue([]);
  mockFunds.mockReset();
  mockFunds.mockResolvedValue({ availableCash: 0, usedMargin: 0, totalBalance: 0 });
});

afterEach(() => {
  resetAccountRuntime();
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("Risk widget", () => {
  it("renders widget title", () => {
    renderWidget();
    expect(screen.getByText("Risk")).toBeTruthy();
  });

  it("shows Sample badge in Explore", () => {
    renderWidget();
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("does not show Sample badge when connected", async () => {
    renderLive();
    await waitFor(() => expect(mockPositions).toHaveBeenCalled());
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("reads and labels the Practice sandbox without a live broker", async () => {
    setAccountRuntime({ accounts: [], mode: "practice" });
    renderWidget();

    expect(await screen.findByText("Practice")).toBeTruthy();
    await waitFor(() => expect(mockPositions).toHaveBeenCalled());
    await waitFor(() => expect(mockFunds).toHaveBeenCalled());
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders overall status banner", () => {
    renderWidget();
    expect(screen.getByLabelText(/Overall risk status/i)).toBeTruthy();
  });

  it("renders risk metrics section", () => {
    renderWidget();
    expect(screen.getByLabelText("Risk metrics")).toBeTruthy();
  });

  it("renders all sample metric labels", () => {
    renderWidget();
    for (const m of SAMPLE_RISK_DATA.metrics) {
      expect(screen.getByText(m.label)).toBeTruthy();
    }
  });

  it("renders legend with three traffic light levels", () => {
    renderWidget();
    expect(screen.getByText(/Within limits/i)).toBeTruthy();
    expect(screen.getByText(/Approaching/i)).toBeTruthy();
    expect(screen.getByText(/Breached/i)).toBeTruthy();
  });

  it("renders metric cards with aria labels", () => {
    renderWidget();
    for (const m of SAMPLE_RISK_DATA.metrics) {
      expect(screen.getByLabelText(new RegExp(m.label, "i"))).toBeTruthy();
    }
  });

  it("renders metric gauges through the shared Flint radial gauge primitive", () => {
    const { container } = renderWidget();
    const gauges = container.querySelectorAll('[data-flint-chart="radial-gauge"]');
    expect(gauges.length).toBe(SAMPLE_RISK_DATA.metrics.length);
  });
});

// ---------------------------------------------------------------------------
// Sample data — may not promise what the live path cannot produce
// ---------------------------------------------------------------------------

describe("SAMPLE_RISK_DATA", () => {
  it("shows only metrics the live path can also produce", () => {
    const liveIds = computeLiveRisk(POS, FUNDS).metrics.map((m) => m.id);
    expect(SAMPLE_RISK_DATA.metrics.map((m) => m.id)).toEqual(liveIds);
  });

  it("carries no fabricated greeks or max-loss figures", () => {
    const ids = SAMPLE_RISK_DATA.metrics.map((m) => m.id);
    for (const fabricated of ["delta", "theta", "maxloss"]) {
      expect(ids).not.toContain(fabricated);
    }
    const infoLabels = (SAMPLE_RISK_DATA.infoStats ?? []).map((s) => s.label);
    expect(infoLabels).not.toContain("Net Delta");
    expect(infoLabels).not.toContain("Net Theta");
    expect(infoLabels).not.toContain("Max Loss");
  });

  it("shows only info stats the live path can also produce", () => {
    const liveLabels = (computeLiveRisk(POS, FUNDS).infoStats ?? []).map((s) => s.label);
    for (const s of SAMPLE_RISK_DATA.infoStats ?? []) {
      expect(liveLabels).toContain(s.label);
    }
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
    const hasRed = SAMPLE_RISK_DATA.metrics.some((m) => m.level === "red");
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
    expect(new Set(ids).size).toBe(ids.length);
  });
});

// ---------------------------------------------------------------------------
// One threshold set — the merge's core invariant
// ---------------------------------------------------------------------------

describe("levelForUsage", () => {
  it("bands at 70/90 for every usage percentage in the widget", () => {
    expect(levelForUsage(0)).toBe("green");
    expect(levelForUsage(69.9)).toBe("green");
    expect(levelForUsage(70)).toBe("amber");
    expect(levelForUsage(89.9)).toBe("amber");
    expect(levelForUsage(90)).toBe("red");
    expect(levelForUsage(100)).toBe("red");
  });

  it("is the same function the margin gauge is banded with", () => {
    const amber = computeLiveRisk([], { availableCash: 25_000, usedMargin: 75_000, totalBalance: 100_000 });
    expect(amber.metrics[0]?.level).toBe(levelForUsage(75));
    const red = computeLiveRisk([], { availableCash: 5_000, usedMargin: 95_000, totalBalance: 100_000 });
    expect(red.metrics[0]?.level).toBe(levelForUsage(95));
  });
});

// ---------------------------------------------------------------------------
// computeLiveRisk — real data only, no fabricated greeks
// ---------------------------------------------------------------------------

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

  it("shows the position row count as an informational stat, never as a lot gauge", () => {
    const data = computeLiveRisk(POS, FUNDS);
    // A position row is not a lot: it must never acquire a limit or a gauge.
    expect(data.metrics.find((m) => m.id === "positions")).toBeUndefined();
    expect(data.infoStats?.find((s) => s.label === "Open Positions")?.value).toBe("2");
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
    // Available cash is unknown, not zero.
    expect(data.infoStats?.find((s) => s.label === "Available Cash")?.value).toBe("—");
  });

  it("is all-clear (green) when flat with no funds", () => {
    expect(computeLiveRisk([], undefined).overallLevel).toBe("green");
  });

  it("takes daily P&L from the shared mark-to-market definition", () => {
    // Not a re-sum of the raw broker `pnl` field — the same lib/pnl definition
    // MTM Monitor plots, so the two widgets cannot disagree about the session.
    expect(computeLiveRisk(POS_HALF_STOP, FUNDS).dayPnl).toBe(totalPositionMtm(POS_HALF_STOP));
    expect(computeLiveRisk([], undefined).dayPnl).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Connected behaviour
// ---------------------------------------------------------------------------

describe("Risk widget (connected)", () => {
  it("fetches positions + funds only when there is an account source", async () => {
    renderWidget(); // Explore
    expect(mockPositions).not.toHaveBeenCalled();
    expect(mockFunds).not.toHaveBeenCalled();

    renderLive();
    await waitFor(() => expect(mockPositions).toHaveBeenCalled());
    await waitFor(() => expect(mockFunds).toHaveBeenCalled());
  });

  it("gates live risk account data when no broker is configured", () => {
    setAccountRuntime({ accounts: [], mode: "live" });
    renderWidget();

    expect(mockPositions).not.toHaveBeenCalled();
    expect(mockFunds).not.toHaveBeenCalled();
    expect(screen.getByText("Broker required")).toBeTruthy();
    expect(screen.getByText(/Connect a broker to load risk metrics/i)).toBeTruthy();
  });

  it("does not render fabricated greeks metrics when connected", async () => {
    renderLive();
    expect(await screen.findByText("Total Exposure")).toBeTruthy();
    expect(screen.getByText("Margin Utilised")).toBeTruthy();
    // The sample-only greeks metrics must NOT appear for a live user.
    expect(screen.queryByText("Net Delta")).toBeNull();
    expect(screen.queryByText("Net Theta")).toBeNull();
    expect(screen.queryByText("Max Loss")).toBeNull();
  });

  it("shows the honest note about unwired greeks metrics when connected", async () => {
    renderLive();
    expect(await screen.findByText(/option-greeks feed/i)).toBeTruthy();
  });

  it("does not substitute position rows for lot usage", async () => {
    renderLive();
    expect(await screen.findByText("Position lot usage")).toBeTruthy();
    expect(screen.getByText(/instrument lot metadata is not loaded/i)).toBeTruthy();
    expect(screen.queryByText("Position Lots")).toBeNull();
  });

  it("does not substitute open-order count for orders per minute", async () => {
    renderLive();
    expect(await screen.findByText("Order rate")).toBeTruthy();
    expect(screen.getByText(/rolling placement events are not tracked/i)).toBeTruthy();
    expect(screen.queryByText("Open Orders")).toBeNull();
  });

  it("shows local values as references rather than enforced limits", () => {
    renderWidget();
    expect(screen.getByText("Local Reference Values")).toBeTruthy();
    expect(screen.getByText("Lot reference")).toBeTruthy();
    expect(screen.getByText("Order-rate reference")).toBeTruthy();
    expect(screen.queryByText("Configured Limits")).toBeNull();
  });

  it("describes only the observed indicators when usage is low", async () => {
    renderLive(POS_HALF_STOP, FUNDS);
    // Wait for the loaded book (50% of the stop), then read the verdict:
    // 60% margin and 50% of the local stop are both inside the green band.
    expect(await screen.findByText("50%")).toBeTruthy();
    expect(screen.getByText("Indicators normal")).toBeTruthy();
  });

  it("measures the daily stop-loss bar against settingsStore.riskLimits", async () => {
    renderLive(POS_HALF_STOP, FUNDS);
    expect(screen.getByText("Daily SL Exposure")).toBeTruthy();
    // 2500 down against the mocked 5000 stop — the denominator is the shared
    // setting MTM Monitor draws as a price line, not a widget-local constant.
    expect(await screen.findByText("50%")).toBeTruthy();
  });

  it("warns at 70% of the daily stop, not the retired panel's 80%", async () => {
    renderLive(POS_72PCT_STOP, FUNDS);
    expect(await screen.findByText("Observed caution")).toBeTruthy();
  });
});
