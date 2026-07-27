import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { Order } from "@/types/api";

// ---------------------------------------------------------------------------
// Mocks — inline selectors to avoid Zustand cast issues
// ---------------------------------------------------------------------------

const mockMode = vi.hoisted(() => ({ value: "explore" }));
const mockWsTicks = vi.hoisted(() => ({ value: {} as Record<string, { ltp: number }> }));
const mockPlaceOrder = vi.hoisted(() => vi.fn());
// The ladder resolves a real lot size before it will place a derivative
// order; equity instruments report 1.
const mockGetSymbol = vi.hoisted(() =>
  vi.fn(() => Promise.resolve({ symbol: "NIFTY", exchange: "NSE", lotsize: 1, tick_size: 0.05 })),
);
const mockCancelOrder = vi.hoisted(() => vi.fn());
// Live orderbook feed the widget reconciles its rows against (useOrders).
// null = no book response yet; set an Order[] to drive reconciliation.
const mockBrokerOrders = vi.hoisted(() => ({ value: null as unknown }));
// Shared depth query (["depth", symbol, exchange]) — the merged widget's book.
const mockDepthQuery = vi.hoisted(() => vi.fn());

// Production's useTrackBehavior is memoised with useCallback, so the tracker's
// identity is STABLE across renders. A mock that minted a new function each
// render would silently refresh every callback whose dep array contains it,
// hiding stale-closure bugs in the order path — keep this stable.
const mockTrack = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => mockTrack,
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: mockMode.value }),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  default: () => ({ ticks: mockWsTicks.value, connected: true }),
}));

vi.mock("@/hooks/useOrders", () => ({
  useOrders: () => ({ data: mockBrokerOrders.value }),
}));

vi.mock("@/hooks/useDepthData", () => ({
  useDepthData: (symbol: string, exchange: string, enabled: boolean) =>
    mockDepthQuery(symbol, exchange, enabled),
}));

vi.mock("@/services/api", () => ({
  placeOrder: mockPlaceOrder,
  cancelOrder: mockCancelOrder,
  getSymbol: mockGetSymbol,
}));

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  mockMode.value = "explore";
  mockWsTicks.value = {};
  mockBrokerOrders.value = null;
  mockPlaceOrder.mockResolvedValue({ orderId: "test_123" });
  mockCancelOrder.mockResolvedValue(undefined);
  mockDepthQuery.mockReturnValue({
    data: undefined,
    isError: false,
    error: null,
    dataUpdatedAt: 0,
  });
});

import OrderLadderWidget, {
  applyBookToLevels,
  generateLadderLevels,
  extractBrokerOrderId,
  isTerminalOrderStatus,
  reconcilePendingOrders,
  type PendingOrder,
} from "../OrderLadderWidget";
import { bookImbalance, normaliseDepth } from "@/lib/depth";

/** Drive the merged widget's shared depth query with a raw wire payload. */
function setBook(raw: unknown): void {
  mockDepthQuery.mockReturnValue({
    data: raw,
    isError: false,
    error: null,
    dataUpdatedAt: 1_700_000_000_000,
  });
}

/** Minimal fully-typed orderbook row for reconciliation tests. */
function makeBookOrder(orderId: string, status: string): Order {
  return {
    orderId,
    symbol: "NIFTY",
    exchange: "NSE",
    action: "BUY",
    quantity: 25,
    price: 105,
    orderType: "LIMIT",
    status,
    product: "MIS",
    strategy: "orderladder",
    timestamp: "2026-07-07 10:00:00",
  };
}

// ---------------------------------------------------------------------------
// generateLadderLevels unit tests
// ---------------------------------------------------------------------------

describe("generateLadderLevels", () => {
  it("generates 41 levels (20 above + centre + 20 below)", () => {
    const levels = generateLadderLevels(22000, 0.25);
    expect(levels).toHaveLength(41);
  });

  it("first level is 20 ticks above centre", () => {
    const levels = generateLadderLevels(22000, 1);
    expect(levels[0].price).toBeCloseTo(22020, 1);
  });

  it("last level is 20 ticks below centre", () => {
    const levels = generateLadderLevels(22000, 1);
    expect(levels[40].price).toBeCloseTo(21980, 1);
  });

  it("centre level (index 20) equals centre price", () => {
    const levels = generateLadderLevels(22150, 0.5);
    expect(levels[20].price).toBeCloseTo(22150, 2);
  });

  it("all prices are finite numbers", () => {
    const levels = generateLadderLevels(100, 0.05);
    for (const l of levels) {
      expect(isFinite(l.price)).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("OrderLadderWidget", () => {
  it("renders widget title", () => {
    render(<OrderLadderWidget />);
    // Renamed by the Depth merge: one widget carries both the book and the
    // order ladder, so the header names both.
    expect(screen.getByText("DOM / Ladder")).toBeTruthy();
  });

  it("renders default symbol NIFTY", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("NIFTY")).toBeTruthy();
  });

  it("renders default exchange NSE", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("NSE")).toBeTruthy();
  });

  it("renders Bid and Ask column headers", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("Bid")).toBeTruthy();
    expect(screen.getByText("Ask")).toBeTruthy();
    expect(screen.getByText("Price")).toBeTruthy();
  });

  it("renders quantity input", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByLabelText("Order quantity")).toBeTruthy();
  });

  it("renders tick size selector group", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByRole("group", { name: "Tick size" })).toBeTruthy();
  });

  it("price ladder aria-label is present", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByLabelText("Price ladder")).toBeTruthy();
  });

  it("clicking bid in explore mode shows connect message", async () => {
    render(<OrderLadderWidget />);
    // Find first sell button on the ladder
    const sellBtns = screen.getAllByRole("button").filter((b) =>
      b.getAttribute("title")?.startsWith("SELL")
    );
    if (sellBtns.length > 0) {
      fireEvent.click(sellBtns[0]);
      const status = await screen.findByRole("status");
      expect(status.textContent).toContain("broker");
    }
  });

  it("custom symbol rendered in header", () => {
    render(<OrderLadderWidget symbol="BANKNIFTY" exchange="NSE_FO" />);
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
    expect(screen.getByText("NSE_FO")).toBeTruthy();
  });

  it("Qty label is present in controls", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("Qty")).toBeTruthy();
  });

  it("Tick label is present in controls", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("Tick")).toBeTruthy();
  });

  it("changing qty input updates the value", () => {
    render(<OrderLadderWidget />);
    const input = screen.getByLabelText("Order quantity") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "50" } });
    expect(input.value).toBe("50");
  });
});

// ---------------------------------------------------------------------------
// extractBrokerOrderId unit tests
// ---------------------------------------------------------------------------

describe("extractBrokerOrderId", () => {
  it("reads orderId / orderid / order_id aliases", () => {
    expect(extractBrokerOrderId({ orderId: "A1" })).toBe("A1");
    expect(extractBrokerOrderId({ orderid: "B2" })).toBe("B2");
    expect(extractBrokerOrderId({ order_id: "C3" })).toBe("C3");
  });

  it("accepts a bare string or numeric id", () => {
    expect(extractBrokerOrderId("XYZ")).toBe("XYZ");
    expect(extractBrokerOrderId({ orderId: 12345 })).toBe("12345");
  });

  it("returns null for anything else — the caller must fail closed", () => {
    expect(extractBrokerOrderId(undefined)).toBeNull();
    expect(extractBrokerOrderId(null)).toBeNull();
    expect(extractBrokerOrderId({})).toBeNull();
    expect(extractBrokerOrderId({ orderId: "" })).toBeNull();
    expect(extractBrokerOrderId("")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Live-mode order placement + cancel with the REAL broker order id
// ---------------------------------------------------------------------------

describe("OrderLadderWidget live cancel", () => {
  function renderLiveLadder(): void {
    mockMode.value = "live";
    mockWsTicks.value = { "NSE:NIFTY": { ltp: 100 } };
    render(<OrderLadderWidget />);
  }

  async function placeBuyAtTopLevel(): Promise<void> {
    // Top ask level = 100 + 20 × 0.25 = 105.00
    const askBtn = screen
      .getAllByRole("button")
      .find((b) => b.getAttribute("title")?.startsWith("BUY"));
    expect(askBtn).toBeTruthy();
    fireEvent.click(askBtn as HTMLElement);
    await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
  }

  it("cancels a ladder order with the REAL broker order id from placeOrder", async () => {
    mockPlaceOrder.mockResolvedValue({ orderId: "BRK-98765" });
    renderLiveLadder();

    await placeBuyAtTopLevel();

    // The cancel affordance unlocks only once the broker id is stored
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/^Cancel buy order at/) as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByLabelText(/^Cancel buy order at/));

    await waitFor(() => {
      expect(mockCancelOrder).toHaveBeenCalledTimes(1);
      expect(mockCancelOrder).toHaveBeenCalledWith("BRK-98765", "orderladder");
    });
    // Never the fabricated local id
    expect(mockCancelOrder).not.toHaveBeenCalledWith(
      expect.stringMatching(/^lo_/),
      expect.anything(),
    );
  });

  it("disables cancel (fail closed) when the broker id is not in the response", async () => {
    mockPlaceOrder.mockResolvedValue({ status: "success" });
    renderLiveLadder();

    await placeBuyAtTopLevel();

    // Placement resolved (status message shown) but no broker id was returned
    await screen.findByText(/order id unconfirmed/);
    const cancelBtn = screen.getByLabelText(/^Cancel buy order at/) as HTMLButtonElement;
    expect(cancelBtn.disabled).toBe(true);
    fireEvent.click(cancelBtn);
    expect(mockCancelOrder).not.toHaveBeenCalled();
  });

  it("removes the pending row when placeOrder rejects", async () => {
    mockPlaceOrder.mockRejectedValue(new Error("Order blocked in live mode."));
    renderLiveLadder();

    await placeBuyAtTopLevel();

    await waitFor(() => {
      expect(screen.queryByLabelText(/^Cancel buy order at/)).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// isTerminalOrderStatus unit tests
// ---------------------------------------------------------------------------

describe("isTerminalOrderStatus", () => {
  it("treats fills, rejections and cancellations as terminal", () => {
    for (const status of ["complete", "FILLED", "Executed", "rejected", "cancelled", "CANCELED"]) {
      expect(isTerminalOrderStatus(status)).toBe(true);
    }
  });

  it("keeps pending variants and partial fills live", () => {
    for (const status of ["open", "open pending", "trigger pending", "cancel pending", "partially filled"]) {
      expect(isTerminalOrderStatus(status)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// reconcilePendingOrders unit tests — fail-safe row reconciliation
// ---------------------------------------------------------------------------

describe("reconcilePendingOrders", () => {
  function makeRow(overrides: Partial<PendingOrder> = {}): PendingOrder {
    return {
      localId: "lo_1",
      brokerOrderId: "BRK-1",
      side: "buy",
      price: 105,
      qty: 25,
      status: "open",
      ...overrides,
    };
  }

  it("drops rows whose broker order left the book (filled or rejected)", () => {
    const rows = [
      makeRow({ localId: "lo_1", brokerOrderId: "BRK-1" }),
      makeRow({ localId: "lo_2", brokerOrderId: "BRK-2", side: "sell" }),
    ];
    const book = [makeBookOrder("BRK-1", "complete"), makeBookOrder("BRK-2", "rejected")];
    expect(reconcilePendingOrders(rows, book)).toEqual([]);
  });

  it("keeps rows whose broker order is still live in the book", () => {
    const rows = [makeRow()];
    const book = [makeBookOrder("BRK-1", "open")];
    expect(reconcilePendingOrders(rows, book)).toEqual(rows);
  });

  it("keeps rows without a confirmed broker id — the book cannot vouch for them", () => {
    const rows = [makeRow({ brokerOrderId: null, status: "placing" })];
    const book = [makeBookOrder("BRK-1", "complete")];
    expect(reconcilePendingOrders(rows, book)).toEqual(rows);
  });

  it("keeps rows whose id is absent from the book (fail-safe against partial responses)", () => {
    const rows = [makeRow({ brokerOrderId: "BRK-MISSING" })];
    const book = [makeBookOrder("BRK-OTHER", "complete")];
    expect(reconcilePendingOrders(rows, book)).toEqual(rows);
  });
});

// ---------------------------------------------------------------------------
// Orderbook reconciliation in the widget — fills/rejections done elsewhere
// must clear stale ladder rows (and their live-looking cancel affordances).
// ---------------------------------------------------------------------------

describe("OrderLadderWidget orderbook reconciliation", () => {
  function renderLiveLadder(): void {
    mockMode.value = "live";
    mockWsTicks.value = { "NSE:NIFTY": { ltp: 100 } };
    render(<OrderLadderWidget />);
  }

  async function placeBuyAtTopLevel(): Promise<void> {
    const askBtn = screen
      .getAllByRole("button")
      .find((b) => b.getAttribute("title")?.startsWith("BUY"));
    expect(askBtn).toBeTruthy();
    fireEvent.click(askBtn as HTMLElement);
    await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
  }

  it("clears the row when the orderbook reports the order filled", async () => {
    mockPlaceOrder.mockResolvedValue({ orderId: "BRK-FILL-1" });
    mockBrokerOrders.value = [makeBookOrder("BRK-FILL-1", "complete")];
    renderLiveLadder();

    await placeBuyAtTopLevel();

    await waitFor(() => {
      expect(screen.queryByLabelText(/^Cancel buy order at/)).toBeNull();
    });
    expect(await screen.findByText(/1 order left the book/)).toBeTruthy();
    expect(mockCancelOrder).not.toHaveBeenCalled();
  });

  it("clears the row when the orderbook reports the order rejected", async () => {
    mockPlaceOrder.mockResolvedValue({ orderId: "BRK-REJ-1" });
    mockBrokerOrders.value = [makeBookOrder("BRK-REJ-1", "rejected")];
    renderLiveLadder();

    await placeBuyAtTopLevel();

    await waitFor(() => {
      expect(screen.queryByLabelText(/^Cancel buy order at/)).toBeNull();
    });
    expect(await screen.findByText(/1 order left the book/)).toBeTruthy();
  });

  it("keeps the row (cancel stays live) while the book shows the order still open", async () => {
    mockPlaceOrder.mockResolvedValue({ orderId: "BRK-OPEN-1" });
    mockBrokerOrders.value = [makeBookOrder("BRK-OPEN-1", "open")];
    renderLiveLadder();

    await placeBuyAtTopLevel();

    // The cancel affordance appears once the broker id is stored — and stays.
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/^Cancel buy order at/) as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    expect(screen.queryByText(/left the book/)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Lot-size validation. The ladder ships a free integer quantity and a
// hardcoded default of 25; on a derivative that is the non-lot-multiple order
// every other order ticket refuses. It used to send it.
// ---------------------------------------------------------------------------

describe("OrderLadderWidget derivative lot validation", () => {
  it("refuses a non-lot-multiple quantity on a derivative exchange", async () => {
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY", exchange: "NFO", lotsize: 75, tick_size: 0.05,
    });
    mockMode.value = "live";
    mockWsTicks.value = { "NFO:NIFTY": { ltp: 100 } };
    render(<OrderLadderWidget symbol="NIFTY" exchange="NFO" />);

    // Default quantity is 25 — not a multiple of the 75 lot size. The lot
    // lookup is async, so retry the click until it has resolved; until then
    // the widget fails closed on the unverified lot size instead.
    await waitFor(() => {
      const askBtn = screen
        .getAllByRole("button")
        .find((b) => b.getAttribute("title")?.startsWith("BUY"));
      fireEvent.click(askBtn as HTMLElement);
      expect(screen.getByText(/multiple of the lot size \(75\)/i)).toBeTruthy();
    });
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("places a lot-multiple derivative order once the lot size resolves", async () => {
    // Regression: the submit callback did not list the resolved lot size in
    // its dependencies, so with a memoised tracker it kept reading the
    // pre-fetch {lotSize: 0, verified: false} and refused every derivative
    // order as unverified — for good.
    mockGetSymbol.mockResolvedValue({
      symbol: "NIFTY", exchange: "NFO", lotsize: 75, tick_size: 0.05,
    });
    mockMode.value = "live";
    mockWsTicks.value = { "NFO:NIFTY": { ltp: 100 } };
    render(<OrderLadderWidget symbol="NIFTY" exchange="NFO" />);

    const qtyInput = screen.getByLabelText("Order quantity") as HTMLInputElement;
    fireEvent.change(qtyInput, { target: { value: "75" } });

    await waitFor(() => {
      const askBtn = screen
        .getAllByRole("button")
        .find((b) => b.getAttribute("title")?.startsWith("BUY"));
      fireEvent.click(askBtn as HTMLElement);
      expect(mockPlaceOrder).toHaveBeenCalled();
    });
    expect(mockPlaceOrder.mock.calls[0][0]).toMatchObject({ quantity: 75, exchange: "NFO" });
  });

  it("fails closed while the derivative lot size is unconfirmed", async () => {
    mockGetSymbol.mockRejectedValue(new Error("symbol master unavailable"));
    mockMode.value = "live";
    mockWsTicks.value = { "NFO:BANKNIFTY": { ltp: 100 } };
    render(<OrderLadderWidget symbol="BANKNIFTY" exchange="NFO" />);

    const askBtn = screen
      .getAllByRole("button")
      .find((b) => b.getAttribute("title")?.startsWith("BUY"));
    fireEvent.click(askBtn as HTMLElement);

    expect(await screen.findByText(/unverified/i)).toBeTruthy();
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// applyBookToLevels — the merge's core: real resting sizes keyed onto the
// ladder's price rows. Absorbed from the retired Depth widget, which owned the
// only real book in the family and could not trade on it.
// ---------------------------------------------------------------------------

describe("applyBookToLevels", () => {
  const grid = () => generateLadderLevels(100, 0.25);

  it("keys bid and ask levels onto the matching ladder rows", () => {
    const rows = applyBookToLevels(grid(), {
      bids: [{ price: 99.75, qty: 1200, orders: 45 }],
      asks: [{ price: 100.25, qty: 900, orders: 38 }],
    }, 0.25);

    const bidRow = rows.find((r) => r.price === 99.75);
    const askRow = rows.find((r) => r.price === 100.25);
    expect(bidRow).toMatchObject({ bidQty: 1200, bidOrders: 45, askQty: 0 });
    expect(askRow).toMatchObject({ askQty: 900, askOrders: 38, bidQty: 0 });
  });

  it("aggregates levels that collapse onto one row at a wider tick", () => {
    const rows = applyBookToLevels(generateLadderLevels(100, 5), {
      bids: [
        { price: 99.95, qty: 500, orders: 5 },
        { price: 99.9, qty: 300, orders: 3 },
      ],
      asks: [],
    }, 5);

    const centre = rows.find((r) => r.price === 100);
    expect(centre).toMatchObject({ bidQty: 800, bidOrders: 8 });
  });

  it("drops levels outside the ±20-tick window rather than clamping them", () => {
    const rows = applyBookToLevels(grid(), {
      bids: [{ price: 50, qty: 9999, orders: 99 }],
      asks: [{ price: 500, qty: 9999, orders: 99 }],
    }, 0.25);

    expect(rows.every((r) => r.bidQty === 0 && r.askQty === 0)).toBe(true);
  });

  it("ignores zero-size and malformed levels", () => {
    const rows = applyBookToLevels(grid(), {
      bids: [{ price: 99.75, qty: 0, orders: 0 }, { price: 0, qty: 100, orders: 1 }],
      asks: [{ price: Number.NaN, qty: 100, orders: 1 }],
    }, 0.25);

    expect(rows.every((r) => r.bidQty === 0 && r.askQty === 0)).toBe(true);
  });

  it("does not mutate the input rows", () => {
    const input = grid();
    applyBookToLevels(input, { bids: [{ price: 99.75, qty: 1200, orders: 45 }], asks: [] }, 0.25);
    expect(input.every((r) => r.bidQty === 0 && r.askQty === 0)).toBe(true);
  });

  it("generateLadderLevels never fabricates quantities", () => {
    expect(generateLadderLevels(22000, 0.25).every(
      (l) => l.bidQty === 0 && l.askQty === 0 && l.bidOrders === 0 && l.askOrders === 0,
    )).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Live-mode book. THE regression this merge exists to fix: the ladder used to
// hardcode bid/ask quantities to zero in live mode (it had no depth feed at
// all), so it showed an empty book beside a live price.
// ---------------------------------------------------------------------------

describe("OrderLadderWidget live depth", () => {
  function renderLiveLadder(symbol = "NIFTY", exchange = "NSE"): void {
    mockMode.value = "live";
    mockWsTicks.value = { [`${exchange}:${symbol}`]: { ltp: 100 } };
    render(<OrderLadderWidget symbol={symbol} exchange={exchange} />);
  }

  it("shows REAL resting quantities on the ladder rows in live mode", () => {
    setBook({
      buy: [
        { price: 99.75, quantity: 1200, orders: 45 },
        { price: 99.5, quantity: 800, orders: 30 },
      ],
      sell: [
        { price: 100.25, quantity: 900, orders: 38 },
        { price: 100.5, quantity: 1100, orders: 42 },
      ],
    });
    renderLiveLadder();

    expect(screen.getByLabelText("Sell 25 at 99.75: 1200 bids")).toBeTruthy();
    expect(screen.getByLabelText("Sell 25 at 99.50: 800 bids")).toBeTruthy();
    expect(screen.getByLabelText("Buy 25 at 100.25: 900 asks")).toBeTruthy();
    expect(screen.getByLabelText("Buy 25 at 100.50: 1100 asks")).toBeTruthy();
    // The pre-merge behaviour — a priced row with no size — is gone for those levels.
    expect(screen.queryByLabelText("Place sell at 99.75")).toBeNull();
    expect(screen.queryByLabelText("Place buy at 100.25")).toBeNull();
  });

  it("renders the orders-count column absorbed from Depth", () => {
    setBook({ buy: [{ price: 99.75, quantity: 1200, orders: 45 }], sell: [] });
    renderLiveLadder();

    expect(screen.getByTitle("45 bid orders at 99.75")).toBeTruthy();
  });

  it("reads the book through the shared normaliser (short broker aliases)", () => {
    // These are the aliases only the retired Depth widget handled; the merged
    // widget gets them from @/lib/depth, so a bridge emitting p/q/num_orders
    // no longer renders a silently empty book.
    setBook({
      bids: [{ p: 99.75, q: 1200, num_orders: 45 }],
      asks: [{ p: "100.25", q: "900", num_orders: "38" }],
    });
    renderLiveLadder();

    expect(screen.getByLabelText("Sell 25 at 99.75: 1200 bids")).toBeTruthy();
    expect(screen.getByLabelText("Buy 25 at 100.25: 900 asks")).toBeTruthy();
  });

  it("subscribes to the shared depth query key rather than its own poller", () => {
    renderLiveLadder("BANKNIFTY", "NFO");
    expect(mockDepthQuery).toHaveBeenCalledWith("BANKNIFTY", "NFO", true);
  });

  it("leaves the quantity columns blank and flags the failure when depth errors", () => {
    mockDepthQuery.mockReturnValue({
      data: undefined,
      isError: true,
      error: new Error("depth feed down"),
      dataUpdatedAt: 0,
    });
    renderLiveLadder();

    expect(screen.getByText(/Depth unavailable/)).toBeTruthy();
    expect(screen.getByLabelText("Place sell at 99.75")).toBeTruthy();
    expect(screen.queryByLabelText("Bid/ask dominance")).toBeNull();
  });

  it("shows the spread from the real book", () => {
    setBook({
      buy: [{ price: 99.75, quantity: 1200, orders: 45 }],
      sell: [{ price: 100.25, quantity: 900, orders: 38 }],
    });
    renderLiveLadder();

    const spread = screen.getByLabelText("Book spread");
    expect(spread.textContent).toContain("0.50");
  });
});

// ---------------------------------------------------------------------------
// Bid/ask dominance footer — absorbed from Depth, but computed with the shared
// signed kernel (lib/depth bookImbalance) instead of a third percentage.
// ---------------------------------------------------------------------------

describe("OrderLadderWidget dominance footer", () => {
  it("reads the dominance percentage from the shared bookImbalance kernel", () => {
    const raw = {
      buy: [
        { price: 99.75, quantity: 2000, orders: 20 },
        { price: 99.5, quantity: 1000, orders: 10 },
      ],
      sell: [{ price: 100.25, quantity: 1000, orders: 10 }],
    };
    setBook(raw);
    mockMode.value = "live";
    mockWsTicks.value = { "NSE:NIFTY": { ltp: 100 } };
    render(<OrderLadderWidget />);

    const book = normaliseDepth(raw);
    const expected = ((bookImbalance(book.bids, book.asks) + 1) / 2) * 100;
    expect(expected).toBeCloseTo(75, 5);
    expect(screen.getByText(`${expected.toFixed(1)}% bid`)).toBeTruthy();
    expect(screen.getByText(`${(100 - expected).toFixed(1)}% ask`)).toBeTruthy();
    expect(
      screen.getByLabelText(`Resting book dominance: ${expected.toFixed(1)} percent bid`),
    ).toBeTruthy();
  });

  it("hides the footer when the book carries no resting volume", () => {
    mockMode.value = "live";
    mockWsTicks.value = { "NSE:NIFTY": { ltp: 100 } };
    render(<OrderLadderWidget />);
    expect(screen.queryByLabelText("Bid/ask dominance")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Explore mode — ported from the retired Depth suite: a labelled deterministic
// sample book, and no broker call.
// ---------------------------------------------------------------------------

describe("OrderLadderWidget explore sample book", () => {
  it("uses the sample book in explore mode without enabling the depth query", () => {
    render(<OrderLadderWidget />);

    expect(screen.getByText("Explore · sample")).toBeTruthy();
    expect(mockDepthQuery).toHaveBeenCalledWith("NIFTY", "NSE", false);
    expect(screen.getByLabelText("Showing demo data")).toBeTruthy();
  });

  it("keys the sample book onto the demo ladder rows", () => {
    render(<OrderLadderWidget />);
    // SAMPLE centre 22150.25 = best bid; first ask one tick above.
    expect(screen.getByLabelText("Sell 25 at 22,150.25: 14850 bids")).toBeTruthy();
    expect(screen.getByLabelText("Buy 25 at 22,150.50: 13200 asks")).toBeTruthy();
  });

  it("sample dominance is bid-heavy and matches the shared kernel", () => {
    render(<OrderLadderWidget />);
    const bidQty = 14850 + 11275 + 9150 + 7625 + 5840;
    const askQty = 13200 + 10450 + 8860 + 7210 + 5685;
    const expected = (bidQty / (bidQty + askQty)) * 100;
    expect(screen.getByText(`${expected.toFixed(1)}% bid`)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Exchange picker — absorbed from Depth; the ladder took a prop only.
// ---------------------------------------------------------------------------

describe("OrderLadderWidget exchange picker", () => {
  it("renders a picker seeded from the panel prop", () => {
    render(<OrderLadderWidget />);
    const picker = screen.getByLabelText("Exchange");
    expect(picker.textContent).toBe("NSE");
  });

  it("keeps an exchange the picker does not list (never blanks the header)", () => {
    render(<OrderLadderWidget symbol="BANKNIFTY" exchange="NSE_FO" />);
    expect(screen.getByLabelText("Exchange").textContent).toBe("NSE_FO");
  });

  it("accepts symbol / exchange / tick from workspace panel params", () => {
    mockMode.value = "live";
    mockWsTicks.value = { "NSE_INDEX:NIFTY": { ltp: 100 } };
    render(<OrderLadderWidget params={{ symbol: "NIFTY", exchange: "NSE_INDEX", tick: 0.05 }} />);

    expect(mockDepthQuery).toHaveBeenCalledWith("NIFTY", "NSE_INDEX", true);
    expect(screen.getByLabelText("Exchange").textContent).toBe("NSE_INDEX");
    // 0.05 tick → the row one tick below the 100.00 centre.
    expect(screen.getByLabelText("Place sell at 99.95")).toBeTruthy();
  });
});
