import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../useArbitrageScanner", () => ({
  useArbitrageScanner: vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({ children, featureName }: { children: React.ReactNode; featureName: string }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>
      {children}
    </div>
  ),
}));

import { useArbitrageScanner } from "../useArbitrageScanner";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useModeStore } from "@/stores/modeStore";
import ArbitrageScannerWidget from "../ArbitrageScannerWidget";
import { SAMPLE_ARBITRAGE_SCAN } from "../sampleData";

const mockHook = useArbitrageScanner as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

const IDLE_QUERY = {
  data: undefined,
  isLoading: false,
  isFetching: false,
  isError: false,
  error: null,
  refetch: vi.fn(),
};

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("ArbitrageScannerWidget", () => {
  it("renders sample scan with demo affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({ ...IDLE_QUERY });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.queryByText(/Sample data/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Arbitrage Scanner");
    // Both section tables present (exact match avoids the subtitle collision).
    expect(screen.getByText("Cash-future basis")).toBeInTheDocument();
    expect(screen.getByText("Cross-exchange gaps")).toBeInTheDocument();
    // First cash-future opportunity underlying rendered.
    expect(screen.getByText(SAMPLE_ARBITRAGE_SCAN.cash_future[0].underlying)).toBeInTheDocument();
  });

  it("passes the collected universe and edge threshold to the scanner hook", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({ ...IDLE_QUERY });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(mockHook).toHaveBeenCalledWith(
      expect.objectContaining({
        universe: expect.arrayContaining(["NIFTY", "RELIANCE"]),
        edgeThresholdPct: 1.0,
      }),
      true,
    );
  });

  it("renders live scan without demo affordance when connected and not sample", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      ...IDLE_QUERY,
      data: {
        is_sample_data: false,
        scan: {
          risk_free_rate: 0.065,
          edge_threshold_pct: 1,
          cash_future: [
            { underlying: "INFY", exchange: "NFO", spot: 1500, future_price: 1512, days_to_expiry: 8, basis: 12, basis_pct: 0.8, fair_basis: 2.1, mispricing: 9.9, annualised_return_pct: 36.5, signal: "cash_and_carry" },
          ],
          cross_exchange: [],
        },
      },
    });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.queryByText(/Sample data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("INFY")).toBeInTheDocument();
    // The empty cross-exchange table shows its honest per-section empty state.
    expect(screen.getByText(/No cross-exchange gaps found/i)).toBeInTheDocument();
  });

  it("keeps the demo affordance when a connected response is flagged is_sample_data", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      ...IDLE_QUERY,
      data: { is_sample_data: true, scan: SAMPLE_ARBITRAGE_SCAN },
    });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.queryByText(/Sample data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
  });

  it("shows an honest empty state for a real scan with no opportunities", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      ...IDLE_QUERY,
      data: {
        is_sample_data: false,
        scan: { risk_free_rate: 0.07, edge_threshold_pct: 1, cash_future: [], cross_exchange: [] },
      },
    });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.getByText(/No arbitrage opportunities found/i)).toBeInTheDocument();
    expect(screen.queryByText(/Sample data/i)).not.toBeInTheDocument();
  });

  it("shows an error state instead of fabricated tables when the scan fails", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      ...IDLE_QUERY,
      isError: true,
      error: new Error("No live quotes available for the scan universe — scan not performed."),
    });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.getByText(/No live quotes available/i)).toBeInTheDocument();
    // No sample tables leak into the connected error state.
    expect(
      screen.queryByText(SAMPLE_ARBITRAGE_SCAN.cash_future[0].underlying),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Sample data/i)).not.toBeInTheDocument();
  });
});

describe("ArbitrageScannerWidget example-data badge", () => {
  afterEach(() => {
    useModeStore.setState({ mode: "practice" });
  });

  it("badges a connected scan the backend flags as sample", () => {
    useModeStore.setState({ mode: "practice" });
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({ ...IDLE_QUERY, data: { is_sample_data: true, scan: SAMPLE_ARBITRAGE_SCAN } });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.getByTestId("example-data-badge")).toHaveTextContent("Example data");
  });

  it("fails closed when a connected scan omits the provenance flag", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({ ...IDLE_QUERY, data: { scan: SAMPLE_ARBITRAGE_SCAN } });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.getByTestId("example-data-badge")).toBeInTheDocument();
  });

  it("drops the badge for an explicitly live scan", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({ ...IDLE_QUERY, data: { is_sample_data: false, scan: SAMPLE_ARBITRAGE_SCAN } });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.queryByTestId("example-data-badge")).not.toBeInTheDocument();
  });

  it("leaves the disconnected preview to the teaser's own label", () => {
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({ ...IDLE_QUERY });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.getByTestId("feature-teaser")).toBeInTheDocument();
    expect(screen.queryByTestId("example-data-badge")).not.toBeInTheDocument();
  });

  it("stays hidden in Explore, where the Mode line already says Example data", () => {
    useModeStore.setState({ mode: "explore" });
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({ ...IDLE_QUERY, data: { is_sample_data: true, scan: SAMPLE_ARBITRAGE_SCAN } });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.queryByTestId("example-data-badge")).not.toBeInTheDocument();
  });
});
