import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

vi.mock("../useVolSurface", () => ({
  useVolSurface: vi.fn(),
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

import { useVolSurface } from "../useVolSurface";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import VolSurfaceWidget from "../VolSurfaceWidget";

const mockUseVolSurface = useVolSurface as ReturnType<typeof vi.fn>;
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

describe("VolSurfaceWidget", () => {
  it("renders loading state when connected and loading", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseVolSurface.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: true,
    });
    render(<VolSurfaceWidget />, { wrapper });
    expect(screen.getByText(/building volatility surface/i)).toBeTruthy();
  });

  it("renders empty state when connected but no data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseVolSurface.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<VolSurfaceWidget />, { wrapper });
    expect(screen.getByText(/enter symbol and at least one expiry/i)).toBeTruthy();
  });

  it("renders 3D chart when connected with live data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseVolSurface.mockReturnValue({
      data: {
        underlying: "NIFTY",
        spot_price: 24200,
        atm_strike: 24200,
        strikes: [24000, 24100, 24200, 24300, 24400],
        expiries: ["2026-03-27", "2026-04-03"],
        days_to_expiry: [3, 10],
        iv_matrix: [
          [20, 18, 17, 18, 20],
          [22, 20, 19, 20, 22],
        ],
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<VolSurfaceWidget />, { wrapper });
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText(/IV Range/i)).toBeTruthy();
  });

  it("renders error banner", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseVolSurface.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("Upstream error"),
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<VolSurfaceWidget />, { wrapper });
    expect(screen.getByText(/upstream error/i)).toBeTruthy();
  });

  it("renders sample data with FeatureTeaser when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseVolSurface.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<VolSurfaceWidget />, { wrapper });
    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
  });
});
