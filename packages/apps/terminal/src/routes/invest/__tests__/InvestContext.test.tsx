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
import { accountCharges, accountLedgerCash, accountNetWorth } from "@/lib/accountNetWorth";
import { useModeStore } from "@/stores/modeStore";
import type { Holding } from "@/types/api";

const holdingsQuery = vi.hoisted(() => ({
  data: undefined as Holding[] | undefined,
  isLoading: false,
  isError: false,
  refetch: vi.fn(),
}));

const fundsQuery = vi.hoisted(() => ({
  data: undefined as {
    availableCash: number;
    usedMargin: number;
    totalBalance: number;
    ledgerBalance?: number;
    futuresMtmInLedger?: boolean;
  } | undefined,
  isLoading: false,
}));

const positionsQuery = vi.hoisted(() => ({
  data: undefined as {
    symbol: string;
    exchange: string;
    product: string;
    quantity: number;
    averagePrice: number;
    ltp: number;
    pnl: number;
    pnlPercent: number;
  }[] | undefined,
  isLoading: false,
  isError: false,
  isSuccess: false,
}));

const accountReadsEnabled = vi.hoisted(() => ({ current: false }));

vi.mock("@/hooks/useHoldings", () => ({
  useHoldings: () => holdingsQuery,
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: () => fundsQuery,
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => positionsQuery,
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => accountReadsEnabled.current,
}));

const brokerConnected = vi.hoisted(() => ({ current: false }));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => brokerConnected.current,
}));

import { InvestProvider, useInvest } from "../InvestContext";

function HoldingsCountProbe() {
  const { holdings, summary, isSampleData, isLoading, isError, positionBookReady } = useInvest();
  const netWorthPublished = positionBookReady && !isLoading && !isError;
  return (
    <div>
      <span data-testid="holding-count">{holdings.length} holdings</span>
      <span data-testid="summary-count">{summary.holdingCount}</span>
      <span data-testid="sample-flag">{String(isSampleData)}</span>
      <span data-testid="loading-flag">{String(isLoading)}</span>
      <span data-testid="error-flag">{String(isError)}</span>
      <span data-testid="position-book-ready">{String(positionBookReady)}</span>
      <span data-testid="net-worth">{netWorthPublished ? summary.netWorth : ""}</span>
    </div>
  );
}

function renderProbe() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const view = render(
    <QueryClientProvider client={qc}>
      <InvestProvider>
        <HoldingsCountProbe />
      </InvestProvider>
    </QueryClientProvider>,
  );
  return { ...view, qc };
}

afterEach(() => {
  brokerConnected.current = false;
  accountReadsEnabled.current = false;
  holdingsQuery.data = undefined;
  holdingsQuery.isLoading = false;
  holdingsQuery.isError = false;
  fundsQuery.data = undefined;
  fundsQuery.isLoading = false;
  positionsQuery.data = undefined;
  positionsQuery.isLoading = false;
  positionsQuery.isError = false;
  positionsQuery.isSuccess = false;
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

  it("keeps the practice cash balance when holdings are empty instead of the sample book", () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = false;
    fundsQuery.data = { availableCash: 999_200, usedMargin: 800, totalBalance: 1_000_000 };

    renderProbe();

    expect(screen.getByTestId("holding-count")).toHaveTextContent("0 holdings");
    expect(screen.getByTestId("sample-flag")).toHaveTextContent("false");
    expect(screen.getByTestId("net-worth")).toHaveTextContent("1000000");
    expect(getDemoHoldings().length).toBeGreaterThan(0);
  });

  it("is cash + holdings + positions − the practice charges source", () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = false;
    const funds = {
      availableCash: 999_200,
      usedMargin: 800,
      totalBalance: 1_000_000,
      ledgerBalance: 999_200,
      futuresMtmInLedger: false,
    };
    const positions = [{
      symbol: "SBIN",
      exchange: "NSE",
      product: "MIS",
      quantity: 1,
      averagePrice: 800,
      ltp: 800,
      pnl: 0,
      pnlPercent: 0,
    }];
    fundsQuery.data = funds;
    positionsQuery.data = positions;
    const charges = accountCharges(funds);
    const cash = accountLedgerCash(funds);
    const expected = accountNetWorth([], cash, positions, charges, funds.futuresMtmInLedger);

    renderProbe();

    expect(expected).toBe(1_000_000);
    expect(expected).not.toBe(funds.availableCash - charges);
    expect(screen.getByTestId("holding-count")).toHaveTextContent("0 holdings");
    expect(screen.getByTestId("position-book-ready")).toHaveTextContent("true");
    expect(screen.getByTestId("net-worth")).toHaveTextContent(String(expected));
  });

  it("does not publish net worth until the position book loads, even when funds and holdings are ready", () => {
    useModeStore.setState({ mode: "practice" });
    accountReadsEnabled.current = true;
    brokerConnected.current = false;
    fundsQuery.data = {
      availableCash: 999_200,
      usedMargin: 800,
      totalBalance: 1_000_000,
      ledgerBalance: 1_000_000 + 235 * 65,
      futuresMtmInLedger: false,
    };
    fundsQuery.isLoading = false;
    holdingsQuery.data = [];
    holdingsQuery.isLoading = false;
    holdingsQuery.isError = false;
    positionsQuery.isLoading = true;
    positionsQuery.isSuccess = false;
    positionsQuery.isError = false;
    positionsQuery.data = undefined;

    const view = renderProbe();

    expect(screen.getByTestId("loading-flag")).toHaveTextContent("false");
    expect(screen.getByTestId("position-book-ready")).toHaveTextContent("false");
    expect(screen.getByTestId("error-flag")).toHaveTextContent("false");
    expect(screen.getByTestId("net-worth").textContent).toBe("");

    positionsQuery.isLoading = false;
    positionsQuery.isSuccess = true;
    positionsQuery.data = [{
      symbol: "NIFTY24SEP23500CE",
      exchange: "NFO",
      product: "NRML",
      quantity: -65,
      averagePrice: 235,
      ltp: 205,
      pnl: 0,
      pnlPercent: 0,
    }];
    view.rerender(
      <QueryClientProvider client={view.qc}>
        <InvestProvider>
          <HoldingsCountProbe />
        </InvestProvider>
      </QueryClientProvider>,
    );

    const expected = 1_000_000 + (235 - 205) * 65;
    expect(screen.getByTestId("position-book-ready")).toHaveTextContent("true");
    expect(screen.getByTestId("net-worth")).toHaveTextContent(String(expected));
    expect(screen.getByTestId("net-worth").textContent).not.toContain(String(1_000_000 + 205 * 65));
  });

  it("does not publish net worth when the position book fails after funds and holdings are ready", () => {
    useModeStore.setState({ mode: "practice" });
    accountReadsEnabled.current = true;
    fundsQuery.data = { availableCash: 999_200, usedMargin: 800, totalBalance: 1_000_000 };
    fundsQuery.isLoading = false;
    holdingsQuery.data = [];
    holdingsQuery.isLoading = false;
    holdingsQuery.isError = false;
    positionsQuery.isLoading = false;
    positionsQuery.isSuccess = false;
    positionsQuery.isError = true;
    positionsQuery.data = undefined;

    renderProbe();

    expect(screen.getByTestId("loading-flag")).toHaveTextContent("false");
    expect(screen.getByTestId("error-flag")).toHaveTextContent("true");
    expect(screen.getByTestId("position-book-ready")).toHaveTextContent("false");
    expect(screen.getByTestId("net-worth").textContent).toBe("");
  });

  it("does not flash the sample book while practice funds are still loading", () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = false;
    fundsQuery.isLoading = true;
    fundsQuery.data = undefined;

    renderProbe();

    expect(screen.getByTestId("holding-count")).toHaveTextContent("0 holdings");
    expect(screen.getByTestId("sample-flag")).toHaveTextContent("false");
    expect(screen.getByTestId("loading-flag")).toHaveTextContent("true");
  });

  it("keeps an empty connected practice book at 0 with no sample flag", () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = true;

    renderProbe();

    expect(screen.getByTestId("holding-count")).toHaveTextContent("0 holdings");
    expect(screen.getByTestId("summary-count")).toHaveTextContent("0");
    expect(screen.getByTestId("sample-flag")).toHaveTextContent("false");
  });

  it("does not classify Practice as sample while the holdings query is still pending", () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = false;
    holdingsQuery.isLoading = true;
    holdingsQuery.data = undefined;

    renderProbe();

    expect(screen.getByTestId("holding-count")).toHaveTextContent("0 holdings");
    expect(screen.getByTestId("summary-count")).toHaveTextContent("0");
    expect(screen.getByTestId("sample-flag")).toHaveTextContent("false");
    expect(screen.getByTestId("loading-flag")).toHaveTextContent("true");
  });

  it("does not classify Practice as sample when the holdings query errored empty", () => {
    useModeStore.setState({ mode: "practice" });
    brokerConnected.current = false;
    holdingsQuery.isError = true;
    holdingsQuery.data = undefined;

    renderProbe();

    expect(screen.getByTestId("holding-count")).toHaveTextContent("0 holdings");
    expect(screen.getByTestId("summary-count")).toHaveTextContent("0");
    expect(screen.getByTestId("sample-flag")).toHaveTextContent("false");
    expect(screen.getByTestId("loading-flag")).toHaveTextContent("false");
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

  it("does not substitute sample when practice already has an account snapshot", async () => {
    const { resolveInvestHoldings } = await import("../InvestContext");

    expect(resolveInvestHoldings("practice", [], false, true, true)).toEqual({
      holdings: [],
      isSampleData: false,
    });
  });

  it("does not substitute sample in practice until the holdings query has settled empty", async () => {
    const { resolveInvestHoldings } = await import("../InvestContext");

    expect(resolveInvestHoldings("practice", [], false, false)).toEqual({
      holdings: [],
      isSampleData: false,
    });
  });
});
