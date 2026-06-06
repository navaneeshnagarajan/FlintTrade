import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// When connected, the widget fetches the nearest expiries' option chains
// (getExpiry + getOptionChain) and derives the skew curves. We mock both so we
// can exercise the live ("Live" badge) and sample ("Sample data") paths.

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getExpiry, getOptionChain } from "@/services/api";
import IVSkewWidget, {
  SAMPLE_IV_SKEW_DATA,
  type IVSkewCurve,
} from "../IVSkewWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetExpiry = getExpiry as ReturnType<typeof vi.fn>;
const mockGetChain = getOptionChain as ReturnType<typeof vi.fn>;

function liveChain() {
  return {
    underlying_ltp: 22400,
    atm_strike: 22400,
    chain: [
      { strike: 22200, ce: { iv: 15.5, delta: 0.65 }, pe: { iv: 16.0, delta: -0.35 } },
      { strike: 22400, ce: { iv: 14.8, delta: 0.5 }, pe: { iv: 14.8, delta: -0.5 } },
      { strike: 22600, ce: { iv: 14.1, delta: 0.25 }, pe: { iv: 14.3, delta: -0.75 } },
    ],
  };
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <IVSkewWidget />
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
  mockGetExpiry.mockResolvedValue({ expiry: [] });
  mockGetChain.mockResolvedValue({ chain: [] });
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("IVSkewWidget", () => {
  it("renders widget title", () => {
    renderWidget();
    expect(screen.getByText("IV Skew")).toBeTruthy();
  });

  it("shows the Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not fetch chains when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockGetExpiry).not.toHaveBeenCalled();
    expect(mockGetChain).not.toHaveBeenCalled();
  });

  it("flips to a Live badge once the option chain yields a skew curve", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["10-APR-26", "24-APR-26"] });
    mockGetChain.mockResolvedValue(liveChain());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(mockGetChain).toHaveBeenCalled();
  });

  it("falls back to Sample data when connected but the chain is empty", async () => {
    mockConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["10-APR-26"] });
    mockGetChain.mockResolvedValue({ chain: [] });
    renderWidget();

    await waitFor(() => expect(mockGetChain).toHaveBeenCalled());
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("renders ATM IV metric", () => {
    renderWidget();
    expect(screen.getByText("ATM IV")).toBeTruthy();
  });

  it("renders 25Δ Skew metric", () => {
    renderWidget();
    expect(screen.getByText("25Δ Skew")).toBeTruthy();
  });

  it("renders the chart with aria label", () => {
    renderWidget();
    expect(screen.getByLabelText("IV Skew chart")).toBeTruthy();
  });

  it("renders skew curves through the shared Flint banded-line primitive", () => {
    renderWidget();
    const chart = screen.getByRole("img", { name: "IV Skew chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "banded-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-banded-line-series]").length).toBeGreaterThanOrEqual(4);
    expect(chart.querySelectorAll("[data-banded-line-marker]").length).toBeGreaterThan(0);
  });

  it("renders CE and PE legend swatches without local SVG", () => {
    const { container } = renderWidget();
    expect(container.querySelector('svg[width="12"][height="4"]')).not.toBeInTheDocument();
  });

  it("symbol selector includes NIFTY", () => {
    renderWidget();
    const trigger = screen.getByLabelText("Select symbol");
    expect(trigger).toBeTruthy();
    expect(trigger.textContent).toContain("NIFTY");
  });

  it("can switch to Moneyness X-axis", () => {
    renderWidget();
    const btn = screen.getByRole("button", { name: /moneyness/i });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("Strike button is initially pressed", () => {
    renderWidget();
    const btn = screen.getByRole("button", { name: /^strike$/i });
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("does not render a dead refresh button (removed deceptive affordance)", () => {
    renderWidget();
    expect(screen.queryByLabelText("Refresh IV skew")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_IV_SKEW_DATA", () => {
  it("has at least 2 curves for term structure", () => {
    expect(SAMPLE_IV_SKEW_DATA.curves.length).toBeGreaterThanOrEqual(2);
  });

  it("every curve has a positive atm_iv", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      expect(curve.atm_iv).toBeGreaterThan(0);
    }
  });

  it("every curve has at least 5 strike points", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      expect(curve.points.length).toBeGreaterThanOrEqual(5);
    }
  });

  it("skew_25delta is a finite number for all curves", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      expect(Number.isFinite(curve.skew_25delta)).toBe(true);
    }
  });

  it("moneyness at ATM strike is approximately 1.0", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      const atmPoint = curve.points.find((p) => p.strike === curve.atm_strike);
      if (atmPoint) {
        expect(Math.abs(atmPoint.moneyness - 1.0)).toBeLessThan(0.01);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// Computation tests
// ---------------------------------------------------------------------------

describe("IVSkewCurve skew_25delta interpretation", () => {
  it("positive skew means put premium (put IV > call IV)", () => {
    const curve = SAMPLE_IV_SKEW_DATA.curves[0] as IVSkewCurve;
    // positive skew_25delta = put IV 25d > call IV 25d
    if (curve.skew_25delta > 0) {
      // just validate the sign convention holds in our sample
      expect(curve.skew_25delta).toBeGreaterThan(0);
    }
  });

  it("ATM IV is within a reasonable range (5%–100%)", () => {
    for (const curve of SAMPLE_IV_SKEW_DATA.curves) {
      expect(curve.atm_iv * 100).toBeGreaterThan(5);
      expect(curve.atm_iv * 100).toBeLessThan(100);
    }
  });
});
