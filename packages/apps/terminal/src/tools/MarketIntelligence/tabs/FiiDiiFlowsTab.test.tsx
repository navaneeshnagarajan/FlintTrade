import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.screener", () => ({
  getFiiDiiData: vi.fn(),
}));
import { getFiiDiiData } from "@/services/ftApi.screener";
import { FiiDiiFlowsTab } from "./FiiDiiFlowsTab";

const mockGet = getFiiDiiData as unknown as ReturnType<typeof vi.fn>;

function snapshot(overrides: Record<string, unknown> = {}) {
  return {
    trade_date: "2026-06-05",
    fii_buy: 12000,
    fii_sell: 9000,
    fii_net: 3000,
    dii_buy: 8000,
    dii_sell: 6000,
    dii_net: 2000,
    fii_idx_fut_long: 50000,
    fii_idx_fut_short: 30000,
    fii_idx_fut_net: 20000,
    fii_stk_fut_long: 0,
    fii_stk_fut_short: 0,
    fii_stk_fut_net: 0,
    fii_idx_call_long: 0,
    fii_idx_call_short: 0,
    fii_idx_call_net: 0,
    fii_idx_put_long: 0,
    fii_idx_put_short: 0,
    fii_idx_put_net: 0,
    dii_idx_fut_long: 0,
    dii_idx_fut_short: 0,
    dii_idx_fut_net: 0,
    dii_stk_fut_long: 0,
    dii_stk_fut_short: 0,
    dii_stk_fut_net: 0,
    pcr: 0.9,
    sentiment_score: 60,
    updated_at: "",
    ...overrides,
  };
}

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FiiDiiFlowsTab />
    </QueryClientProvider>,
  );
}

describe("FiiDiiFlowsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders real FII/DII history and hides the demo notice when live", async () => {
    mockGet.mockResolvedValue({
      is_sample_data: false,
      latest: snapshot(),
      trend: {
        days: 1,
        snapshots: [snapshot()],
        fii_net_total: 3000,
        dii_net_total: 2000,
        avg_sentiment: 60,
      },
    });

    renderTab();

    // Real cash-segment row keyed on the backend trade date.
    expect(await screen.findByText("2026-06-05")).toBeInTheDocument();
    // Real derivative-positioning row from the snapshot's OI fields.
    expect(screen.getByText("FII Index Futures")).toBeInTheDocument();
    // No demo affordance when the backend reports live data.
    expect(screen.queryByText(/representative data structure/i)).not.toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith(10);
  });

  it("shows the demo-data notice when the backend returns sample data", async () => {
    mockGet.mockResolvedValue({ is_sample_data: true, latest: snapshot(), trend: null });

    renderTab();

    expect(await screen.findByText(/representative data structure/i)).toBeInTheDocument();
  });
});
