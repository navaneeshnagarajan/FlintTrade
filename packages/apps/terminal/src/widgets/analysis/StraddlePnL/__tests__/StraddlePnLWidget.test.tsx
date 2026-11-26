import { describe, it, expect, vi, beforeAll, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

vi.mock("../useStraddlePnL", () => ({
  useStraddlePnL: vi.fn(),
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

import { useStraddlePnL } from "../useStraddlePnL";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useModeStore } from "@/stores/modeStore";
import StraddlePnLWidget from "../StraddlePnLWidget";

const mockUseStraddlePnL = useStraddlePnL as ReturnType<typeof vi.fn>;
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

describe("StraddlePnLWidget", () => {
  it("renders loading state when connected and loading", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseStraddlePnL.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: true,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByText(/simulating p&l/i)).toBeTruthy();
  });

  it("renders empty state when connected but no data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseStraddlePnL.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByText(/enter symbol and expiry/i)).toBeTruthy();
  });

  it("renders chart and summary when connected with live data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    const curve = Array.from({ length: 50 }, (_, i) => ({
      spot_price: 23000 + i * 50,
      pnl: -180 + Math.abs(i - 25) * 20,
    }));

    mockUseStraddlePnL.mockReturnValue({
      data: {
        underlying: "NIFTY",
        atm_strike: 24200,
        call_premium: 180,
        put_premium: 165,
        break_even_low: 23855,
        break_even_high: 24545,
        max_loss: -34500,
        curve,
        legs: [
          { strike: 24200, type: "CE", action: "BUY", premium: 180, lots: 1 },
          { strike: 24200, type: "PE", action: "BUY", premium: 165, lots: 1 },
        ],
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText(/Max Loss/i)).toBeTruthy();
    expect(screen.getByText(/Base Straddle/i)).toBeTruthy();
  });

  it("renders error banner", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseStraddlePnL.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("Simulation failed"),
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByText(/simulation failed/i)).toBeTruthy();
  });

  it("renders sample data with FeatureTeaser when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseStraddlePnL.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText(/Base Straddle/i)).toBeTruthy();
  });

  it("gives the expiry and leg inputs accessible names", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseStraddlePnL.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByRole("textbox", { name: "Expiry date" })).toBe(
      screen.getByPlaceholderText("Expiry (YYYY-MM-DD)"),
    );
    fireEvent.click(screen.getByRole("button", { name: /Add Leg/ }));
    fireEvent.click(screen.getByRole("button", { name: /Add Leg/ }));
    expect(screen.getByRole("spinbutton", { name: "Adjustment leg 1 strike" })).toBeTruthy();
    expect(screen.getByRole("spinbutton", { name: "Adjustment leg 1 premium" })).toBeTruthy();
    expect(screen.getByRole("spinbutton", { name: "Adjustment leg 2 strike" })).toBeTruthy();
  });
});

describe("StraddlePnLWidget example-data badge", () => {
  const payload = {
    underlying: "NIFTY",
    atm_strike: 24200,
    call_premium: 180,
    put_premium: 165,
    break_even_low: 23855,
    break_even_high: 24545,
    max_loss: -34500,
    curve: Array.from({ length: 10 }, (_, i) => ({ spot_price: 23000 + i * 50, pnl: -180 + i * 20 })),
    legs: [
      { strike: 24200, type: "CE", action: "BUY", premium: 180, lots: 1 },
      { strike: 24200, type: "PE", action: "BUY", premium: 165, lots: 1 },
    ],
  };

  function mockPayload(data: unknown) {
    mockUseStraddlePnL.mockReturnValue({
      data,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
  }

  afterEach(() => {
    useModeStore.setState({ mode: "practice" });
  });

  it("badges a connected payload the backend flags as sample", () => {
    useModeStore.setState({ mode: "practice" });
    mockUseBrokerConnected.mockReturnValue(true);
    mockPayload({ ...payload, is_sample_data: true });

    render(<StraddlePnLWidget />, { wrapper });

    expect(screen.getByTestId("example-data-badge").textContent).toBe("Example data");
  });

  it("fails closed when a connected payload omits the provenance flag", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockPayload(payload);

    render(<StraddlePnLWidget />, { wrapper });

    expect(screen.getByTestId("example-data-badge")).toBeTruthy();
  });

  it("drops the badge for an explicitly live payload", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockPayload({ ...payload, is_sample_data: false });

    render(<StraddlePnLWidget />, { wrapper });

    expect(screen.queryByTestId("example-data-badge")).toBeNull();
  });

  it("leaves the disconnected preview to the teaser's own label", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockPayload(undefined);

    render(<StraddlePnLWidget />, { wrapper });

    expect(screen.queryByTestId("example-data-badge")).toBeNull();
  });

  it("stays hidden in Explore", () => {
    useModeStore.setState({ mode: "explore" });
    mockUseBrokerConnected.mockReturnValue(true);
    mockPayload({ ...payload, is_sample_data: true });

    render(<StraddlePnLWidget />, { wrapper });

    expect(screen.queryByTestId("example-data-badge")).toBeNull();
  });
});
