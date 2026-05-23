import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock PlotlyChart to avoid loading Plotly in tests
vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

// Mock the useGEX hook
vi.mock("../useGEX", () => ({
  useGEX: vi.fn(),
}));

// Mock useBrokerConnected — default: disconnected (shows sample data + teaser)
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

// Mock FeatureTeaser to render children + sentinel
vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({ children, featureName }: { children: React.ReactNode; featureName: string }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>{children}</div>
  ),
}));

import { useGEX } from "../useGEX";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import GEXWidget from "../GEXWidget";

const mockUseGEX = useGEX as ReturnType<typeof vi.fn>;
const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeAll(() => {
  // suppress plotly ResizeObserver noise
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("GEXWidget", () => {
  it("renders loading state when connected and loading", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGEX.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: true,
    });
    render(<GEXWidget />, { wrapper });
    expect(screen.getByText(/loading gex data/i)).toBeTruthy();
  });

  it("renders empty state when connected but no data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGEX.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<GEXWidget />, { wrapper });
    expect(screen.getByText(/enter symbol and expiry/i)).toBeTruthy();
  });

  it("renders chart and summary when connected with live data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGEX.mockReturnValue({
      data: {
        underlying: "NIFTY",
        spot_price: 24200,
        atm_strike: 24200,
        strikes: [
          { strike: 24000, call_gex: 1e8, put_gex: -5e7, net_gex: 5e7, call_oi: 1000, put_oi: 500 },
          { strike: 24200, call_gex: 2e8, put_gex: -1e8, net_gex: 1e8, call_oi: 2000, put_oi: 800 },
        ],
        gamma_flip_strike: 24100,
        dealer_zone: "Dealer Long Gamma",
        total_call_gex: 3e8,
        total_put_gex: -1.5e8,
        net_gex: 1.5e8,
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<GEXWidget />, { wrapper });
    expect(screen.getAllByTestId("plotly-chart").length).toBeGreaterThan(0);
    expect(screen.getByText(/Net GEX/i)).toBeTruthy();
    expect(screen.getByText(/Dealer Long Gamma/i)).toBeTruthy();
  });

  it("renders error banner on failure", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseGEX.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("Network error"),
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<GEXWidget />, { wrapper });
    expect(screen.getByText(/network error/i)).toBeTruthy();
  });

  it("renders sample data with FeatureTeaser when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseGEX.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<GEXWidget />, { wrapper });
    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getAllByTestId("plotly-chart").length).toBeGreaterThan(0);
  });
});
