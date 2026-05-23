/**
 * HomeRoute.test.tsx — Smoke tests for the Home bento dashboard.
 *
 * Verifies all default cards render, the AddWidgetCard is present,
 * and the StatusBar is visible.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mock framer-motion
// ---------------------------------------------------------------------------
vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      style,
      className,
      "data-testid": testId,
      "data-bento-size": size,
      "aria-label": label,
      whileHover: _wh,
      whileTap: _wt,
      initial: _i,
      animate: _a,
      transition: _t,
      ...rest
    }: Record<string, unknown>) => (
      <div
        style={style as React.CSSProperties}
        className={className as string}
        data-testid={testId as string}
        data-bento-size={size as string}
        aria-label={label as string}
        {...rest}
      >
        {children as React.ReactNode}
      </div>
    ),
    button: ({
      children,
      onClick,
      "data-testid": testId,
      "aria-label": label,
      whileHover: _wh,
      whileTap: _wt,
      initial: _i,
      animate: _a,
      transition: _t,
      ...rest
    }: Record<string, unknown>) => (
      <button
        type="button"
        onClick={onClick as React.MouseEventHandler}
        data-testid={testId as string}
        aria-label={label as string}
        {...rest}
      >
        {children as React.ReactNode}
      </button>
    ),
  },
}));

// ---------------------------------------------------------------------------
// Mock stores
// ---------------------------------------------------------------------------
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: { setWidgetPickerOpen: () => void }) => unknown) =>
    selector({ setWidgetPickerOpen: vi.fn() }),
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (s: { name: string }) => unknown) =>
    selector({ name: "Test User" }),
}));

vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: (selector: (s: { totalPnl: number }) => unknown) =>
    selector({ totalPnl: 2500 }),
}));

const mockBentoState = {
  cards: [],
  presets: [],
  activePresetId: null,
  savePreset: vi.fn(),
  resetToDefault: vi.fn(),
};
vi.mock("@/stores/bentoStore", () => ({
  useBentoStore: (selector: (s: typeof mockBentoState) => unknown) => selector(mockBentoState),
}));

// ---------------------------------------------------------------------------
// Mock hooks
// ---------------------------------------------------------------------------
vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => ({
    data: [
      { symbol: "NIFTY24DECFUT", exchange: "NSE", quantity: 50, averagePrice: 22000, ltp: 22500, pnl: 2500, pnlPercent: 1.14, product: "NRML" },
    ],
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: () => ({
    data: { availableCash: 100000, usedMargin: 50000, totalBalance: 150000 },
  }),
}));

vi.mock("@/hooks/useHoldings", () => ({
  useHoldings: () => ({
    data: [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 10, averagePrice: 2900, ltp: 3000, pnl: 1000, pnlPercent: 3.45 },
    ],
  }),
}));

vi.mock("@/hooks/useOrders", () => ({
  useOrders: () => ({
    data: [
      {
        orderId: "ORD-001",
        symbol: "NIFTY",
        exchange: "NSE",
        action: "BUY",
        quantity: 50,
        price: 22000,
        orderType: "LIMIT",
        status: "COMPLETE",
        product: "NRML",
        strategy: "manual",
        timestamp: "2026-04-13T09:30:00Z",
      },
    ],
    isLoading: false,
  }),
}));

// ---------------------------------------------------------------------------
// Mock Jotai atoms
// ---------------------------------------------------------------------------
vi.mock("jotai", () => ({
  useAtomValue: () => null,
  atom: vi.fn(() => ({ read: vi.fn() })),
}));

vi.mock("@/atoms/marketAtoms", () => ({
  niftyAtom: {},
  bankniftyAtom: {},
  sensexAtom: {},
  vixAtom: {},
  goldAtom: {},
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------
import HomeRoute from "../HomeRoute";

function renderHomeRoute() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <HomeRoute />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("HomeRoute", () => {
  it("renders the home route container", () => {
    renderHomeRoute();
    expect(screen.getByTestId("home-route")).toBeInTheDocument();
  });

  it("renders the bento grid", () => {
    renderHomeRoute();
    expect(screen.getByTestId("home-bento-grid")).toBeInTheDocument();
  });

  it("renders WelcomeCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("welcome-card")).toBeInTheDocument();
  });

  it("renders AIPulseCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("ai-pulse-card")).toBeInTheDocument();
  });

  it("renders PositionsCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("positions-card")).toBeInTheDocument();
  });

  it("renders MiniChartCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("mini-chart-card")).toBeInTheDocument();
  });

  it("renders PortfolioCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("portfolio-card")).toBeInTheDocument();
  });

  it("renders WatchlistCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("watchlist-card")).toBeInTheDocument();
  });

  it("renders NewsCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("news-card")).toBeInTheDocument();
  });

  it("renders BreadthCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("breadth-card")).toBeInTheDocument();
  });

  it("renders SectorCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("sector-card")).toBeInTheDocument();
  });

  it("renders SIPCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("sip-card")).toBeInTheDocument();
  });

  it("renders GlobalCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("global-card")).toBeInTheDocument();
  });

  it("renders OrdersCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("orders-card")).toBeInTheDocument();
  });

  it("renders AddWidgetCard", () => {
    renderHomeRoute();
    expect(screen.getByTestId("add-widget-card")).toBeInTheDocument();
  });

  it("renders StatusBar", () => {
    renderHomeRoute();
    expect(screen.getByTestId("status-bar")).toBeInTheDocument();
  });

  it("WelcomeCard shows greeting with user name", () => {
    renderHomeRoute();
    expect(screen.getByText(/good/i)).toBeInTheDocument();
  });

  it("WelcomeCard shows positive P&L in green", () => {
    renderHomeRoute();
    // totalPnl = 2500 → should render +₹2,500 in welcome card
    const welcomeCard = screen.getByTestId("welcome-card");
    expect(welcomeCard.textContent).toMatch(/₹2,500/);
  });
});
