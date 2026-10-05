/**
 * PositionsWidget.test.tsx
 *
 * Tests for the merged Positions widget — the position book's THREE views.
 * Covers the gated write path (per-row Convert, per-row square-off, the typed
 * exit-all flow, exact displayed-account authority and the fail-closed product
 * check), and the two absorbed views: netting/grouping/totals
 * (from the retired Net Position widget) and the treemap/grouping/chart-open
 * contract (from the retired Position Heat Map widget).
 *
 * The pure kernel (`positionBook.ts`) is exercised directly at the bottom —
 * exposure, mark-to-market and netting have ONE definition each now, so those
 * assertions are the reconciliation's pins.
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { act, render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// Force DEV mode so ftApi.helpers' getBase() returns "/ft-api" — the convert
// and exit-all actions go through the real helpers with a stubbed fetch.
vi.stubEnv("DEV", true);

// Radix Select (the broker-target picker, the heat-map group picker) and the
// heat map's container measurement both need ResizeObserver.
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUsePositions = vi.fn();
const mockUseBrokerConnected = vi.fn();
const mockConnectionState = vi.hoisted(() => ({
  apiKey: "",
  //  models a normally-loaded app; the hydration
  // fail-closed window is covered by brokerTargets/api tests.
}));
const mockModeState = vi.hoisted(() => ({
  mode: "live",
}));
const mockBrokerState = vi.hoisted(() => ({
  accounts: [] as Array<{
    broker: string;
    account_id: string;
    label: string;
    source?: string;
    status?: string;
    is_primary?: boolean;
    read_only?: boolean;
  }>,
  activeAccountId: null as string | null,
}));
const mockReadState = vi.hoisted(() => ({
  identity: null as null | {
    mode: string;
    scopeKey: string;
    brokerType: string;
    accountId: string;
  },
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

const mockUseOrders = vi.fn();
vi.mock("@/hooks/useOrders", () => ({
  useOrders: (...args: unknown[]) => mockUseOrders(...args),
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: () => ({ data: undefined }),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockUseBrokerConnected(),
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => mockUseBrokerConnected(),
  useAccountReadContext: () => {
    const mode = mockModeState.mode;
    const account = mockBrokerState.accounts.find((candidate) =>
      mockBrokerAccountMatch(candidate, mockBrokerState.activeAccountId),
    ) ?? mockBrokerState.accounts[0];
    const identity = mockReadState.identity ?? (mode === "explore"
      ? {
          mode,
          scopeKey: "explore:mock:default",
          brokerType: "mock",
          accountId: "default",
        }
      : mode === "practice"
        ? {
            mode,
            scopeKey: "practice:sandbox:default",
            brokerType: "sandbox",
            accountId: "default",
          }
        : account
          ? {
              mode,
              scopeKey: ["live", "native", account.broker, account.account_id]
                .map(encodeURIComponent)
                .join(":"),
              brokerType: account.broker,
              accountId: account.account_id,
            }
          : {
              mode,
              scopeKey: "live:native:upstox:U1",
              brokerType: "dhan",
              accountId: "default",
            });
    return {
      identity,
      enabled: mockUseBrokerConnected(),
      host: "",
      apiKey: "",
    };
  },
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// Deterministic colour string so the heat-map assertions do not depend on
// exact RGB maths.
vi.mock("@/lib/colourScale", () => ({
  divergingColourScaleRange: () => "rgb(80,160,100)",
  divergingColourScale: () => "rgb(80,160,100)",
}));

// Mock tradingStore to avoid side-effects in usePositions
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: Object.assign(() => ({}), {
    getState: () => ({ updateFromPositions: vi.fn() }),
  }),
}));

// ftApi.helpers reads these stores for auth headers on every call.
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: Object.assign(
    (selector?: (s: { apiKey: string }) => unknown) =>
      typeof selector === "function" ? selector(mockConnectionState) : mockConnectionState,
    { getState: () => mockConnectionState },
  ),
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "" }) },
}));
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector?: (s: { mode: string }) => unknown) =>
    typeof selector === "function" ? selector(mockModeState) : mockModeState,
}));


// Square-off goes through the existing gated placeOrder path (services/api →
// /ft-api/api/v1/orders/place → SafetySystem → gate_order → BrokerRouter).
const mockPlaceOrder = vi.fn();
vi.mock("@/services/api", () => {
  class OrderApiError extends Error {
    readonly status: number;
    readonly body: unknown;
    constructor(message: string, status: number, body: unknown) {
      super(message);
      this.name = "OrderApiError";
      this.status = status;
      this.body = body;
    }
  }
  return {
    placeOrder: (...args: unknown[]) => mockPlaceOrder(...args),
    OrderApiError,
  };
});

const mockEmitNotification = vi.fn();
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: (...args: unknown[]) => mockEmitNotification(...args),
}));

vi.mock("@/stores/brokerStore", () => ({
  brokerAccountKey: (account: { account_id: string; broker: string; source?: string }) => [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":"),
  findBrokerAccountMatch: (
    accounts: Array<{ account_id: string; broker: string; source?: string }>,
    selector: string | null,
  ) => accounts.find((account) => mockBrokerAccountMatch(account, selector)),
  isBrokerAccountMatch: (
    account: { account_id: string; broker: string; source?: string },
    selector: string | null,
  ) => mockBrokerAccountMatch(account, selector),
  useBrokerStore: Object.assign(
    (selector?: (s: typeof mockBrokerState) => unknown) =>
      typeof selector === "function" ? selector(mockBrokerState) : mockBrokerState,
    { getState: () => mockBrokerState },
  ),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import PositionsWidget from "../PositionsWidget";
import { OrderApiError } from "@/services/api";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import {
  netPositions,
  normalisePositions,
  offsetLegTooltip,
  positionExposure,
  underlyingOf,
} from "../positionBook";
import { SAMPLE_POSITION_BOOK } from "../sampleBook";
import { totalPositionMtm } from "@/lib/pnl";

function mockBrokerAccountMatch(
  account: { account_id: string; broker: string; source?: string },
  selector: string | null,
) {
  if (!selector) return false;
  const key = [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":");
  return key === selector || account.account_id === selector;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeWidgetPanelProps();

/** Panel props that open the widget on one of the two absorbed views. */
function viewProps(view: "table" | "net" | "heat", extra: Record<string, unknown> = {}) {
  return makeWidgetPanelProps<Record<string, unknown>>({ params: { view, ...extra } });
}

function queryResult(overrides = {}) {
  return {
    data: undefined,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
    ...overrides,
  };
}

/** Heat tiles are the only buttons whose accessible name carries a rupee P&L. */
function heatTiles() {
  return screen.getAllByRole("button", { name: /: [+\-]₹/ });
}

/**
 * JSDOM reports 0×0 for every rect, which culls every treemap cell.
 *
 * `heatOnly` sizes the heat canvas and leaves the widget root wide, so a
 * "+N more" click still lands on the table rather than the narrow cards.
 */
function withMeasuredContainer(
  run: () => void,
  size: { width: number; height: number } = { width: 800, height: 400 },
  options: { heatOnly?: boolean } = {},
) {
  const original = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function (this: Element) {
    const measured = !options.heatOnly || this.getAttribute("data-testid") === "heat-map";
    const width = measured ? size.width : 900;
    const height = measured ? size.height : 700;
    return {
      width,
      height,
      top: 0,
      left: 0,
      right: width,
      bottom: height,
      x: 0,
      y: 0,
      toJSON() {},
    } as DOMRect;
  };
  try {
    run();
  } finally {
    Element.prototype.getBoundingClientRect = original;
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PositionsWidget", () => {
  afterEach(async () => {
    // Radix focus-scope schedules a setTimeout on dialog unmount; drain it
    // INSIDE this test's jsdom realm. Left pending, it fires during the
    // next test file's realm swap and crashes the run with "parameter 1 is
    // not of type 'Event'" — the cross-file flake that intermittently
    // failed the whole trading bucket.
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  beforeEach(() => {
    vi.restoreAllMocks();
    mockPlaceOrder.mockReset();
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockUseBrokerConnected.mockReturnValue(true);
    mockBrokerState.accounts = [];
    mockBrokerState.activeAccountId = null;
    mockReadState.identity = null;
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    mockUseOrders.mockReturnValue({ data: [] });
    useOperatorSignalStore.setState({ decisionStatus: "ready" });
  });

  it("renders without crashing", () => {
    const { container } = render(<PositionsWidget {...defaultProps} />);
    expect(container.querySelector("[data-tour-target='positions']")).toBeInTheDocument();
  });

  it("shows 'No open positions' when data is empty", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("shows the empty state when data is undefined", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: undefined }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("shows pending status before first authoritative success (and no empty or error)", () => {
    mockUsePositions.mockReturnValue(queryResult({ isPending: true, isLoading: true, data: undefined }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByLabelText(/loading positions/i)).toBeInTheDocument();
    expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows error/unavailable on failure but never with empty when no prior data", () => {
    mockUsePositions.mockReturnValue(
      queryResult({ isError: true, error: new Error("network fail"), data: undefined }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/failed to load positions/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
  });

  it("shows empty copy only after a successful empty response", () => {
    mockUsePositions.mockReturnValue(queryResult({ isPending: false, isError: false, data: [] }));
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("No open positions")).toBeInTheDocument();
  });

  it("does not fetch or expose position actions without a broker connection", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);

    expect(mockUsePositions).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to load positions")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /exit all positions/i })).not.toBeInTheDocument();
  });

  it("does not fetch for the heat view either when the broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...viewProps("heat")} />);

    expect(mockUsePositions).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to load positions")).toBeInTheDocument();
  });

  it("displays position rows with symbol, qty, and P&L", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, average_price: 134 },
          { symbol: "BANKNIFTY24APR51000PE", pnl: -800, quantity: -30, ltp: 220, average_price: 193 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // Symbols should be visible
    expect(screen.getByText("NIFTY24APR24000CE")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY24APR51000PE")).toBeInTheDocument();

    // P&L is the shared mark-to-market, not the broker's `pnl` field:
    // (150 − 134) × 75 = +1,200 and (220 − 193) × −30 = −810 (the broker said
    // −800). A loss now carries its minus sign; the table used to print the
    // absolute value, so a ₹810 loss read as "₹810".
    expect(screen.getByText("+₹1,200")).toBeInTheDocument();
    expect(screen.getByText("-₹810")).toBeInTheDocument();
  });

  it("squares off a Practice position through place with the opposite side and quantity", async () => {
    mockModeState.mode = "practice";
    mockPlaceOrder.mockResolvedValue({ orderId: "PQ1" });
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, exchange: "NFO", product: "NRML" },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(mockUsePositions).toHaveBeenCalledWith(expect.objectContaining({ enabled: true }));
    expect(screen.queryByText("Read-only")).not.toBeInTheDocument();
    expect(screen.getByText("Practice")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Convert NIFTY24APR24000CE" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
    expect(mockPlaceOrder).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

    await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith({
      symbol: "NIFTY24APR24000CE",
      exchange: "NFO",
      action: "SELL",
      product: "NRML",
      orderType: "MARKET",
      quantity: 75,
      price: 150,
      triggerPrice: 0,
      strategy: "FlintPositions",
      rationale: "",
    }, {
      mode: "practice",
      scopeKey: "practice:sandbox:default",
      brokerType: "sandbox",
      accountId: "default",
    }, { exit: true });
  });

  it("squares off a Practice position while Laya is Down without an extra confirmation", async () => {
    useOperatorSignalStore.setState({ decisionStatus: "down" });
    mockModeState.mode = "practice";
    mockPlaceOrder.mockResolvedValue({ orderId: "PQ-DOWN" });
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, exchange: "NFO", product: "NRML" },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const squareOff = screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" });
    expect(squareOff).toBeEnabled();
    fireEvent.click(squareOff);
    expect(screen.queryByRole("button", { name: /laya/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

    await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
    expect(mockPlaceOrder).toHaveBeenCalledWith(
      expect.objectContaining({ action: "SELL", quantity: 75 }),
      expect.objectContaining({ mode: "practice" }),
      { exit: true },
    );
    await waitFor(() => expect(mockEmitNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Closed. Exits are allowed while Laya is Down.",
      }),
    ));
  });

  it("shows the header with position count", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // Header shows "Positions (1)"
    expect(screen.getByText("Positions (1)")).toBeInTheDocument();
  });

  it("displays total P&L in the header from the shared mark-to-market", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "A", pnl: 1000, quantity: 10, ltp: 100, average_price: 90 },
          { symbol: "B", pnl: -300, quantity: 20, ltp: 50, average_price: 65 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    // (100 − 90) × 10 = +100, (50 − 65) × 20 = −300 → −200. The broker's own
    // `pnl` fields would have summed to +700; totalPositionMtm is the single
    // definition, so the header, the net total and the heat cells agree.
    expect(screen.getByText("P&L: -₹200")).toBeInTheDocument();
  });

  it("falls back to the broker P&L when the row cannot be marked to market", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        // ltp 0 — an illiquid option the broker never priced. Recomputing would
        // fabricate a (0 − 134) × 75 loss.
        data: [{ symbol: "NIFTY24APR24000CE", pnl: 640, quantity: 75, ltp: 0, average_price: 134 }],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("P&L: +₹640")).toBeInTheDocument();
  });

  // ── Absorbed from the retired Dashboard widget (ruling D5) ───────────────

  it("shows the P&L% column with the kernel's derived percentage", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        // No broker pnlPercent → the kernel derives (150 − 134) / 134 × 100
        // × sign(qty) = +11.94%. The retired Dashboard recomputed this
        // per-row; the column now renders the ONE normalised figure.
        data: [{ symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, average_price: 134 }],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByRole("columnheader", { name: /P&L%/ })).toBeInTheDocument();
    expect(screen.getByText("+11.94%")).toBeInTheDocument();
  });

  it("prefers a broker-supplied P&L% over the derivation, like every other view", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "INFY", pnl: 3000, quantity: 100, ltp: 1510, average_price: 1480, pnlPercent: 5.5 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByText("+5.50%")).toBeInTheDocument();
    // The derivation would have said +2.03% — the broker figure wins.
    expect(screen.queryByText("+2.03%")).not.toBeInTheDocument();
  });

  it("signs a losing row's P&L% as a loss", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "TCS", pnl: -4000, quantity: 50, ltp: 3820, average_price: 3900 }],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const pct = screen.getByText("-2.05%");
    expect(pct).toBeInTheDocument();
    expect(pct).toHaveClass("text-loss");
  });

  it("shows stacked P&L cards instead of the clipped table at ~390px", () => {
    let resizeCallback: ResizeObserverCallback | null = null;
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserver {
        constructor(callback: ResizeObserverCallback) {
          resizeCallback = callback;
        }
        observe = vi.fn();
        disconnect = vi.fn();
        unobserve = vi.fn();
      },
    );
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "RELIANCE", pnl: 3500, quantity: 50, ltp: 2520, average_price: 2450 },
        ],
      }),
    );

    render(<PositionsWidget {...defaultProps} />);

    act(() => {
      resizeCallback?.(
        [{ contentRect: { width: 390, height: 700 } } as ResizeObserverEntry],
        {} as ResizeObserver,
      );
    });

    const cards = screen.getByRole("list", { name: "Positions" });
    expect(cards).toHaveAttribute("data-layout", "cards");
    expect(cards).toHaveTextContent("RELIANCE");
    expect(cards).toHaveTextContent("+₹3,500");
    expect(cards).toHaveTextContent("+2.86%");
    expect(screen.queryByRole("columnheader", { name: /P&L%/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("renders the position-status tracker with counts from the shared mark-to-market", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          // (100 − 90) × 10 = +100 → profit.
          { symbol: "A", pnl: 100, quantity: 10, ltp: 100, average_price: 90 },
          // (50 − 65) × 20 = −300 → loss, even though the broker's own `pnl`
          // says +1000: the tracker tones by the kernel mtm, not the raw field.
          { symbol: "B", pnl: 1000, quantity: 20, ltp: 50, average_price: 65 },
          // (2500 − 2500) × 10 = 0 → flat.
          { symbol: "C", pnl: 0, quantity: 10, ltp: 2500, average_price: 2500 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(screen.getByRole("img", { name: "Position status tracker" })).toBeInTheDocument();
    expect(screen.getByText("1 profit")).toBeInTheDocument();
    expect(screen.getByText("1 loss")).toBeInTheDocument();
    expect(screen.getByText("1 flat")).toBeInTheDocument();
  });

  it("keeps the tracker off the net and heat views and off the empty book", () => {
    mockUsePositions.mockReturnValue(queryResult({ data: [] }));
    render(<PositionsWidget {...defaultProps} />);
    expect(screen.queryByRole("img", { name: "Position status tracker" })).not.toBeInTheDocument();

    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "A", pnl: 100, quantity: 10, ltp: 100, average_price: 90, exchange: "NSE", product: "MIS" }],
      }),
    );
    render(<PositionsWidget {...viewProps("net")} />);
    expect(screen.queryByRole("img", { name: "Position status tracker" })).not.toBeInTheDocument();
  });

  // ── Interaction tests ────────────────────────────────────────────────────

  it("shows an unfrozen error banner and Retry button when the initial fetch has no data", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Network timeout"),
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/failed to load positions/i);
    // No prior row or successful update exists, so nothing can truthfully be
    // described as frozen.
    expect(alert.textContent).not.toMatch(/frozen/i);
    expect(alert.textContent).toContain("Network timeout");
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("calls refetch when Retry button is clicked in error state", () => {
    const mockRefetch = vi.fn();
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Server error"),
        refetch: mockRefetch,
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const retryBtn = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retryBtn);

    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });

  it("clicking the Symbol column header toggles sort direction indicator", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", pnl: 500, quantity: 50, ltp: 100, average_price: 90 },
          { symbol: "BANKNIFTY", pnl: 200, quantity: 25, ltp: 200, average_price: 190 },
        ],
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const symbolHeader = screen.getByRole("columnheader", { name: /symbol/i });
    // First click — ascending sort indicator
    fireEvent.click(symbolHeader);
    expect(symbolHeader.textContent).toMatch(/symbol.*↑/i);

    // Second click — descending
    fireEvent.click(symbolHeader);
    expect(symbolHeader.textContent).toMatch(/symbol.*↓/i);
  });

  it("shows Retry button as disabled while isFetching is true", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: undefined,
        isError: true,
        error: new Error("Error"),
        isFetching: true,
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const retryBtn = screen.getByRole("button", { name: /retrying/i });
    expect(retryBtn).toBeDisabled();
  });

  // ── Freshness (absorbed from the retired Net Position widget) ────────────

  it("shows a last-updated indicator once data arrives", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "TATAMOTORS", pnl: 250, quantity: 5, ltp: 950, average_price: 900 }],
        dataUpdatedAt: Date.now(),
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const chip = screen.getByRole("status", { name: /positions last updated/i });
    expect(chip.textContent).toMatch(/updated \d{2}:\d{2}:\d{2}/i);
    expect(chip.textContent).not.toMatch(/stale/i);
  });

  it("flags the P&L as stale when the feed stops refreshing", () => {
    mockUsePositions.mockReturnValue(
      queryResult({
        data: [{ symbol: "TATAMOTORS", pnl: 250, quantity: 5, ltp: 950, average_price: 900 }],
        // Beyond both the market (30s) and off-hours (150s) thresholds.
        dataUpdatedAt: Date.now() - 200_000,
      }),
    );
    render(<PositionsWidget {...defaultProps} />);

    const chip = screen.getByRole("status", { name: /positions last updated .* stale/i });
    expect(chip.textContent).toMatch(/stale since \d{2}:\d{2}:\d{2}/i);
  });

  it("shows no error banner, staleness chip or broker warning for the Explore sample", () => {
    mockModeState.mode = "explore";
    mockUseBrokerConnected.mockReturnValue(false);
    mockUsePositions.mockReturnValue(
      queryResult({ data: undefined, isError: true, error: new Error("unreachable") }),
    );
    render(<PositionsWidget {...defaultProps} />);

    expect(mockUsePositions).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText("Sample")).not.toBeInTheDocument();
    expect(screen.queryByText(/Sample data — connect a broker/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Live only")).toBeNull();
  });

  // ── Convert + exit-all safety actions ───────────────────────────────────

  describe("position actions", () => {
    beforeEach(() => {
      mockBrokerState.accounts = [{
        broker: "dhan",
        account_id: "POSITIONS-A",
        label: "Positions account",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:dhan:POSITIONS-A";
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    function stubFetch(body: unknown = { status: "success", data: { ok: true } }, status = 200) {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );
      vi.stubGlobal("fetch", fetchMock);
      return fetchMock;
    }

    const positions = [
      {
        symbol: "NIFTY24APR24000CE",
        pnl: 1200,
        quantity: 75,
        ltp: 150,
        average_price: 134,
        exchange: "NFO",
        product: "NRML",
      },
      {
        symbol: "RELIANCE",
        pnl: -200,
        quantity: -10,
        ltp: 2900,
        average_price: 2880,
        exchange: "NSE",
        product: "MIS",
      },
    ];

    it("converts a position through the gated convert route", async () => {
      const fetchMock = stubFetch();
      const mockRefetch = vi.fn();
      mockUsePositions.mockReturnValue(queryResult({ data: positions, refetch: mockRefetch }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      expect(screen.getByText("Convert position")).toBeInTheDocument();

      // NRML defaults to MIS as the target product — confirm without
      // touching the select.
      fireEvent.click(
        screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }),
      );

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/ft-api/api/v1/positions/convert");
      expect(init.method).toBe("POST");
      expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("live");
      const body = JSON.parse(String(init.body)) as {
        broker: string;
        req: Record<string, unknown>;
      };
      expect(body.broker).toBe("dhan");
      expect(body.req).toMatchObject({
        symbol: "NIFTY24APR24000CE",
        exchange: "NFO",
        quantity: 75,
        position_type: "LONG",
        from_product: "NRML",
        to_product: "MIS",
        new_product: "MIS",
      });

      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1));
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Position conversion submitted" }),
      );
    });

    it("surfaces the mode-guard 403 honestly inside the convert dialog", async () => {
      stubFetch(
        { status: "error", message: "Live orders are allowed in live mode only — switch mode first" },
        403,
      );
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      fireEvent.click(
        screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }),
      );

      expect(
        await screen.findByText("Live orders are allowed in live mode only — switch mode first"),
      ).toBeInTheDocument();
      // The dialog stays open so the operator can read what blocked it.
      expect(screen.getByText("Convert position")).toBeInTheDocument();
    });

    it("blocks exit-all until the operator types EXIT, then posts the confirmed body", async () => {
      const fetchMock = stubFetch({ status: "success", data: { status: "ok" } });
      const mockRefetch = vi.fn();
      mockUsePositions.mockReturnValue(queryResult({ data: positions, refetch: mockRefetch }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      expect(screen.getByText("Exit all positions?")).toBeInTheDocument();

      const confirmButton = screen.getByRole("button", { name: "Confirm exit all positions" });
      expect(confirmButton).toBeDisabled();

      // Clicking while disabled must never reach the backend.
      fireEvent.click(confirmButton);
      expect(fetchMock).not.toHaveBeenCalled();

      // A wrong phrase keeps it blocked.
      const input = screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i);
      fireEvent.change(input, { target: { value: "exit" } });
      expect(confirmButton).toBeDisabled();
      fireEvent.click(confirmButton);
      expect(fetchMock).not.toHaveBeenCalled();

      // The exact phrase unlocks the action.
      fireEvent.change(input, { target: { value: "EXIT" } });
      expect(confirmButton).toBeEnabled();
      fireEvent.click(confirmButton);

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/ft-api/api/v1/positions/exit-all");
      expect(init.method).toBe("POST");
      expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("live");
      expect(JSON.parse(String(init.body))).toStrictEqual({
        confirm: true,
        broker: "dhan",
        account_id: "POSITIONS-A",
      });

      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1));
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "system", title: "Exit-all submitted" }),
      );
    });

    it("keeps exit-all reachable from the absorbed views (it is book-level)", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByRole("button", { name: "Exit all positions" })).toBeInTheDocument();
      // Per-row writes stay on the table view: a net row is an aggregate of
      // broker rows, and squaring one off would mean inventing a multi-leg plan.
      expect(screen.queryByRole("button", { name: "Square off NIFTY24APR24000CE" })).not.toBeInTheDocument();
    });

    it("surfaces the mode-guard 403 honestly inside the exit-all dialog", async () => {
      stubFetch(
        { status: "error", message: "Live mode is locked — verify your PIN to unlock live trading" },
        403,
      );
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      fireEvent.change(screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i), {
        target: { value: "EXIT" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm exit all positions" }));

      expect(
        await screen.findByText("Live mode is locked — verify your PIN to unlock live trading"),
      ).toBeInTheDocument();
      expect(screen.getByText("Exit all positions?")).toBeInTheDocument();
    });

    // ── Per-position square-off (existing gated placeOrder path) ────────────

    it("squares off a long position with an opposite-side market order via placeOrder", async () => {
      mockPlaceOrder.mockResolvedValue({ orderId: "SQ1" });
      const mockRefetch = vi.fn();
      mockUsePositions.mockReturnValue(queryResult({ data: positions, refetch: mockRefetch }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));

      // Confirm dialog spells out symbol, quantity and side before anything fires.
      expect(screen.getByText("Square off position?")).toBeInTheDocument();
      expect(
        screen.getByText((_, el) =>
          (el?.textContent ?? "").includes("SELL market order for 75 NIFTY24APR24000CE") &&
          el?.tagName === "P",
        ),
      ).toBeInTheDocument();
      expect(mockPlaceOrder).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
      expect(mockPlaceOrder).toHaveBeenCalledWith({
        symbol: "NIFTY24APR24000CE",
        exchange: "NFO",
        action: "SELL",
        product: "NRML",
        orderType: "MARKET",
        quantity: 75,
        price: 0,
        triggerPrice: 0,
        strategy: "FlintPositions",
        rationale: "",
      }, {
        mode: "live",
        scopeKey: "live:native:dhan:POSITIONS-A",
        brokerType: "dhan",
        accountId: "POSITIONS-A",
      }, { exit: true });
      await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1));
      expect(mockEmitNotification).toHaveBeenCalledWith(
        expect.objectContaining({ category: "order", title: "Square-off submitted" }),
      );
    });

    it("sends the square-off admission note with placeOrder", async () => {
      mockPlaceOrder.mockResolvedValue({ orderId: "SQ-NOTE" });
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off RELIANCE" }));
      fireEvent.change(screen.getByLabelText("Add a reason (optional)"), {
        target: { value: "Flatten the open risk" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm square off RELIANCE" }));

      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: "RELIANCE",
          action: "BUY",
          rationale: "Flatten the open risk",
        }),
        expect.anything(),
        { exit: true },
      );
    });

    it("tags a pending exit and refuses a second square-off", () => {
      mockModeState.mode = "practice";
      mockUseOrders.mockReturnValue({
        data: [{
          orderId: "E1",
          symbol: "INFY",
          exchange: "NSE",
          action: "SELL",
          quantity: 4,
          price: 100,
          orderType: "LIMIT",
          status: "OPEN",
          product: "MIS",
          strategy: "",
          timestamp: "",
        }],
      });
      mockUsePositions.mockReturnValue(queryResult({
        data: [{
          symbol: "INFY",
          exchange: "NSE",
          product: "MIS",
          quantity: 10,
          average_price: 100,
          ltp: 101,
          pnl: 10,
        }],
      }));
      render(<PositionsWidget {...defaultProps} />);

      expect(screen.getByText("INFY")).toBeInTheDocument();
      expect(screen.getByText("Exit pending")).toBeInTheDocument();
      const squareOff = screen.getByRole("button", { name: "Square off INFY" });
      expect(squareOff).toBeDisabled();
      fireEvent.click(squareOff);
      expect(screen.queryByText("Square off position?")).not.toBeInTheDocument();
      expect(mockPlaceOrder).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      fireEvent.change(screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i), {
        target: { value: "EXIT" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm exit all positions" }));
      expect(screen.getByText(
        "Not placed. An exit for INFY is already pending. Wait for it to fill, or cancel it and try again.",
      )).toBeInTheDocument();
      expect(mockPlaceOrder).not.toHaveBeenCalled();
    });

    it("tags a position restored from backup", () => {
      mockUsePositions.mockReturnValue(queryResult({
        data: [{
          symbol: "INFY",
          exchange: "NSE",
          product: "MIS",
          quantity: 10,
          average_price: 100,
          ltp: 101,
          pnl: 10,
          restored: true,
        }],
      }));
      render(<PositionsWidget {...defaultProps} />);
      const tag = screen.getByText("Restored");
      expect(tag).toHaveAttribute(
        "title",
        "Restored from backup. Not sent to a broker or checked by Laya.",
      );
    });

    it("shows a flipped position on its own row until the toast is dismissed", async () => {
      const held = {
        symbol: "INFY",
        exchange: "NSE",
        product: "MIS",
        quantity: 10,
        average_price: 100,
        ltp: 110,
        pnl: 100,
      };
      mockUsePositions.mockReturnValue(queryResult({ data: [held] }));
      const { rerender } = render(<PositionsWidget {...defaultProps} />);
      expect(screen.queryByText("Unexpected")).not.toBeInTheDocument();
      expect(screen.queryByTestId("position-flip-toast")).not.toBeInTheDocument();

      mockUsePositions.mockReturnValue(queryResult({
        data: [{ ...held, quantity: -3, pnl: -30 }],
      }));
      rerender(<PositionsWidget {...defaultProps} params={{ nonce: 1 }} />);

      expect(screen.getByText("INFY")).toBeInTheDocument();
      expect(screen.getByText("Unexpected")).toBeInTheDocument();
      expect(screen.getByTestId("position-flip-toast")).toHaveTextContent(
        "Position changed after your broker's orders loaded. You're now short 3 INFY. Close it if that wasn't intended.",
      );
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 30));
      });
      expect(screen.getByTestId("position-flip-toast")).toBeInTheDocument();

      useOperatorSignalStore.setState({ decisionStatus: "down" });
      mockPlaceOrder.mockResolvedValue({ orderId: "CLOSE1" });
      fireEvent.click(screen.getByRole("button", { name: "Close INFY" }));
      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: "INFY",
          exchange: "NSE",
          action: "BUY",
          product: "MIS",
          quantity: 3,
        }),
        expect.objectContaining({
          mode: "live",
          brokerType: "dhan",
          accountId: "POSITIONS-A",
        }),
        { exit: true },
      );

      fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
      expect(screen.queryByTestId("position-flip-toast")).not.toBeInTheDocument();
      expect(screen.getByText("Unexpected")).toBeInTheDocument();
    });
    it("squares off a short position with a BUY market order for the absolute quantity", async () => {
      mockPlaceOrder.mockResolvedValue({ orderId: "SQ2" });
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off RELIANCE" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm square off RELIANCE" }));

      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: "RELIANCE",
          exchange: "NSE",
          action: "BUY",
          product: "MIS",
          orderType: "MARKET",
          quantity: 10,
        }),
        expect.objectContaining({
          scopeKey: "live:native:dhan:POSITIONS-A",
          brokerType: "dhan",
          accountId: "POSITIONS-A",
        }),
        { exit: true },
      );
    });

    it("keeps the square-off control and shows Laya's refusal when a close is denied", async () => {
      mockModeState.mode = "practice";
      mockPlaceOrder.mockRejectedValue(new OrderApiError("Laya denied this order.", 403, {
        code: "laya_denied",
        reason: "Quantity is above the practice limit.",
        message: "Laya denied this order.",
        limits: { max_quantity: 4 },
      }));
      mockUsePositions.mockReturnValue(queryResult({
        data: [
          { symbol: "NIFTY24APR24000CE", pnl: 1200, quantity: 75, ltp: 150, exchange: "NFO", product: "NRML" },
        ],
      }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

      const denied = await screen.findByTestId("laya-denied");
      expect(denied).toHaveTextContent("Laya denied");
      expect(denied).toHaveTextContent("Quantity is above the practice limit.");
      expect(screen.getByText("Max quantity 4.")).toBeInTheDocument();
      expect(screen.getByText("Square off position?")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE", hidden: true })).toBeInTheDocument();
    });

    it("squares off each Practice position through place and reports a partial failure", async () => {
      mockModeState.mode = "practice";
      mockPlaceOrder
        .mockResolvedValueOnce({ orderId: "PQ-OK" })
        .mockRejectedValueOnce(new OrderApiError("Laya denied this order.", 403, {
          code: "laya_denied",
          reason: "Practice book is closed.",
          message: "Laya denied this order.",
        }));
      mockUsePositions.mockReturnValue(queryResult({
        data: [
          { symbol: "INFY", pnl: 100, quantity: 10, ltp: 100, average_price: 90, exchange: "NSE", product: "CNC" },
          { symbol: "TCS", pnl: -50, quantity: -4, ltp: 200, average_price: 210, exchange: "NSE", product: "MIS" },
        ],
      }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      fireEvent.change(screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i), {
        target: { value: "EXIT" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm exit all positions" }));

      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(2));
      expect(mockPlaceOrder).toHaveBeenNthCalledWith(1, expect.objectContaining({
        symbol: "INFY",
        action: "SELL",
        quantity: 10,
        orderType: "MARKET",
        product: "CNC",
        price: 100,
      }), expect.objectContaining({ mode: "practice" }), { exit: true });
      expect(mockPlaceOrder).toHaveBeenNthCalledWith(2, expect.objectContaining({
        symbol: "TCS",
        action: "BUY",
        quantity: 4,
        orderType: "MARKET",
        product: "MIS",
        price: 200,
      }), expect.objectContaining({ mode: "practice" }), { exit: true });
      expect(await screen.findByText("Squared off: INFY.")).toBeInTheDocument();
      expect(screen.getAllByText("TCS").length).toBeGreaterThan(0);
      expect(screen.getByTestId("laya-denied")).toHaveTextContent("Laya denied");
      expect(screen.getByTestId("laya-denied")).toHaveTextContent("Practice book is closed.");
      expect(screen.getByText("Exit all positions?")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Confirm exit all positions" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Exit all positions", hidden: true })).toBeInTheDocument();
    });

    it("surfaces the backend rejection honestly inside the square-off dialog", async () => {
      mockPlaceOrder.mockRejectedValue(
        new Error("Live orders are allowed in live mode only — switch mode first"),
      );
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

      expect(
        await screen.findByText("Live orders are allowed in live mode only — switch mode first"),
      ).toBeInTheDocument();
      // The dialog stays open so the operator can read what blocked it.
      expect(screen.getByText("Square off position?")).toBeInTheDocument();
    });

    it("fails closed on an unrecognised product instead of guessing one", async () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            {
              symbol: "NIFTY24APR24000CE",
              pnl: 100,
              quantity: 75,
              ltp: 150,
              average_price: 134,
              exchange: "NFO",
              product: "BO", // bracket order — not a convertible/square-off product here
            },
          ],
        }),
      );
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      expect(screen.getByText(/unrecognised product/i)).toBeInTheDocument();

      const confirmBtn = screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" });
      expect(confirmBtn).toBeDisabled();
      fireEvent.click(confirmBtn);
      expect(mockPlaceOrder).not.toHaveBeenCalled();
    });

    it("exposes no mutations when account A owns the displayed book but account B is selected", () => {
      const fetchMock = stubFetch();
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:dhan:ACCOUNT-A",
        brokerType: "dhan",
        accountId: "ACCOUNT-A",
      };
      mockBrokerState.accounts = [
        {
          broker: "dhan",
          account_id: "ACCOUNT-A",
          label: "Account A",
          source: "native",
          status: "connected",
        },
        {
          broker: "upstox",
          account_id: "ACCOUNT-B",
          label: "Account B",
          source: "native",
          status: "connected",
        },
      ];
      mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-B";
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));

      render(<PositionsWidget {...defaultProps} />);

      expect(screen.queryByRole("button", { name: "Square off NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Convert NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Exit all positions" })).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
      expect(mockPlaceOrder).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it("refuses all writes when the displayed book differs from the selected native account", () => {
      mockConnectionState.apiKey = "dhan-key";
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:dhan:DIFFERENT",
        brokerType: "dhan",
        accountId: "DIFFERENT",
      };
      mockBrokerState.accounts = [{
        broker: "dhan",
        account_id: "ACCOUNT-A",
        label: "Native account",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:dhan:ACCOUNT-A";
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));

      render(<PositionsWidget {...defaultProps} />);

      expect(screen.queryByRole("button", { name: "Square off NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Convert NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Exit all positions" })).not.toBeInTheDocument();
      expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
    });

    it("refuses mutation when a primary native book is shown without an active selection", () => {
      const fetchMock = stubFetch();
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:dhan:PRIMARY-A",
        brokerType: "dhan",
        accountId: "PRIMARY-A",
      };
      mockBrokerState.accounts = [{
        broker: "dhan",
        account_id: "PRIMARY-A",
        label: "Primary account",
        source: "native",
        status: "connected",
        is_primary: true,
      }];
      mockBrokerState.activeAccountId = null;
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));

      render(<PositionsWidget {...defaultProps} />);

      expect(screen.queryByRole("button", { name: "Square off NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Convert NIFTY24APR24000CE" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Exit all positions" })).not.toBeInTheDocument();
      expect(mockPlaceOrder).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it("does not square off account A after account B is selected while confirmation is open", async () => {
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:dhan:ACCOUNT-A",
        brokerType: "dhan",
        accountId: "ACCOUNT-A",
      };
      mockBrokerState.accounts = [
        {
          broker: "dhan",
          account_id: "ACCOUNT-A",
          label: "Account A",
          source: "native",
          status: "connected",
        },
        {
          broker: "upstox",
          account_id: "ACCOUNT-B",
          label: "Account B",
          source: "native",
          status: "connected",
        },
      ];
      mockBrokerState.activeAccountId = "native:dhan:ACCOUNT-A";
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      const { rerender } = render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-B";
      rerender(<PositionsWidget {...makeWidgetPanelProps()} />);

      const confirm = screen.queryByRole("button", { name: "Confirm square off NIFTY24APR24000CE" });
      if (confirm) fireEvent.click(confirm);
      await waitFor(() => expect(mockPlaceOrder).not.toHaveBeenCalled());
    });

    it("pins the exact displayed account identity into square-off placeOrder", async () => {
      mockReadState.identity = {
        mode: "live",
        scopeKey: "live:native:upstox:ACCOUNT-A",
        brokerType: "upstox",
        accountId: "ACCOUNT-A",
      };
      mockBrokerState.accounts = [{
        broker: "upstox",
        account_id: "ACCOUNT-A",
        label: "Account A",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-A";
      mockPlaceOrder.mockResolvedValue({ orderId: "SQ-EXACT" });
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Square off NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm square off NIFTY24APR24000CE" }));

      await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
      expect(mockPlaceOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          symbol: "NIFTY24APR24000CE",
          action: "SELL",
          quantity: 75,
        }),
        {
          mode: "live",
          scopeKey: "live:native:upstox:ACCOUNT-A",
          brokerType: "upstox",
          accountId: "ACCOUNT-A",
        },
        { exit: true },
      );
    });

    // ── Exact displayed-account target (convert/exit-all are native-only) ──

    it("does not render an independent broker-target selector for position mutations", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);
      expect(screen.queryByRole("combobox", { name: /broker account/i })).not.toBeInTheDocument();
    });

    it("defaults gated position writes to the active native account in native-only Live mode", async () => {
      mockBrokerState.accounts = [
        {
          broker: "upstox",
          account_id: "UP-9",
          label: "F&O",
          source: "native",
          status: "connected",
        },
      ];
      mockBrokerState.activeAccountId = "native:upstox:UP-9";
      const fetchMock = stubFetch();
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(String(init.body)) as { broker: string; account_id: string };
      expect(body.broker).toBe("upstox");
      expect(body.account_id).toBe("UP-9");
    });

    it("threads the exact displayed native account into the convert request", async () => {
      mockBrokerState.accounts = [{
        broker: "dhan",
        account_id: "DHAN-1",
        label: "Primary",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:dhan:DHAN-1";
      const fetchMock = stubFetch();
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE" }));
      fireEvent.click(screen.getByRole("button", { name: "Convert NIFTY24APR24000CE to MIS" }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      const body = JSON.parse(String(init.body)) as { broker: string; account_id: string };
      expect(body.broker).toBe("dhan");
      expect(body.account_id).toBe("DHAN-1");
    });

    it("threads the exact displayed native account into the exit-all request", async () => {
      mockBrokerState.accounts = [{
        broker: "upstox",
        account_id: "UP-9",
        label: "F&O",
        source: "native",
        status: "connected",
      }];
      mockBrokerState.activeAccountId = "native:upstox:UP-9";
      const fetchMock = stubFetch({ status: "success", data: { status: "ok" } });
      mockUsePositions.mockReturnValue(queryResult({ data: positions }));
      render(<PositionsWidget {...defaultProps} />);

      fireEvent.click(screen.getByRole("button", { name: "Exit all positions" }));
      fireEvent.change(screen.getByLabelText(/type EXIT \(in capitals\) to confirm/i), {
        target: { value: "EXIT" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Confirm exit all positions" }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(JSON.parse(String(init.body))).toStrictEqual({
        confirm: true,
        broker: "upstox",
        account_id: "UP-9",
      });
    });
  });

  // ── Net view (absorbed from the retired Net Position widget) ─────────────

  describe("net view", () => {
    const LIVE = [
      { symbol: "TATAMOTORS", exchange: "NSE", product: "MIS", quantity: 5, averagePrice: 900, ltp: 950, pnl: 250 },
      { symbol: "TATAMOTORS", exchange: "NSE", product: "CNC", quantity: -2, averagePrice: 900, ltp: 950, pnl: -100 },
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 2, averagePrice: 800, ltp: 810, pnl: 20 },
    ];

    it("renders the netted table with its headers and totals footer", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: LIVE }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByLabelText("Net positions table")).toBeInTheDocument();
      expect(screen.getByText("Symbol")).toBeInTheDocument();
      expect(screen.getByText("Net Qty")).toBeInTheDocument();
      expect(screen.getByText("Avg")).toBeInTheDocument();
      expect(screen.getByText("LTP")).toBeInTheDocument();
      expect(screen.getByText(/Net P&L/i)).toBeInTheDocument();
      expect(screen.getByText("Exposure")).toBeInTheDocument();
      expect(screen.getByText("Total")).toBeInTheDocument();
    });

    it("nets the broker's split rows for one symbol into a single net row", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: LIVE }));
      render(<PositionsWidget {...viewProps("net")} />);

      // 5 long MIS + 2 short CNC = net +3, one row, under the TATAMOTORS group.
      expect(screen.getByLabelText("TATAMOTORS: net qty 3")).toBeInTheDocument();
      expect(screen.getByLabelText("TATAMOTORS group — 1 positions")).toBeInTheDocument();
      expect(screen.getByText("Positions (2)")).toBeInTheDocument();
    });

    it("clicking a group header collapses its rows", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: LIVE }));
      render(<PositionsWidget {...viewProps("net")} />);

      const group = screen.getByLabelText("TATAMOTORS group — 1 positions");
      expect(group.getAttribute("aria-expanded")).toBe("true");
      expect(screen.getByLabelText("TATAMOTORS: net qty 3")).toBeInTheDocument();

      fireEvent.click(group);
      expect(group.getAttribute("aria-expanded")).toBe("false");
      expect(screen.queryByLabelText("TATAMOTORS: net qty 3")).not.toBeInTheDocument();
    });

    it("keeps offset legs that net to zero, each with its own row", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "RELIANCE", exchange: "NSE", product: "CNC", quantity: 80, averagePrice: 2950, ltp: 2870, pnl: -6400 },
            { symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: -80, averagePrice: 2960, ltp: 2870, pnl: 7200 },
            { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 2, averagePrice: 800, ltp: 810, pnl: 20 },
          ],
        }),
      );
      render(<PositionsWidget {...viewProps("net")} />);

      const cnc = screen.getByLabelText("RELIANCE CNC: net qty 80");
      const mis = screen.getByLabelText("RELIANCE MIS: net qty -80");
      const tooltip = "CNC and MIS legs don't cancel at your broker. At intraday square-off the MIS leg closes and the CNC leg stays open.";
      expect(within(cnc).getByText("Offset")).toHaveAttribute("title", tooltip);
      expect(within(mis).getByText("Offset")).toHaveAttribute("title", tooltip);
      expect(screen.getByText("incl. 1 offset symbol (legs still open)")).toBeInTheDocument();
      expect(screen.queryByText(/flat symbol/)).not.toBeInTheDocument();
      expect(screen.getByLabelText("SBIN: net qty 2")).toBeInTheDocument();
    });

    it("counts a symbol as flat only when every leg is at quantity 0", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "TCS", exchange: "NSE", product: "CNC", quantity: 0, averagePrice: 3900, ltp: 3820, pnl: 0 },
            { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 2, averagePrice: 800, ltp: 810, pnl: 20 },
          ],
        }),
      );
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByText("incl. 1 flat symbol")).toBeInTheDocument();
      expect(screen.queryByText(/offset symbol/)).not.toBeInTheDocument();
      expect(screen.queryByText("TCS")).not.toBeInTheDocument();
      expect(screen.getByLabelText("SBIN: net qty 2")).toBeInTheDocument();
    });

    it("shows the flat and offset notes alongside each other", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "TCS", exchange: "NSE", product: "CNC", quantity: 0, averagePrice: 3900, ltp: 3820, pnl: 0 },
            { symbol: "RELIANCE", exchange: "NSE", product: "CNC", quantity: 80, averagePrice: 2950, ltp: 2870, pnl: -6400 },
            { symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: -80, averagePrice: 2960, ltp: 2870, pnl: 7200 },
          ],
        }),
      );
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByText("incl. 1 offset symbol (legs still open)")).toBeInTheDocument();
      expect(screen.getByText("incl. 1 flat symbol")).toBeInTheDocument();
    });

    it("counts RELIANCE and NIFTY as two offset symbols on the sample book", () => {
      mockModeState.mode = "explore";
      mockUseBrokerConnected.mockReturnValue(false);
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByText("incl. 2 offset symbols (legs still open)")).toBeInTheDocument();
      expect(screen.queryByText(/flat symbol/)).not.toBeInTheDocument();
      expect(screen.getByText("P&L: +₹16,575")).toBeInTheDocument();
      expect(screen.getByText("+₹1,625")).toBeInTheDocument();
      expect(screen.getAllByText("NIFTY24APR22500CE")).toHaveLength(2);
      expect(screen.getByLabelText("RELIANCE CNC: net qty 80")).toBeInTheDocument();
      expect(screen.getByLabelText("RELIANCE MIS: net qty -80")).toBeInTheDocument();
      expect(screen.getByLabelText("BANKNIFTY24APR49000PE: net qty -30")).toBeInTheDocument();
      const niftyMis = screen.getByLabelText("NIFTY24APR22500CE MIS: net qty 65");
      const niftyNrml = screen.getByLabelText("NIFTY24APR22500CE NRML: net qty -65");
      const niftyTip = "MIS and NRML legs don't cancel at your broker. At intraday square-off the MIS leg closes and the NRML leg stays open.";
      expect(within(niftyMis).getByText("Offset")).toHaveAttribute("title", niftyTip);
      expect(within(niftyNrml).getByText("Offset")).toHaveAttribute("title", niftyTip);
      const relianceCnc = screen.getByLabelText("RELIANCE CNC: net qty 80");
      expect(within(relianceCnc).getByText("Offset")).toHaveAttribute(
        "title",
        "CNC and MIS legs don't cancel at your broker. At intraday square-off the MIS leg closes and the CNC leg stays open.",
      );
    });

    it("renders live positions, never the Explore sample, when a broker is connected", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: LIVE }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getAllByText("TATAMOTORS").length).toBeGreaterThanOrEqual(1);
      expect(screen.queryByText("NIFTY24APR22500CE")).toBeNull();
      expect(screen.queryByText("Sample")).toBeNull();
    });

    it("shows the empty state when connected with no positions", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      render(<PositionsWidget {...viewProps("net")} />);

      expect(screen.getByText("No open positions")).toBeInTheDocument();
    });
  });

  // ── Heat view (absorbed from the retired Position Heat Map widget) ───────

  describe("heat view", () => {
    const MOCK_POSITIONS = [
      { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
      { symbol: "TCS", exchange: "NSE", product: "CNC", quantity: 50, averagePrice: 3900, ltp: 3820, pnl: -4000, pnlPercent: -2.1 },
    ];

    it("renders cells rather than the empty state, and counts them in the header", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: MOCK_POSITIONS }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat")} />);
        expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
        expect(screen.getByText("Positions (2)")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^INFY:/ })).toBeInTheDocument();
      });
    });

    it("renders the group-mode selector", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: MOCK_POSITIONS }));
      render(<PositionsWidget {...viewProps("heat")} />);

      expect(screen.getByRole("combobox", { name: /group heat map by/i })).toBeInTheDocument();
    });

    it("clicking a position cell opens a chart via flinttrade:addWidget (not a dead no-op)", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: MOCK_POSITIONS }));
      const events: CustomEvent[] = [];
      const handler = (e: Event) => events.push(e as CustomEvent);
      window.addEventListener("flinttrade:addWidget", handler);
      try {
        withMeasuredContainer(() => {
          render(<PositionsWidget {...viewProps("heat")} />);
          // Cells are role="button" with the symbol in the aria-label.
          fireEvent.click(screen.getByRole("button", { name: /^INFY:/ }));
        });
        expect(events).toHaveLength(1);
        expect(events[0].detail).toMatchObject({
          widgetId: "chart",
          props: { symbol: "INFY", exchange: "NSE" },
        });
      } finally {
        window.removeEventListener("flinttrade:addWidget", handler);
      }
    });

    it("labels a cell with the shared mark-to-market, not the broker P&L field", () => {
      mockUsePositions.mockReturnValue(queryResult({ data: MOCK_POSITIONS }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat")} />);
        // (1510 − 1480) × 100 = +3,000 and (3820 − 3900) × 50 = −4,000.
        expect(screen.getByRole("button", { name: "INFY: +₹3,000 (+2.00%)" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "TCS: -₹4,000 (-2.10%)" })).toBeInTheDocument();
      });
      // Header total agrees with the cells: 3,000 − 4,000 = −1,000.
      expect(screen.getByText("P&L: -₹1,000")).toBeInTheDocument();
    });

    it("prices the sample NIFTY short at one lot of 65", () => {
      mockModeState.mode = "explore";
      mockUseBrokerConnected.mockReturnValue(false);
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "flat" })} />);
        expect(screen.getByRole("button", { name: "NIFTY24APR22500CE: -₹1,950 (-14.60%)" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "NIFTY24APR22500CE: +₹3,575 (+30.60%)" })).toBeInTheDocument();
      });
      expect(screen.getByText("P&L: +₹16,575")).toBeInTheDocument();
    });

    it("shows the Explore sample and its watermark without a broker", () => {
      mockModeState.mode = "explore";
      mockUseBrokerConnected.mockReturnValue(false);
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat")} />);
        expect(screen.queryByText(/Sample data — connect a broker/i)).not.toBeInTheDocument();
        expect(screen.queryByText("Sample")).not.toBeInTheDocument();
        expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
      });
    });

    // ── FT-TRADE-005: labelled group bands, not a silent re-sort ──────────

    it("shows labelled exchange group bands, not a silent re-sort", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
            { symbol: "NIFTY24APR22500CE", exchange: "NFO", product: "MIS", quantity: 65, averagePrice: 180, ltp: 235, pnl: 3575, pnlPercent: 30.6 },
          ],
        }),
      );
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "exchange" })} />);
        expect(screen.getByRole("group", { name: "NSE group" })).toBeInTheDocument();
        expect(screen.getByRole("group", { name: "NFO group" })).toBeInTheDocument();
        expect(screen.getByTestId("heat-group-chip-NSE")).toHaveTextContent("NSE");
        expect(screen.getByTestId("heat-group-chip-NFO")).toHaveTextContent("NFO");
        expect(screen.getByRole("button", { name: /^INFY:/ })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^NIFTY24APR22500CE:/ })).toBeInTheDocument();
        expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
      });
    });

    it("keeps a small exchange group on its own band when the canvas is short", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
            { symbol: "NIFTY24APR22500CE", exchange: "NFO", product: "MIS", quantity: 65, averagePrice: 180, ltp: 235, pnl: 3575, pnlPercent: 30.6 },
          ],
        }),
      );
      // The stack is taller than the canvas; NFO still gets a band and a tile.
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "exchange" })} />);
        expect(screen.getByRole("group", { name: "NSE group" })).toBeInTheDocument();
        expect(screen.getByRole("group", { name: "NFO group" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^INFY:/ })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^NIFTY24APR22500CE:/ })).toBeInTheDocument();
        expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
        expect(screen.queryByTestId("heat-more-overflow")).not.toBeInTheDocument();
      }, { width: 800, height: 60 });
    });

    it("names tiles that do not fit inside their own band and opens them in the list", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "TCS", exchange: "NSE", product: "CNC", quantity: 50, averagePrice: 3900, ltp: 3820, pnl: -4000, pnlPercent: -2.1 },
            { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
            { symbol: "WIPRO", exchange: "NSE", product: "CNC", quantity: 10, averagePrice: 400, ltp: 410, pnl: 100, pnlPercent: 2.5 },
          ],
        }),
      );
      const scrollIntoView = vi.fn();
      const originalScroll = HTMLElement.prototype.scrollIntoView;
      HTMLElement.prototype.scrollIntoView = scrollIntoView;
      try {
        withMeasuredContainer(() => {
          render(<PositionsWidget {...viewProps("heat", { group: "exchange" })} />);
          expect(screen.getByRole("group", { name: "NSE group" })).toBeInTheDocument();
          expect(screen.queryByTestId("heat-more-overflow")).not.toBeInTheDocument();
          const more = screen.getByRole("button", { name: "+3 more: TCS, INFY, WIPRO" });
          expect(more).toHaveAttribute("title", "TCS, INFY, WIPRO");
          expect(screen.getByRole("list", { name: "Positions without a heat map tile" })).toBeInTheDocument();
          expect(screen.getByText("TCS: -₹4,000 (-2.10%)")).toBeInTheDocument();
          fireEvent.click(more);
        }, { width: 16, height: 40 }, { heatOnly: true });
        expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByRole("button", { name: "Heat" })).toHaveAttribute("aria-pressed", "false");
        for (const symbol of ["TCS", "INFY", "WIPRO"]) {
          const row = document.querySelector(`[data-position-key="${symbol}:CNC:NSE"]`);
          expect(row).toHaveAttribute("data-highlighted", "true");
        }
        expect(scrollIntoView).toHaveBeenCalled();
      } finally {
        HTMLElement.prototype.scrollIntoView = originalScroll;
      }
    });

    it("still labels a single exchange group so the mode control looks used", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
            { symbol: "TCS", exchange: "NSE", product: "CNC", quantity: 50, averagePrice: 3900, ltp: 3820, pnl: -4000, pnlPercent: -2.1 },
          ],
        }),
      );
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "exchange" })} />);
        expect(screen.getByRole("group", { name: "NSE group" })).toBeInTheDocument();
        expect(screen.getByTestId("heat-group-chip-NSE")).toHaveTextContent("NSE");
        expect(screen.queryByRole("group", { name: "NFO group" })).not.toBeInTheDocument();
      });
    });

    it("shows an honest empty when positions have no exchange metadata", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "INFY", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
            { symbol: "TCS", product: "CNC", quantity: 50, averagePrice: 3900, ltp: 3820, pnl: -4000, pnlPercent: -2.1 },
          ],
        }),
      );
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "exchange" })} />);
        expect(screen.getByText("No exchange groups in these positions")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /^INFY:/ })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /^TCS:/ })).not.toBeInTheDocument();
        expect(screen.queryByTestId("heat-group-band")).not.toBeInTheDocument();
        expect(screen.queryByRole("group", { name: /group$/ })).not.toBeInTheDocument();
      });
    });

    it("renders Flat without group chrome", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
            { symbol: "NIFTY24APR22500CE", exchange: "NFO", product: "MIS", quantity: 65, averagePrice: 180, ltp: 235, pnl: 3575, pnlPercent: 30.6 },
          ],
        }),
      );
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "flat" })} />);
        expect(screen.queryByTestId("heat-group-band")).not.toBeInTheDocument();
        expect(screen.queryByRole("group", { name: /group$/ })).not.toBeInTheDocument();
        expect(screen.queryByTestId("heat-group-chip-NSE")).not.toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^INFY:/ })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^NIFTY24APR22500CE:/ })).toBeInTheDocument();
      });
    });

    it("shows labelled sector group bands", () => {
      mockUsePositions.mockReturnValue(
        queryResult({
          data: [
            { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
            { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 300, averagePrice: 810, ltp: 832, pnl: 6600, pnlPercent: 2.7 },
          ],
        }),
      );
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "sector" })} />);
        expect(screen.getByRole("group", { name: "IT group" })).toBeInTheDocument();
        expect(screen.getByRole("group", { name: "Banking group" })).toBeInTheDocument();
        expect(screen.getByTestId("heat-group-chip-IT")).toHaveTextContent("IT");
        expect(screen.getByTestId("heat-group-chip-Banking")).toHaveTextContent("Banking");
      });
    });

    it("labels Explore sample exchange groups (NSE and NFO)", () => {
      mockModeState.mode = "explore";
      mockUseBrokerConnected.mockReturnValue(false);
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "exchange" })} />);
        expect(screen.getByRole("group", { name: "NSE group" })).toBeInTheDocument();
        expect(screen.getByRole("group", { name: "NFO group" })).toBeInTheDocument();
        expect(screen.getByTestId("heat-group-chip-NSE")).toHaveTextContent("NSE");
        expect(screen.getByTestId("heat-group-chip-NFO")).toHaveTextContent("NFO");
        expect(screen.queryByText("No exchange groups in these positions")).not.toBeInTheDocument();
        expect(screen.getAllByRole("button", { name: /^NIFTY24APR22500CE:/ })).toHaveLength(2);
        expect(screen.getByRole("button", { name: /^BANKNIFTY24APR49000PE:/ })).toBeInTheDocument();
        expect(heatTiles()).toHaveLength(SAMPLE_POSITION_BOOK.length);
        expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
      });
    });

    it("keeps every Example sample tile when grouped by sector", () => {
      mockModeState.mode = "explore";
      mockUseBrokerConnected.mockReturnValue(false);
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "sector" })} />);
        expect(screen.getByRole("group", { name: "Other group" })).toBeInTheDocument();
        expect(screen.getAllByRole("button", { name: /^NIFTY24APR22500CE:/ })).toHaveLength(2);
        expect(screen.getByRole("button", { name: /^BANKNIFTY24APR49000PE:/ })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^SUNPHARMA:/ })).toBeInTheDocument();
        expect(heatTiles()).toHaveLength(SAMPLE_POSITION_BOOK.length);
        expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
      });
    });

    it("keeps the Example sample's small exchange group on a short canvas", () => {
      mockModeState.mode = "explore";
      mockUseBrokerConnected.mockReturnValue(false);
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "exchange" })} />);
        expect(heatTiles()).toHaveLength(SAMPLE_POSITION_BOOK.length);
        expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
      }, { width: 320, height: 160 });
    });

    it("keeps every Example sample sector band on a short canvas", () => {
      mockModeState.mode = "explore";
      mockUseBrokerConnected.mockReturnValue(false);
      mockUsePositions.mockReturnValue(queryResult({ data: [] }));
      withMeasuredContainer(() => {
        render(<PositionsWidget {...viewProps("heat", { group: "sector" })} />);
        expect(screen.getByRole("group", { name: "Other group" })).toBeInTheDocument();
        expect(screen.getByRole("group", { name: "Pharma group" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /^SUNPHARMA:/ })).toBeInTheDocument();
        expect(screen.getAllByRole("button", { name: /^NIFTY24APR22500CE:/ })).toHaveLength(2);
        expect(heatTiles()).toHaveLength(SAMPLE_POSITION_BOOK.length);
        expect(screen.queryByText(/^\+\d+ more$/)).not.toBeInTheDocument();
      }, { width: 320, height: 160 });
    });
  });
});

// ---------------------------------------------------------------------------
// positionBook kernel — the reconciled definitions
// ---------------------------------------------------------------------------

describe("positionBook", () => {
  it("derives the underlying from the symbol root, spaced or not", () => {
    expect(underlyingOf("NIFTY 22200 CE 10APR")).toBe("NIFTY");
    expect(underlyingOf("BANKNIFTY FUT 24APR")).toBe("BANKNIFTY");
    // A real broker symbol has no spaces — the retired widget's whitespace
    // split made live grouping a no-op.
    expect(underlyingOf("NIFTY24APR22500CE")).toBe("NIFTY");
    expect(underlyingOf("RELIANCE")).toBe("RELIANCE");
  });

  it("classifies a position's sector from lib/sectors.ts, derivatives included", () => {
    const [option, stock] = normalisePositions([
      { symbol: "NIFTY24APR22500CE", quantity: 75, ltp: 235, average_price: 180 },
      { symbol: "SBIN", quantity: 10, ltp: 832, average_price: 810 },
    ]);
    expect(option.sector).toBe("Other"); // index options are not a stock sector
    expect(stock.sector).toBe("Banking");
  });

  it("computes exposure at the mark, falling back to entry when LTP is unusable", () => {
    // |qty| × ltp — what the position is worth now, not what it cost.
    expect(positionExposure(2, 22450, 22400)).toBe(2 * 22450);
    // Short positions carry exposure too.
    expect(positionExposure(-2, 22450, 22400)).toBe(2 * 22450);
    // A broker that reports ltp 0 on an open position must not report zero risk.
    expect(positionExposure(2, 0, 22400)).toBe(2 * 22400);
  });

  it("marks each row to market once, with the broker figure as the fallback", () => {
    const [marked, unpriced] = normalisePositions([
      { symbol: "TCS", quantity: 10, ltp: 3050, average_price: 3000, pnl: 400 },
      { symbol: "NIFTY24APR22500CE", quantity: 75, ltp: 0, average_price: 180, pnl: 640 },
    ]);
    // The recomputation Net Position performed — minus its always-1 lot factor.
    expect(marked.mtm).toBe((3050 - 3000) * 10);
    expect(unpriced.mtm).toBe(640);
  });

  it("nets long and short of the same symbol across products", () => {
    const rows = netPositions(
      normalisePositions([
        { symbol: "NIFTY FUT", exchange: "NFO", product: "NRML", quantity: 2, average_price: 22400, ltp: 22450 },
        { symbol: "NIFTY FUT", exchange: "NFO", product: "MIS", quantity: -1, average_price: 22400, ltp: 22450 },
      ]),
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].netQty).toBe(1);
    expect(rows[0].legs).toBe(2);
  });

  it("keeps open legs that net to zero as separate offset rows", () => {
    const rows = netPositions(
      normalisePositions([
        { symbol: "NIFTY FUT", exchange: "NFO", product: "MIS", quantity: 1, average_price: 22400, ltp: 22400 },
        { symbol: "NIFTY FUT", exchange: "NFO", product: "NRML", quantity: -1, average_price: 22400, ltp: 22400 },
      ]),
    );
    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.netQty)).toEqual([1, -1]);
    expect(rows.every((row) => row.offset)).toBe(true);
    expect(rows[0]?.exposure).toBe(22400);
    expect(rows[1]?.exposure).toBe(22400);
    expect(rows[0]?.offsetProducts).toEqual(["MIS", "NRML"]);
  });

  it("drops a symbol only when every leg is at quantity 0", () => {
    const rows = netPositions(
      normalisePositions([
        { symbol: "WIPRO", exchange: "NSE", product: "CNC", quantity: 0, average_price: 455, ltp: 448 },
        { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 2, average_price: 800, ltp: 810 },
      ]),
    );
    expect(rows.map((row) => row.symbol)).toEqual(["SBIN"]);
    expect(rows[0]?.offset).toBeUndefined();
  });

  it("names offset products and drops the square-off sentence when neither leg is MIS", () => {
    expect(offsetLegTooltip(["MIS", "NRML"])).toBe(
      "MIS and NRML legs don't cancel at your broker. At intraday square-off the MIS leg closes and the NRML leg stays open.",
    );
    expect(offsetLegTooltip(["CNC", "MIS"])).toBe(
      "CNC and MIS legs don't cancel at your broker. At intraday square-off the MIS leg closes and the CNC leg stays open.",
    );
    expect(offsetLegTooltip(["CNC", "NRML"])).toBe(
      "CNC and NRML legs don't cancel at your broker.",
    );
  });

  it("nets P&L as the sum of the rows' mark-to-market, so views cannot disagree", () => {
    const normalised = normalisePositions([
      { symbol: "NIFTY FUT", quantity: 2, average_price: 22400, ltp: 22500, pnl: 1 },
      { symbol: "NIFTY FUT", quantity: -1, average_price: 22400, ltp: 22500, pnl: 2 },
    ]);
    const [net] = netPositions(normalised);
    expect(net.mtm).toBe(normalised.reduce((sum, row) => sum + row.mtm, 0));
    expect(net.mtm).toBeGreaterThan(0); // net long into a rising market
  });

  it("net-row P&L turns negative when the mark falls below a long's average", () => {
    const [net] = netPositions(
      normalisePositions([
        { symbol: "NIFTY FUT", quantity: 1, average_price: 22400, ltp: 22300 },
      ]),
    );
    expect(net.mtm).toBeLessThan(0);
  });

  it("prices a net row's exposure off the net quantity", () => {
    const [net] = netPositions(
      normalisePositions([
        { symbol: "NIFTY FUT", quantity: 3, average_price: 22400, ltp: 22450 },
        { symbol: "NIFTY FUT", quantity: -1, average_price: 22400, ltp: 22450 },
      ]),
    );
    // Net 2 lots at the mark — NOT the gross 4, and not the entry price.
    expect(net.exposure).toBe(2 * 22450);
  });

  it("keeps the example sample book's offset legs as separate rows", () => {
    const rows = netPositions(normalisePositions(SAMPLE_POSITION_BOOK));
    expect(rows).toHaveLength(SAMPLE_POSITION_BOOK.length);
    const nifty = rows.filter((row) => row.symbol === "NIFTY24APR22500CE");
    expect(nifty.map((row) => row.netQty)).toEqual([65, -65]);
    expect(nifty.every((row) => row.offset)).toBe(true);
    const reliance = rows.filter((row) => row.symbol === "RELIANCE");
    expect(reliance.map((row) => [row.product, row.netQty])).toEqual([
      ["CNC", 80],
      ["MIS", -80],
    ]);
    const bank = rows.find((row) => row.symbol === "BANKNIFTY24APR49000PE");
    expect(bank?.netQty).toBe(-30);
    expect(bank?.offset).toBeUndefined();
  });

  it("prices the example sample book at 16,575 and the offset NIFTY group at 1,625", () => {
    const rows = normalisePositions(SAMPLE_POSITION_BOOK);
    expect(totalPositionMtm(rows)).toBe(16_575);
    const nifty = rows.filter((row) => row.symbol === "NIFTY24APR22500CE");
    expect(nifty.reduce((sum, row) => sum + row.mtm, 0)).toBe(1_625);
  });
});
