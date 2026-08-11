/**
 * IVSmileWidget tests.
 *
 * This suite is the union of the old IVSmile suite and the retired IVSkew
 * suite (merge 2.1). The IVSkew-only invariants carried over verbatim in
 * intent:
 *   - the four-state provenance badge (Live / Sample data / Loading /
 *     Unavailable);
 *   - the fail-closed live gate, including the connected-but-flagged-sample
 *     payload and the connected-payload-with-no-provenance case (which the old
 *     IVSmile promoted to a chart under a "Sample data" badge);
 *   - the skew view rendering through the shared Flint banded-line primitive
 *     with no hand-rolled local SVG;
 *   - the deliberate absence of a refresh control.
 * The transform's percent-vs-decimal detection is pinned in
 * `ivSkewTransform.test.ts`, which moved here with the module.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { WidgetProps } from "@/types/widgets";

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

vi.mock("../useIVSmile", () => ({
  useIVSmile: vi.fn(),
}));

// Mock useBrokerConnected — default: disconnected
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

const apiMocks = vi.hoisted(() => ({ getExpiry: vi.fn() }));

vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
}));

// Mock FeatureTeaser to render children + sentinel
vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({ children, featureName }: { children: React.ReactNode; featureName: string }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>{children}</div>
  ),
}));

import { useIVSmile } from "../useIVSmile";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import IVSmileWidget from "../IVSmileWidget";
import { SAMPLE_IV_SMILE_DATA } from "../sampleData";

const mockUseIVSmile = useIVSmile as ReturnType<typeof vi.fn>;
const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

/** Far-future expiries so the nearest-future choice is deterministic. */
const FUTURE_EXPIRIES = ["2020-01-30", "2050-02-06", "2050-01-30"];

function idleQuery(overrides: Record<string, unknown> = {}) {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
    ...overrides,
  };
}

function liveSmile() {
  return {
    underlying: "NIFTY",
    spot_price: 24200,
    is_sample_data: false,
    curves: [
      {
        expiry: "2026-03-27",
        days_to_expiry: 3,
        atm_iv: 0.186,
        atm_strike: 24200,
        skew_25delta: 0.032,
        points: [
          { strike: 24000, moneyness: 0.9917, call_iv: 0.22, put_iv: 0.28 },
          { strike: 24200, moneyness: 1.0, call_iv: 0.186, put_iv: 0.186 },
          { strike: 24400, moneyness: 1.0083, call_iv: 0.19, put_iv: 0.18 },
        ],
      },
    ],
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderWidget(params: Record<string, unknown> = {}) {
  return render(<IVSmileWidget {...makeWidgetPanelProps({ params })} />, { wrapper });
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
  mockUseBrokerConnected.mockReturnValue(false);
  mockUseIVSmile.mockReturnValue(idleQuery());
  apiMocks.getExpiry.mockResolvedValue({ expiry: FUTURE_EXPIRIES });
});

describe("IVSmileWidget — smile view", () => {
  it("renders loading state when connected and loading", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue(idleQuery({ isLoading: true, isFetching: true }));
    renderWidget();
    expect(screen.getByText(/loading iv smile/i)).toBeTruthy();
    expect(screen.getByText("Loading")).toBeInTheDocument();
  });

  it("renders empty state when connected but no data", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    renderWidget();
    expect(await screen.findByText(/select symbol to view iv smile/i)).toBeInTheDocument();
  });

  it("renders chart and metrics when connected with live data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue(idleQuery({ data: liveSmile() }));
    renderWidget();
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText(/ATM IV/i)).toBeTruthy();
    expect(screen.getByText(/25Δ Skew/i)).toBeTruthy();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("renders error banner", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue(idleQuery({
      isError: true,
      error: new Error("IV data unavailable"),
    }));
    renderWidget();
    expect(screen.getByText(/iv data unavailable/i)).toBeTruthy();
  });

  it("renders sample data with FeatureTeaser when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Provenance — the fail-closed posture carried over from IVSkew
// ---------------------------------------------------------------------------

describe("IVSmileWidget — provenance", () => {
  it("refuses to promote a connected payload with missing provenance", async () => {
    const { is_sample_data: _flag, ...unknownProvenance } = liveSmile();
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue(idleQuery({ data: unknownProvenance }));

    renderWidget();

    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByTestId("plotly-chart")).toBeNull();
    expect(screen.queryByText(/ATM IV/i)).toBeNull();
    expect(screen.getByText(/no iv data available/i)).toBeInTheDocument();
  });

  it("rejects a connected IV smile explicitly flagged as sample data", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue(idleQuery({
      data: { ...liveSmile(), is_sample_data: true },
    }));

    renderWidget();

    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryByTestId("plotly-chart")).toBeNull();
  });

  it("does not render a connected half-complete option-leg point as live IV", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue(idleQuery({
      data: {
        underlying: "NIFTY",
        spot_price: 24200,
        is_sample_data: false,
        curves: [
          {
            expiry: "2026-03-27",
            days_to_expiry: 3,
            atm_iv: 0.186,
            atm_strike: 24200,
            skew_25delta: 0.032,
            points: [{ strike: 24200, moneyness: 1, call_iv: 0.186, put_iv: 0 }],
          },
        ],
      },
    }));

    renderWidget();

    expect(await screen.findByText(/no iv data available/i)).toBeInTheDocument();
    expect(screen.queryByTestId("plotly-chart")).toBeNull();
    expect(screen.queryByText(/ATM IV/i)).toBeNull();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("does not reach the network while disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderWidget();
    expect(apiMocks.getExpiry).not.toHaveBeenCalled();
    expect(mockUseIVSmile).toHaveBeenLastCalledWith("NIFTY", "NFO", undefined, false);
  });

  it("does not render a refresh control in either view", () => {
    renderWidget();
    expect(screen.queryByLabelText(/refresh/i)).toBeNull();
    expect(screen.queryByTitle("Refresh")).toBeNull();
    expect(screen.queryByLabelText("Refresh IV skew")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Skew view — the retired IVSkew widget's presentation
// ---------------------------------------------------------------------------

describe("IVSmileWidget — skew view", () => {
  it("renders skew curves through the shared Flint banded-line primitive", () => {
    renderWidget({ view: "skew" });
    expect(screen.getByText("IV Skew")).toBeTruthy();
    const chart = screen.getByRole("img", { name: "IV Skew chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "banded-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-banded-line-series]").length).toBeGreaterThanOrEqual(4);
    expect(chart.querySelectorAll("[data-banded-line-marker]").length).toBeGreaterThan(0);
  });

  it("renders CE and PE legend swatches without local SVG", () => {
    const { container } = renderWidget({ view: "skew" });
    expect(container.querySelector('svg[width="12"][height="4"]')).not.toBeInTheDocument();
    expect(screen.getByText("CE", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("PE", { selector: "span" })).toBeInTheDocument();
  });

  it("keeps the smile view on Plotly and the skew view off it", () => {
    const { unmount } = renderWidget();
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.queryByLabelText("IV Skew chart")).not.toBeInTheDocument();
    unmount();

    renderWidget({ view: "skew" });
    expect(screen.queryByTestId("plotly-chart")).toBeNull();
    expect(screen.getByLabelText("IV Skew chart")).toBeTruthy();
  });

  it("falls back to the smile view for an unrecognised params.view", () => {
    renderWidget({ view: "candlestick" });
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText("IV Smile")).toBeTruthy();
  });

  it("persists a view change into the panel params", () => {
    const updateParameters = vi.fn();
    render(
      <IVSmileWidget
        {...makeWidgetPanelProps({
          params: { view: "smile" },
          api: { updateParameters } as unknown as WidgetProps["api"],
        })}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "Skew" }));

    expect(updateParameters).toHaveBeenCalledWith({ view: "skew" });
    expect(screen.getByLabelText("IV Skew chart")).toBeTruthy();
  });

  it("applies the CE/PE leg filter to the skew curves", () => {
    const { container } = renderWidget({ view: "skew" });
    const both = container.querySelectorAll("[data-banded-line-series]").length;

    fireEvent.click(screen.getByRole("button", { name: "CE" }));

    const ceOnly = container.querySelectorAll("[data-banded-line-series]").length;
    expect(ceOnly).toBe(both / 2);
    expect(screen.queryByText("PE", { selector: "span" })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

describe("IVSmileWidget — controls", () => {
  it("symbol selector includes NIFTY", () => {
    renderWidget();
    const trigger = screen.getByLabelText("Select symbol");
    expect(trigger).toBeTruthy();
    expect(trigger.textContent).toContain("NIFTY");
  });

  it("Strike button is initially pressed", () => {
    renderWidget();
    expect(screen.getByRole("button", { name: /^strike$/i }).getAttribute("aria-pressed")).toBe("true");
  });

  it("can switch to Moneyness X-axis", () => {
    renderWidget();
    const btn = screen.getByRole("button", { name: /moneyness/i });
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });
});

// ---------------------------------------------------------------------------
// Expiry selection — neither typed-or-nothing nor a silent backend default
// ---------------------------------------------------------------------------

describe("IVSmileWidget — expiry selection", () => {
  it("auto-selects the nearest FUTURE expiry once connected", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    renderWidget();

    await waitFor(() =>
      expect(mockUseIVSmile).toHaveBeenLastCalledWith("NIFTY", "NFO", ["2050-01-30"], true),
    );
    expect(apiMocks.getExpiry).toHaveBeenCalledWith("NIFTY", "NFO", "options");
  });

  it("never sends an empty expiry list, so the backend default cannot apply", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2020-01-30"] });
    renderWidget();

    expect(await screen.findByText(/no future expiry is available/i)).toBeInTheDocument();
    expect(mockUseIVSmile).toHaveBeenLastCalledWith("NIFTY", "NFO", undefined, true);
  });

  it("lets a typed expiry override the auto-selected one", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    renderWidget();
    await waitFor(() =>
      expect(mockUseIVSmile).toHaveBeenLastCalledWith("NIFTY", "NFO", ["2050-01-30"], true),
    );

    fireEvent.change(
      screen.getByLabelText(/expiries \(comma-separated/i),
      { target: { value: "2050-03-27, 2050-04-24" } },
    );

    // Every typed expiry reaches the hook: the route now builds one curve per
    // expiry instead of silently dropping all but the first.
    expect(mockUseIVSmile).toHaveBeenLastCalledWith(
      "NIFTY",
      "NFO",
      ["2050-03-27", "2050-04-24"],
      true,
    );
  });
});

// ---------------------------------------------------------------------------
// Sample data — invariants ported from the retired SAMPLE_IV_SKEW_DATA suite
// ---------------------------------------------------------------------------

describe("SAMPLE_IV_SMILE_DATA", () => {
  it("has at least 2 curves for term structure", () => {
    expect(SAMPLE_IV_SMILE_DATA.curves.length).toBeGreaterThanOrEqual(2);
  });

  it("every curve has a positive atm_iv", () => {
    for (const curve of SAMPLE_IV_SMILE_DATA.curves) {
      expect(curve.atm_iv).toBeGreaterThan(0);
    }
  });

  it("every curve has at least 5 strike points", () => {
    for (const curve of SAMPLE_IV_SMILE_DATA.curves) {
      expect(curve.points.length).toBeGreaterThanOrEqual(5);
    }
  });

  it("skew_25delta is a finite number for all curves", () => {
    for (const curve of SAMPLE_IV_SMILE_DATA.curves) {
      expect(Number.isFinite(curve.skew_25delta)).toBe(true);
    }
  });

  it("moneyness at the ATM strike is approximately 1.0", () => {
    for (const curve of SAMPLE_IV_SMILE_DATA.curves) {
      const atmPoint = curve.points.find((p) => p.strike === curve.atm_strike);
      expect(atmPoint).toBeDefined();
      expect(Math.abs((atmPoint?.moneyness ?? 0) - 1.0)).toBeLessThan(0.01);
    }
  });

  it("ATM IV is within a reasonable range (5%–100%)", () => {
    for (const curve of SAMPLE_IV_SMILE_DATA.curves) {
      expect(curve.atm_iv * 100).toBeGreaterThan(5);
      expect(curve.atm_iv * 100).toBeLessThan(100);
    }
  });

  it("is flagged as sample data so the live gate can reject it", () => {
    expect(SAMPLE_IV_SMILE_DATA.is_sample_data).toBe(true);
  });
});
