/**
 * InvestContext — sample holdings must be the count source for the
 * Investor Dashboard header (FT-DEMO-001 / FT-TRADE-010).
 *
 * Practice and Explore with no broker expose `getDemoHoldings` so the
 * header badge matches the listed sample rows. A connected broker with
 * an empty book stays at 0 — never a sample table under a zero badge.
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

const brokerConnected = vi.hoisted(() => ({ current: false }));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => brokerConnected.current,
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
  brokerConnected.current = false;
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
    brokerConnected.current = true;

    renderProbe();

    expect(screen.getByTestId("holding-count")).toHaveTextContent("0 holdings");
    expect(screen.getByTestId("summary-count")).toHaveTextContent("0");
    expect(screen.getByTestId("sample-flag")).toHaveTextContent("false");
  });

  it("exposes the demo holdings book in practice mode when no broker is connected", () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = false;
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

  it("keeps an empty connected practice book at 0 with no sample flag", () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = true;

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
    expect(resolveInvestHoldings("practice", [], true)).toEqual({
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

  it("substitutes getDemoHoldings in practice when no broker is connected and the live book is empty", async () => {
    const { resolveInvestHoldings } = await import("../InvestContext");
    const demo = getDemoHoldings();

    const resolved = resolveInvestHoldings("practice", [], false);

    expect(resolved.isSampleData).toBe(true);
    expect(resolved.holdings).toHaveLength(demo.length);
    expect(resolved.holdings.map((h) => h.symbol)).toEqual(demo.map((h) => h.symbol));
  });
});
