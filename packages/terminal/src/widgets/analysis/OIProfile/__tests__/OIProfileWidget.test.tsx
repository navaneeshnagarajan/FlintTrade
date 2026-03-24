import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

vi.mock("../useOIProfile", () => ({
  useOIProfile: vi.fn(),
}));

// Mock the api getHistory to avoid network calls
vi.mock("@/services/api", () => ({
  getHistory: vi.fn().mockResolvedValue([]),
}));

// Mock lightweight-charts
vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addSeries: vi.fn(() => ({ setData: vi.fn() })),
    resize: vi.fn(),
    remove: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
  })),
  CandlestickSeries: {},
}));

// Mock useBrokerConnected — default: disconnected
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

// Mock FeatureTeaser to render children + sentinel
vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({ children, featureName }: { children: React.ReactNode; featureName: string }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>{children}</div>
  ),
}));

import { useOIProfile } from "../useOIProfile";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import OIProfileWidget from "../OIProfileWidget";

const mockUseOIProfile = useOIProfile as ReturnType<typeof vi.fn>;
const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("OIProfileWidget", () => {
  it("renders loading state when connected and loading", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseOIProfile.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: true,
    });
    render(<OIProfileWidget />, { wrapper });
    expect(screen.getByText(/loading oi profile/i)).toBeTruthy();
  });

  it("renders empty state when connected but no data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseOIProfile.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<OIProfileWidget />, { wrapper });
    expect(screen.getByText(/enter symbol and expiry to view oi profile/i)).toBeTruthy();
  });

  it("renders OI butterfly chart and footer when connected with live data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseOIProfile.mockReturnValue({
      data: {
        underlying: "NIFTY",
        expiry: "2026-03-27",
        spot_price: 24200,
        atm_strike: 24200,
        max_pain_strike: 24250,
        strikes: [
          { strike: 24000, ce_oi: 50000, pe_oi: 30000, ce_oi_change: 1000, pe_oi_change: -500 },
          { strike: 24200, ce_oi: 80000, pe_oi: 70000, ce_oi_change: 2000, pe_oi_change: 1000 },
          { strike: 24400, ce_oi: 60000, pe_oi: 20000, ce_oi_change: -1000, pe_oi_change: -200 },
        ],
        total_ce_oi: 190000,
        total_pe_oi: 120000,
        pcr: 0.63,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<OIProfileWidget />, { wrapper });
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText(/PCR/i)).toBeTruthy();
    expect(screen.getByText(/Max Pain/i)).toBeTruthy();
  });

  it("renders error banner", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseOIProfile.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("OI fetch failed"),
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<OIProfileWidget />, { wrapper });
    expect(screen.getByText(/oi fetch failed/i)).toBeTruthy();
  });

  it("renders sample data with FeatureTeaser when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseOIProfile.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<OIProfileWidget />, { wrapper });
    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText(/PCR/i)).toBeTruthy();
  });
});
