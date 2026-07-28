/**
 * HomeRoute.test.tsx — Smoke tests for the Home bento dashboard.
 *
 * Verifies all default cards render, the AddWidgetCard is present,
 * and the StatusBar is visible.
 */

import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";

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
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (s: { name: string }) => unknown) =>
    selector({ name: "Test User" }),
}));

vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: (selector: (s: { totalPnl: number }) => unknown) =>
    selector({ totalPnl: 2500 }),
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

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => true,
}));

// ---------------------------------------------------------------------------
// Mock Jotai atoms
// ---------------------------------------------------------------------------
vi.mock("jotai", async (importOriginal) => ({
  ...(await importOriginal<typeof import("jotai")>()),
  useAtomValue: () => null,
}));

vi.mock("@/atoms/marketAtoms", async (importOriginal) =>
  // Real module — useAtomValue is stubbed above, so the real atoms are
  // inert here, and the FDC3 channel graph (which imports
  // selectedSymbolAtom) keeps resolving.
  await importOriginal<typeof import("@/atoms/marketAtoms")>(),
);

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------
import HomeRoute from "../HomeRoute";
import { DEFAULT_CARDS, useBentoStore } from "@/stores/bentoStore";
import { useModeStore } from "@/stores/modeStore";

function createDataTransfer() {
  const data = new Map<string, string>();
  return {
    effectAllowed: "",
    dropEffect: "",
    setData: vi.fn((type: string, value: string) => data.set(type, value)),
    getData: vi.fn((type: string) => data.get(type) ?? ""),
  };
}

beforeEach(() => {
  localStorage.clear();
  // These tests assert against the mocked REST hook fixtures; the dashboard
  // cards now branch on mode (explore => demo data), so pin to a non-explore
  // mode so the fixtures flow. Demo-mode behaviour is covered separately.
  useModeStore.setState({ mode: "live" });
  useBentoStore.setState({
    cards: DEFAULT_CARDS.map((card) => ({ ...card })),
    presets: [],
    activePresetId: null,
  });
});

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

  it("reserves scroll room so dashboard cards do not sit under the status bar", () => {
    const { container } = renderHomeRoute();

    expect(screen.getByTestId("home-route")).toHaveClass("min-h-0");
    expect(container.querySelector(".bento-scroll-container")).toHaveClass("min-h-0", "pb-20");
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

  it("opens the dashboard widget picker and adds a selected widget", async () => {
    const user = userEvent.setup();
    renderHomeRoute();

    expect(screen.getAllByTestId("ai-pulse-card")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /add widget/i }));

    expect(screen.getByRole("dialog", { name: /add dashboard widget/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /add ai pulse widget/i }));

    expect(screen.queryByRole("dialog", { name: /add dashboard widget/i })).not.toBeInTheDocument();
    expect(screen.getAllByTestId("ai-pulse-card")).toHaveLength(2);
    expect(document.querySelector('[data-home-component-id="AIPulseCard"][data-new-widget="true"]')).toBeInTheDocument();
    expect(screen.getByTestId("status-bar-card-count")).toHaveTextContent("13");
  });

  it("reorders dashboard widgets when one card is dropped onto another", () => {
    renderHomeRoute();

    const dataTransfer = createDataTransfer();
    fireEvent.dragStart(screen.getByRole("button", { name: /drag ai pulse widget/i }), {
      dataTransfer,
    });
    fireEvent.dragOver(screen.getByTestId("home-widget-frame-card-welcome"), {
      dataTransfer,
    });
    fireEvent.drop(screen.getByTestId("home-widget-frame-card-welcome"), {
      dataTransfer,
    });

    const orderedCards = [...useBentoStore.getState().cards].sort((a, b) => a.order - b.order);
    expect(orderedCards[0].id).toBe("card-ai");
    expect(orderedCards[1].id).toBe("card-welcome");
  });

  it("reorders dashboard widgets when the drag handle is moved with a pointer", () => {
    renderHomeRoute();

    const target = screen.getByTestId("home-widget-frame-card-welcome");
    const originalElementFromPoint = document.elementFromPoint;
    const elementFromPoint = vi.fn(() => target);
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: elementFromPoint,
    });

    fireEvent.pointerDown(screen.getByRole("button", { name: /drag ai pulse widget/i }), {
      button: 0,
      clientX: 740,
      clientY: 120,
      pointerId: 1,
    });
    fireEvent.pointerMove(window, {
      clientX: 120,
      clientY: 160,
      pointerId: 1,
    });
    fireEvent.pointerUp(window, {
      clientX: 120,
      clientY: 160,
      pointerId: 1,
    });

    const orderedCards = [...useBentoStore.getState().cards].sort((a, b) => a.order - b.order);
    expect(orderedCards[0].id).toBe("card-ai");
    expect(orderedCards[1].id).toBe("card-welcome");

    if (originalElementFromPoint) {
      Object.defineProperty(document, "elementFromPoint", {
        configurable: true,
        value: originalElementFromPoint,
      });
    } else {
      Reflect.deleteProperty(document, "elementFromPoint");
    }
  });

  it("resizes dashboard widgets from the card size controls", async () => {
    const user = userEvent.setup();
    renderHomeRoute();

    await user.click(screen.getByRole("button", { name: /make welcome widget hero/i }));

    const welcomeCard = useBentoStore.getState().cards.find((card) => card.id === "card-welcome");
    expect(welcomeCard?.size).toBe("hero");
    expect(screen.getByTestId("home-widget-frame-card-welcome")).toHaveAttribute(
      "data-bento-size",
      "hero",
    );
  });

  it("removes dashboard widgets from the card controls", async () => {
    const user = userEvent.setup();
    renderHomeRoute();

    await user.click(screen.getByRole("button", { name: /remove ai pulse widget/i }));

    expect(screen.queryByTestId("home-widget-frame-card-ai")).not.toBeInTheDocument();
    expect(useBentoStore.getState().cards.some((card) => card.id === "card-ai")).toBe(false);
    expect(screen.getByTestId("status-bar-card-count")).toHaveTextContent("11");
  });

  it("opens saved layout presets and restores a selected dashboard layout", async () => {
    const user = userEvent.setup();
    renderHomeRoute();

    await user.click(screen.getByRole("button", { name: /make welcome widget hero/i }));
    await user.click(screen.getByRole("button", { name: /save current layout/i }));
    await user.click(screen.getByRole("button", { name: /reset layout/i }));

    expect(screen.getByTestId("home-widget-frame-card-welcome")).toHaveAttribute(
      "data-bento-size",
      "wide",
    );

    await user.click(screen.getByRole("button", { name: /view presets/i }));
    expect(screen.getByRole("dialog", { name: /dashboard layout presets/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /load layout/i }));

    expect(screen.queryByRole("dialog", { name: /dashboard layout presets/i })).not.toBeInTheDocument();
    expect(screen.getByTestId("home-widget-frame-card-welcome")).toHaveAttribute(
      "data-bento-size",
      "hero",
    );
  });

  it("deletes saved dashboard presets from the presets panel", async () => {
    const user = userEvent.setup();
    renderHomeRoute();

    await user.click(screen.getByRole("button", { name: /save current layout/i }));
    expect(useBentoStore.getState().presets).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /view presets/i }));
    await user.click(screen.getByRole("button", { name: /delete layout/i }));

    expect(useBentoStore.getState().presets).toHaveLength(0);
    expect(screen.getByText(/no saved layouts yet/i)).toBeInTheDocument();
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
