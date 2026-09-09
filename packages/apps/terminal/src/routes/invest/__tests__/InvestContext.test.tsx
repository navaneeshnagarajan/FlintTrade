/**
 * InvestContext — explore-mode sample holdings must be the count source
 * for the Investor Dashboard header (FT-DEMO-001).
 *
 * The Holdings tab already lists sample stocks when the live book is empty.
 * The route header previously read the raw (empty) broker query and showed
 * “0 holdings”. Explore must use the same demo book as the rest of the app
 * (`getDemoHoldings`), not a hardcoded 10.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { getDemoHoldings } from "@/hooks/useModeData";
import { useModeStore } from "@/stores/modeStore";
import type { Holding } from "@/types/api";

vi.mock("@/hooks/useHoldings", () => ({
  useHoldings: () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: () => ({ data: undefined, isLoading: false }),
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => false,
}));

import { InvestProvider, useInvest } from "../InvestContext";

function HoldingsCountProbe() {
  const { holdings, summary, isSampleData } = useInvest();
  return (
    <div>
      <span data-testid="holding-count">{holdings.length} holdings</span>
      <span data-testid="summary-count">{summary.holdingCount}</span>
      <span data-testid="sample-flag">{String(isSampleData)}</span>
    </div>
  );
}

function renderProbe() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <InvestProvider>
        <HoldingsCountProbe />
      </InvestProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  useModeStore.setState({ mode: "explore" });
});

describe("InvestContext sample holdings count (FT-DEMO-001)", () => {
  it("exposes the demo holdings book in explore mode, not an empty live book", () => {
    useModeStore.setState({ mode: "explore" });
    const expected = getDemoHoldings();

    renderProbe();

    expect(screen.getByTestId("holding-count")).toHaveTextContent(
      `${expected.length} holdings`,
    );
    expect(screen.getByTestId("summary-count")).toHaveTextContent(
      String(expected.length),
    );
    expect(screen.getByTestId("sample-flag")).toHaveTextContent("true");
    expect(expected.length).toBeGreaterThan(0);
  });

  it("keeps an empty live book empty so a funded account with no holdings stays at 0", () => {
    useModeStore.setState({ mode: "live" });

    renderProbe();

    expect(screen.getByTestId("holding-count")).toHaveTextContent("0 holdings");
    expect(screen.getByTestId("summary-count")).toHaveTextContent("0");
    expect(screen.getByTestId("sample-flag")).toHaveTextContent("false");
  });
});

describe("resolveInvestHoldings", () => {
  it("returns the live book unchanged outside explore mode", async () => {
    const { resolveInvestHoldings } = await import("../InvestContext");
    const live: Holding[] = [
      {
        symbol: "RELIANCE",
        exchange: "NSE",
        quantity: 1,
        averagePrice: 100,
        ltp: 110,
        pnl: 10,
        pnlPercent: 10,
      },
    ];

    expect(resolveInvestHoldings("practice", live)).toEqual({
      holdings: live,
      isSampleData: false,
    });
    expect(resolveInvestHoldings("live", [])).toEqual({
      holdings: [],
      isSampleData: false,
    });
  });

  it("substitutes getDemoHoldings in explore even when the live query is empty", async () => {
    const { resolveInvestHoldings } = await import("../InvestContext");
    const demo = getDemoHoldings();

    const resolved = resolveInvestHoldings("explore", []);

    expect(resolved.isSampleData).toBe(true);
    expect(resolved.holdings).toHaveLength(demo.length);
    expect(resolved.holdings.map((h) => h.symbol)).toEqual(demo.map((h) => h.symbol));
  });
});
