/**
 * FlowsTab.test — adapted from the retired FiiLongShort suite, plus the
 * FII/DII cash-segment table and DII derivative rows that reuse the live
 * wiring from Market Intelligence's flows tab (same getFiiDiiData call).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// Mock the data hooks so no network call happens.
vi.mock("../useFiiLongShort", () => ({
  useFiiLongShort: vi.fn(),
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

vi.mock("@/services/ftApi.screener", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi.screener")>();
  return { ...actual, getFiiDiiData: vi.fn() };
});

import { useFiiLongShort } from "../useFiiLongShort";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getFiiDiiData } from "@/services/ftApi.screener";
import FlowsTab from "../tabs/FlowsTab";
import { SAMPLE_FII_LONG_SHORT } from "../sampleData";

const mockUseHook = useFiiLongShort as ReturnType<typeof vi.fn>;
const mockUseConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetFiiDii = getFiiDiiData as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** A minimal but complete FiiDiiSnapshot for the derivative rows. */
function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    trade_date: "2026-07-25",
    fii_buy: 12000, fii_sell: 9000, fii_net: 3000,
    dii_buy: 8000, dii_sell: 9500, dii_net: -1500,
    fii_idx_fut_long: 1, fii_idx_fut_short: 2, fii_idx_fut_net: -1,
    fii_stk_fut_long: 3, fii_stk_fut_short: 4, fii_stk_fut_net: -1,
    fii_idx_call_long: 5, fii_idx_call_short: 6, fii_idx_call_net: -1,
    fii_idx_put_long: 7, fii_idx_put_short: 8, fii_idx_put_net: -1,
    dii_idx_fut_long: 48200, dii_idx_fut_short: 24800, dii_idx_fut_net: 23400,
    dii_stk_fut_long: 42840, dii_stk_fut_short: 28400, dii_stk_fut_net: 14440,
    pcr: 1.0, sentiment_score: 0.5, updated_at: "2026-07-25 18:00 IST",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetFiiDii.mockResolvedValue({ is_sample_data: true, latest: null, trend: null });
});

describe("FlowsTab — FII long/short", () => {
  it("renders sample data with a demo affordance when disconnected", () => {
    mockUseConnected.mockReturnValue(false);
    mockUseHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });

    render(<FlowsTab />, { wrapper });

    // Demo affordance is visible and the teaser wraps the content.
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "FII Long/Short");
    // All four segments render.
    for (const seg of SAMPLE_FII_LONG_SHORT.segments) {
      expect(screen.getByText(seg.label)).toBeInTheDocument();
    }
  });

  it("renders live data without the demo affordance when connected", () => {
    mockUseConnected.mockReturnValue(true);
    mockUseHook.mockReturnValue({
      data: {
        is_sample_data: false,
        ratio: { ...SAMPLE_FII_LONG_SHORT, bias_label: "Strongly Long", futures_bias: 68.0 },
      },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<FlowsTab />, { wrapper });

    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("Strongly Long")).toBeInTheDocument();
  });

  it("keeps the demo affordance when a connected response omits is_sample_data (fail-closed)", () => {
    mockUseConnected.mockReturnValue(true);
    mockUseHook.mockReturnValue({
      data: { ratio: SAMPLE_FII_LONG_SHORT },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<FlowsTab />, { wrapper });

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
  });
});

describe("FlowsTab — FII/DII cash flows", () => {
  it("shows the disclosed sample cash table with a Sample chip when disconnected", () => {
    mockUseConnected.mockReturnValue(false);
    mockUseHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });

    render(<FlowsTab />, { wrapper });

    // Disconnected: the query never fires; the disclosed sample rows render.
    expect(mockGetFiiDii).not.toHaveBeenCalled();
    expect(screen.getByText(/Capital Market Segment/)).toBeInTheDocument();
    const heading = screen.getByText(/Capital Market Segment/);
    expect(heading.querySelector("span")?.textContent).toBe("Sample");
    // No DII derivative table without a real snapshot — never fabricated.
    expect(screen.queryByText(/DII Derivative Positioning/)).not.toBeInTheDocument();
  });

  it("renders live cash rows and DII derivative rows with Live chips", async () => {
    mockUseConnected.mockReturnValue(true);
    mockUseHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });
    mockGetFiiDii.mockResolvedValue({
      is_sample_data: false,
      latest: snapshot(),
      trend: { days: 1, snapshots: [snapshot()], fii_net_total: 3000, dii_net_total: -1500, avg_sentiment: 0.5 },
    });

    render(<FlowsTab />, { wrapper });

    expect(await screen.findByText(/DII Derivative Positioning — 2026-07-25/)).toBeInTheDocument();
    const cashHeading = screen.getByText(/Capital Market Segment/);
    expect(cashHeading.querySelector("span")?.textContent).toBe("Live");
    // The live row's trade date renders in the cash table.
    expect(screen.getByText("2026-07-25")).toBeInTheDocument();
    expect(screen.getByText("DII Index Futures")).toBeInTheDocument();
    expect(screen.getByText("DII Stock Futures")).toBeInTheDocument();
  });

  it("keeps the Sample chip over real-looking rows when the backend flags its own sample", async () => {
    mockUseConnected.mockReturnValue(true);
    mockUseHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });
    mockGetFiiDii.mockResolvedValue({
      is_sample_data: true,
      latest: snapshot(),
      trend: null,
    });

    render(<FlowsTab />, { wrapper });

    expect(await screen.findByText("2026-07-25")).toBeInTheDocument();
    const cashHeading = screen.getByText(/Capital Market Segment/);
    expect(cashHeading.querySelector("span")?.textContent).toBe("Sample");
  });
});
