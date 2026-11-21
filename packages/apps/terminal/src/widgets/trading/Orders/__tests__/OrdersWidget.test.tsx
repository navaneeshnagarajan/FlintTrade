/**
 * OrdersWidget.test.tsx
 *
 * Tests for the Orders trading widget.
 * Verifies rendering, empty state, order row display, and the per-order
 * Cancel/Modify actions wired to the REAL broker order id.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUseOrders = vi.fn();
const mockUseBrokerConnected = vi.fn();
const mockMode = vi.hoisted(() => ({ value: "live" }));
const mockBrokerType = vi.hoisted(() => ({ value: "" }));
const mockCancelOrder = vi.hoisted(() => vi.fn());
const mockModifyOrder = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useOrders", () => ({
  useOrders: (...args: unknown[]) => mockUseOrders(...args),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockUseBrokerConnected(),
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => mockUseBrokerConnected(),
  useAccountReadContext: () => {
    const brokerType = mockBrokerType.value || (
      mockMode.value === "explore"
        ? "mock"
        : mockMode.value === "practice"
          ? "sandbox"
          : "upstox"
    );
    return {
    identity: {
      mode: mockMode.value,
      scopeKey:
        mockMode.value === "explore"
          ? "explore:mock:default"
          : mockMode.value === "practice"
            ? "practice:sandbox:default"
            : `live:native:${brokerType}:U1`,
      brokerType,
      accountId: mockMode.value === "live" ? "U1" : "default",
    },
    enabled: mockUseBrokerConnected(),
    host: "",
    apiKey: "",
    };
  },
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: mockMode.value }),
}));

vi.mock("@/services/api", () => ({
  cancelOrder: mockCancelOrder,
  modifyOrder: mockModifyOrder,
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import OrdersWidget, { isOpenOrderStatus, toOrderRow } from "../OrdersWidget";
import { writePersistedAuthSession, clearPersistedAuthSession } from "@/lib/homeEntry";
import { clearPendingOrderOutcomes } from "@/lib/pendingOrderStore";
import { submitOrderOnce } from "@/lib/orderSubmitGuard";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeWidgetPanelProps();

function renderWidget() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OrdersWidget {...defaultProps} />
    </QueryClientProvider>,
  );
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

const OPEN_ORDER = {
  orderid: "ORD123",
  symbol: "NIFTY24APR24000CE",
  exchange: "NFO",
  action: "BUY",
  quantity: 75,
  price: 150,
  pricetype: "LIMIT",
  product: "MIS",
  order_status: "open",
  disclosedQuantity: "0",
};

const COMPLETE_ORDER = {
  orderid: "ORD456",
  symbol: "BANKNIFTY24APR51000PE",
  exchange: "NFO",
  action: "SELL",
  quantity: 30,
  price: 0,
  pricetype: "MARKET",
  product: "MIS",
  order_status: "complete",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OrdersWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockMode.value = "live";
    mockBrokerType.value = "";
    mockCancelOrder.mockReset();
    mockCancelOrder.mockResolvedValue(undefined);
    mockModifyOrder.mockReset();
    mockModifyOrder.mockResolvedValue({ orderId: "ORD123" });
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseOrders.mockReturnValue(queryResult({ data: [] }));
  });

  it("renders without crashing", () => {
    const { container } = renderWidget();
    expect(container).toBeTruthy();
  });

  it("shows 'No orders today' when data is empty", () => {
    mockUseOrders.mockReturnValue(queryResult({ data: [] }));
    renderWidget();

    expect(screen.getByText("No orders today")).toBeInTheDocument();
  });

  it("shows pending status before first authoritative success (and no empty or error)", () => {
    mockUseOrders.mockReturnValue(queryResult({ isPending: true, isLoading: true, data: undefined }));
    renderWidget();

    expect(screen.getByLabelText(/loading orders/i)).toBeInTheDocument();
    expect(screen.queryByText("No orders today")).not.toBeInTheDocument();
    expect(screen.queryByText(/failed to load orders/i)).not.toBeInTheDocument();
  });

  it("shows error banner with retry on failure and never coexists with empty", () => {
    mockUseOrders.mockReturnValue(
      queryResult({ isError: true, error: new Error("boom"), data: undefined, isPending: false }),
    );
    renderWidget();

    expect(screen.getByRole("alert")).toHaveTextContent(/failed to load orders/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByText("No orders today")).not.toBeInTheDocument();
  });

  it("keeps retained orders visible and identifies them as frozen after a refetch error", () => {
    mockUseOrders.mockReturnValue(
      queryResult({
        data: [OPEN_ORDER],
        isError: true,
        error: new Error("broker offline"),
      }),
    );
    renderWidget();

    expect(screen.getByText("NIFTY24APR24000CE")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/frozen/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows empty copy only after successful empty response (not on pending or error)", () => {
    mockUseOrders.mockReturnValue(queryResult({ isPending: false, isError: false, data: [] }));
    renderWidget();

    expect(screen.getByText("No orders today")).toBeInTheDocument();
  });

  it("displays order rows with symbol, action, and status", () => {
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER, COMPLETE_ORDER] }));
    renderWidget();

    // Symbols
    expect(screen.getByText("NIFTY24APR24000CE")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY24APR51000PE")).toBeInTheDocument();

    // Actions
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();

    // Statuses rendered in Badge components
    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.getByText("complete")).toBeInTheDocument();
  });

  it("sorts decimal order prices and quantities numerically while preserving broker display values", () => {
    mockUseOrders.mockReturnValue(queryResult({
      data: [
        { ...COMPLETE_ORDER, symbol: "HALF", price: "100.5", quantity: "2" },
        { ...COMPLETE_ORDER, symbol: "QUARTER", price: "100.25", quantity: "10" },
        { ...COMPLETE_ORDER, symbol: "MARKET", price: 0, quantity: "5" },
      ],
    }));
    renderWidget();
    const symbols = () => Array.from(screen.getByRole("table").querySelectorAll("tbody tr"))
      .map((row) => row.querySelector("td")?.textContent);

    const priceHeader = screen.getByRole("columnheader", { name: /price/i });
    fireEvent.click(priceHeader);
    expect(symbols()).toEqual(["HALF", "QUARTER", "MARKET"]);
    fireEvent.click(priceHeader);
    expect(symbols()).toEqual(["MARKET", "QUARTER", "HALF"]);
    expect(screen.getByText("100.5")).toBeInTheDocument();
    expect(screen.getByText("100.25")).toBeInTheDocument();
    expect(screen.getByText("MKT")).toBeInTheDocument();

    const quantityHeader = screen.getByRole("columnheader", { name: /qty/i });
    fireEvent.click(quantityHeader);
    expect(symbols()).toEqual(["QUARTER", "MARKET", "HALF"]);
    fireEvent.click(quantityHeader);
    expect(symbols()).toEqual(["HALF", "MARKET", "QUARTER"]);
    expect(mockModifyOrder).not.toHaveBeenCalled();
    expect(mockCancelOrder).not.toHaveBeenCalled();
  });

  it("shows the header with order count", () => {
    mockUseOrders.mockReturnValue(
      queryResult({
        data: [
          { symbol: "NIFTY", action: "BUY", quantity: 50, order_status: "complete" },
        ],
      }),
    );
    renderWidget();

    expect(screen.getByText("Orders (1)")).toBeInTheDocument();
  });

  it("has a refresh button with correct aria-label", () => {
    renderWidget();

    expect(screen.getByLabelText("Refresh orders")).toBeInTheDocument();
  });

  it("does not fetch or refresh orders without a broker connection", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderWidget();

    expect(mockUseOrders).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    expect(screen.getByText("Broker required")).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to load orders")).toBeInTheDocument();
    expect(screen.queryByLabelText("Refresh orders")).not.toBeInTheDocument();
  });

  // ── Per-order Cancel / Modify actions ─────────────────────────────────────

  it("shows Cancel and Modify actions only on open orders", () => {
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER, COMPLETE_ORDER] }));
    renderWidget();

    // Open order has both actions
    expect(screen.getByLabelText("Cancel order ORD123")).toBeInTheDocument();
    expect(screen.getByLabelText("Modify order ORD123")).toBeInTheDocument();

    // Completed order has neither
    expect(screen.queryByLabelText("Cancel order ORD456")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Modify order ORD456")).not.toBeInTheDocument();
  });

  it("cancels an open order with the REAL broker order id after confirmation", async () => {
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();

    fireEvent.click(screen.getByLabelText("Cancel order ORD123"));

    // Confirmation dialog shows the order id; nothing sent yet
    const dialog = screen.getByRole("dialog", { name: /confirm order cancellation/i });
    expect(within(dialog).getByText("ORD123")).toBeInTheDocument();
    expect(mockCancelOrder).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByText("Cancel Order"));

    await waitFor(() => {
      expect(mockCancelOrder).toHaveBeenCalledTimes(1);
      expect(mockCancelOrder).toHaveBeenCalledWith("ORD123", "Flint", {
        mode: "live",
        scopeKey: "live:native:upstox:U1",
        brokerType: "upstox",
        accountId: "U1",
      });
    });
  });

  it("shows Cancellation requested when the cancel is acknowledged but not confirmed", async () => {
    mockCancelOrder.mockResolvedValue({
      status: "success",
      orderid: "ORD123",
      order_outcome: "cancel_requested",
      reason: "awaiting_confirmation",
    });
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();
    fireEvent.click(screen.getByLabelText("Cancel order ORD123"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Cancel Order"));

    expect(await screen.findByRole("status")).toHaveTextContent("Cancellation requested");
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(mockCancelOrder).toHaveBeenCalledTimes(1);
  });

  it("shows Order cancelled only after the order status is confirmed cancelled", async () => {
    mockCancelOrder.mockResolvedValue({
      status: "CANCELLED",
      order_id: "ORD123",
      order_outcome: "cancelled",
      reason: "status_confirmed",
    });
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();
    fireEvent.click(screen.getByLabelText("Cancel order ORD123"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Cancel Order"));

    expect(await screen.findByRole("status")).toHaveTextContent("Order cancelled");
    expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
  });

  it("calls a dropped cancel a cancellation request, never cancelled", async () => {
    mockCancelOrder.mockRejectedValue(Object.assign(new Error("Failed to fetch"), { status: 0 }));
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();
    fireEvent.click(screen.getByLabelText("Cancel order ORD123"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Cancel Order"));

    const outcome = await screen.findByRole("status");
    expect(outcome).toHaveTextContent("Cancellation requested");
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(mockCancelOrder).toHaveBeenCalledTimes(1);
  });

  it("does not cancel when the confirmation is dismissed", () => {
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();

    fireEvent.click(screen.getByLabelText("Cancel order ORD123"));
    fireEvent.click(screen.getByText("Keep Order"));

    expect(mockCancelOrder).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("modifies an open order via the existing modifyOrder API with the real id", async () => {
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();

    fireEvent.click(screen.getByLabelText("Modify order ORD123"));

    const dialog = screen.getByRole("dialog", { name: /modify order/i });
    fireEvent.change(within(dialog).getByLabelText("Quantity"), { target: { value: "150" } });
    fireEvent.change(within(dialog).getByLabelText("Price"), { target: { value: "155.5" } });
    fireEvent.click(within(dialog).getByText("Modify Order"));

    await waitFor(() => {
      expect(mockModifyOrder).toHaveBeenCalledTimes(1);
      expect(mockModifyOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          orderId: "ORD123",
          symbol: "NIFTY24APR24000CE",
          exchange: "NFO",
          action: "BUY",
          quantity: 150,
          orderType: "LIMIT",
          product: "MIS",
          price: 155.5,
          disclosedQuantity: 0,
        }),
        {
          mode: "live",
          scopeKey: "live:native:upstox:U1",
          brokerType: "upstox",
          accountId: "U1",
        },
      );
    });
  });

  it("sends recovered trigger and disclosed quantity when modifying a stop-loss order", async () => {
    mockUseOrders.mockReturnValue(queryResult({
      data: [{
        ...OPEN_ORDER,
        pricetype: "SL",
        triggerPrice: "1490.5",
        disclosedQuantity: "25",
      }],
    }));
    renderWidget();

    fireEvent.click(screen.getByLabelText("Modify order ORD123"));
    const dialog = screen.getByRole("dialog", { name: /modify order/i });
    expect(within(dialog).getByLabelText("Trigger Price")).toHaveValue(1490.5);
    expect(within(dialog).getByLabelText("Disclosed Quantity")).toHaveValue(25);
    fireEvent.click(within(dialog).getByText("Modify Order"));

    await waitFor(() => {
      expect(mockModifyOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          orderId: "ORD123",
          orderType: "SL",
          triggerPrice: 1490.5,
          disclosedQuantity: 25,
        }),
        expect.objectContaining({ mode: "live" }),
      );
    });
  });

  it("disables modify when disclosed quantity is broker-unknown", () => {
    const { disclosedQuantity: _omitted, ...unknownDisclosure } = OPEN_ORDER;
    mockUseOrders.mockReturnValue(queryResult({ data: [unknownDisclosure] }));
    renderWidget();

    expect(screen.getByLabelText("Modify order ORD123")).toBeDisabled();
  });

  it("keeps Modify enabled on Groww when disclosed quantity is omitted", () => {
    mockBrokerType.value = "groww";
    const { disclosedQuantity: _omitted, ...unknownDisclosure } = OPEN_ORDER;
    mockUseOrders.mockReturnValue(queryResult({ data: [unknownDisclosure] }));
    renderWidget();

    expect(screen.getByLabelText("Modify order ORD123")).toBeEnabled();
  });

  it("keeps Modify enabled in Practice when disclosed quantity is omitted", () => {
    mockMode.value = "practice";
    const { disclosedQuantity: _omitted, ...unknownDisclosure } = OPEN_ORDER;
    mockUseOrders.mockReturnValue(queryResult({ data: [unknownDisclosure] }));
    renderWidget();

    expect(screen.getByLabelText("Modify order ORD123")).toBeEnabled();
  });

  it("forwards an explicit zero disclosed quantity instead of keeping the recovered value", async () => {
    mockUseOrders.mockReturnValue(queryResult({
      data: [{
        ...OPEN_ORDER,
        pricetype: "SL",
        triggerPrice: "1490.5",
        disclosedQuantity: "25",
      }],
    }));
    renderWidget();

    fireEvent.click(screen.getByLabelText("Modify order ORD123"));
    const dialog = screen.getByRole("dialog", { name: /modify order/i });
    fireEvent.change(within(dialog).getByLabelText("Disclosed Quantity"), { target: { value: "0" } });
    fireEvent.click(within(dialog).getByText("Modify Order"));

    await waitFor(() => {
      expect(mockModifyOrder).toHaveBeenCalledWith(
        expect.objectContaining({
          orderId: "ORD123",
          disclosedQuantity: 0,
        }),
        expect.objectContaining({ mode: "live" }),
      );
    });
  });

  it("disables modify when a stop-loss order has no recoverable trigger", () => {
    mockUseOrders.mockReturnValue(queryResult({
      data: [{ ...OPEN_ORDER, pricetype: "SL" }],
    }));
    renderWidget();

    expect(screen.getByLabelText("Modify order ORD123")).toBeDisabled();
  });

  it("blocks a LIMIT modify with no price instead of sending ₹0", async () => {
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();

    fireEvent.click(screen.getByLabelText("Modify order ORD123"));
    const dialog = screen.getByRole("dialog", { name: /modify order/i });
    fireEvent.change(within(dialog).getByLabelText("Price"), { target: { value: "" } });
    fireEvent.click(within(dialog).getByText("Modify Order"));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/price above 0/i);
    expect(mockModifyOrder).not.toHaveBeenCalled();
  });

  it("disables actions (fail closed) when the broker sent no order id", () => {
    const noIdOrder = { ...OPEN_ORDER, orderid: undefined };
    mockUseOrders.mockReturnValue(queryResult({ data: [noIdOrder] }));
    renderWidget();

    const cancelBtn = screen.getByLabelText(/^Cancel order/);
    expect(cancelBtn).toBeDisabled();
    fireEvent.click(cancelBtn);
    expect(mockCancelOrder).not.toHaveBeenCalled();
  });

  it("disables actions in explore mode", () => {
    mockMode.value = "explore";
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();

    expect(screen.getByLabelText("Cancel order ORD123")).toBeDisabled();
    expect(screen.getByLabelText("Modify order ORD123")).toBeDisabled();
  });

  it("surfaces a cancel failure to the operator", async () => {
    mockCancelOrder.mockRejectedValue(new Error("Order blocked in practice mode."));
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER] }));
    renderWidget();

    fireEvent.click(screen.getByLabelText("Cancel order ORD123"));
    fireEvent.click(screen.getByText("Cancel Order"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Order blocked in practice mode.");
  });
});

// ---------------------------------------------------------------------------
// Pending cancels: a cancel request is not a cancel
// ---------------------------------------------------------------------------

const OPERATOR = "operator";
const LIVE_SCOPE = "live:upstox:U1";
const pendingKey = (scope: string) =>
  `flinttrade:order-pending-cancels:${encodeURIComponent(OPERATOR)}:${encodeURIComponent(scope)}`;

const SECOND_ORDER = { ...OPEN_ORDER, orderid: "ORD789", symbol: "NIFTY24APR24100CE" };

/** The three ways a cancel reply goes missing after the DELETE was sent. */
const LOST_REPLIES: [string, () => Error][] = [
  ["a dropped connection", () => new TypeError("Failed to fetch")],
  ["a hang that ends in a gateway timeout", () => Object.assign(new Error("Gateway Timeout"), { status: 504, body: null })],
  ["an HTTP 500 after the broker accepted it", () => Object.assign(new Error("Internal Server Error"), { status: 500, body: null })],
];

describe("OrdersWidget pending cancels", () => {
  let client: QueryClient;
  let revision = 0;
  // The widget is memoised. A fresh prop object per render stands in for the
  // query and store updates that re-render it in the app.
  const ui = () => {
    revision += 1;
    const props = { ...defaultProps, revision } as typeof defaultProps;
    return (
      <QueryClientProvider client={client}>
        <OrdersWidget {...props} />
      </QueryClientProvider>
    );
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
    writePersistedAuthSession({ token: "operator-session", username: OPERATOR, expiresAt: "" });
    clearPendingOrderOutcomes();
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    mockMode.value = "live";
    mockBrokerType.value = "";
    mockCancelOrder.mockReset();
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER, SECOND_ORDER], dataUpdatedAt: 1 }));
  });

  afterEach(() => {
    clearPendingOrderOutcomes();
    clearPersistedAuthSession();
    sessionStorage.clear();
  });

  async function cancel(orderId: string) {
    fireEvent.click(screen.getByLabelText(`Cancel order ${orderId}`));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Cancel Order"));
    await waitFor(() => expect(document.querySelector(`[data-pending-cancel="${orderId}"]`)).not.toBeNull());
  }

  function newerRead(data: unknown[]) {
    mockUseOrders.mockReturnValue(queryResult({ data, dataUpdatedAt: Date.now() + 60_000 }));
  }

  it.each(LOST_REPLIES)("shows Cancellation requested after %s, with one DELETE and no Retry", async (_label, lost) => {
    mockCancelOrder.mockRejectedValue(lost());
    render(ui());
    await cancel("ORD123");

    expect(screen.getByRole("status")).toHaveTextContent("Cancellation requested");
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    // The row's own cancel is not offered again while the request is pending.
    expect(screen.getByLabelText("Cancel order ORD123")).toBeDisabled();
    expect(mockCancelOrder).toHaveBeenCalledTimes(1);
  });

  it("shows Order cancelled only after a newer read shows CANCELLED", async () => {
    mockCancelOrder.mockRejectedValue(new TypeError("Failed to fetch"));
    const view = render(ui());
    await cancel("ORD123");

    newerRead([{ ...OPEN_ORDER, order_status: "open" }, SECOND_ORDER]);
    view.rerender(ui());
    expect(screen.getByRole("status")).toHaveTextContent("Cancellation requested");
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();

    newerRead([{ ...OPEN_ORDER, order_status: "cancelled" }, SECOND_ORDER]);
    view.rerender(ui());
    await waitFor(() => expect(document.querySelector('[data-cancelled-order="ORD123"]')).not.toBeNull());
    const cancelled = document.querySelector('[data-cancelled-order="ORD123"]') as HTMLElement;
    expect(cancelled).toHaveTextContent("Order cancelled");
    expect(cancelled.className).not.toMatch(/warning/);
    expect(cancelled.className).not.toMatch(/bg-warning/);
    expect(document.querySelector('[data-pending-cancel="ORD123"]')).toBeNull();
  });

  it("keeps Cancellation requested through a full reload", async () => {
    mockCancelOrder.mockRejectedValue(new TypeError("Failed to fetch"));
    const first = render(ui());
    await cancel("ORD123");
    first.unmount();

    render(ui());
    expect(screen.getByRole("status")).toHaveTextContent("Cancellation requested");
    expect(document.querySelector('[data-pending-cancel="ORD123"]')).not.toBeNull();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(mockCancelOrder).toHaveBeenCalledTimes(1);
  });

  it("confirms only the order the read shows cancelled when two cancels are pending", async () => {
    mockCancelOrder.mockResolvedValue({ status: "success", order_outcome: "cancel_requested" });
    const view = render(ui());
    await cancel("ORD123");
    await cancel("ORD789");

    newerRead([{ ...OPEN_ORDER, order_status: "cancelled" }, SECOND_ORDER]);
    view.rerender(ui());
    await waitFor(() => expect(document.querySelector('[data-cancelled-order="ORD123"]')).not.toBeNull());
    expect(document.querySelector('[data-cancelled-order="ORD789"]')).toBeNull();
    expect(document.querySelector('[data-pending-cancel="ORD789"]')).toHaveTextContent("Cancellation requested");
  });

  it("clears the pending line without Order cancelled when a complete list omits the order", async () => {
    mockCancelOrder.mockRejectedValue(new TypeError("Failed to fetch"));
    const view = render(ui());
    await cancel("ORD123");

    newerRead([SECOND_ORDER]);
    view.rerender(ui());
    await waitFor(() => expect(document.querySelector('[data-pending-cancel="ORD123"]')).toBeNull());
    expect(screen.getByText("No longer in Orders. Check order history.")).toBeInTheDocument();
    expect(document.querySelector('[data-left-order="ORD123"]')).toHaveTextContent("No longer in Orders. Check order history.");
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(pendingKey(LIVE_SCOPE))).toBeNull();
  });

  it("does not settle a pending cancel from a read that failed or is still fetching", async () => {
    mockCancelOrder.mockRejectedValue(new TypeError("Failed to fetch"));
    const view = render(ui());
    await cancel("ORD123");

    mockUseOrders.mockReturnValue(queryResult({ data: [SECOND_ORDER], isFetching: true, dataUpdatedAt: Date.now() + 60_000 }));
    view.rerender(ui());
    expect(document.querySelector('[data-pending-cancel="ORD123"]')).not.toBeNull();
  });

  it("clears the pending line on sign-out", async () => {
    mockCancelOrder.mockRejectedValue(new TypeError("Failed to fetch"));
    render(ui());
    await cancel("ORD123");

    act(() => clearPendingOrderOutcomes());
    expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
    expect(Object.keys(sessionStorage).filter((key) => key.startsWith("flinttrade:order-pending-cancels:"))).toEqual([]);
  });

  it("hides the pending line after a mode switch", async () => {
    mockCancelOrder.mockRejectedValue(new TypeError("Failed to fetch"));
    const view = render(ui());
    await cancel("ORD123");

    mockMode.value = "practice";
    view.rerender(ui());
    expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
  });

  it("hides the pending line after a broker-account switch and shows it again on return", async () => {
    mockCancelOrder.mockRejectedValue(new TypeError("Failed to fetch"));
    const view = render(ui());
    await cancel("ORD123");

    mockBrokerType.value = "dhan";
    view.rerender(ui());
    expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();

    mockBrokerType.value = "";
    view.rerender(ui());
    expect(screen.getByRole("status")).toHaveTextContent("Cancellation requested");
  });

  it("drops a corrupted stored value instead of showing it", () => {
    sessionStorage.setItem(pendingKey(LIVE_SCOPE), "{not json");
    render(ui());
    expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(pendingKey(LIVE_SCOPE))).toBeNull();
  });

  it("lists a lost fast-path submit as unknown until a newer read settles it", async () => {
    await expect(submitOrderOnce(
      LIVE_SCOPE,
      { key: "NFO:NIFTY24APR24000CE", symbol: "NIFTY24APR24000CE", exchange: "NFO", action: "BUY", quantity: 75 },
      () => Promise.reject(new TypeError("Failed to fetch")),
    )).rejects.toThrow();
    const view = render(ui());
    const line = document.querySelector('[data-unknown-submit="NFO:NIFTY24APR24000CE"]');
    expect(line).toHaveTextContent("BUY 75 NIFTY24APR24000CE");
    expect(line).toHaveTextContent("Order status unknown. Check Orders before trying again.");

    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 5_000)); });
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER, SECOND_ORDER], isFetching: true, dataUpdatedAt: 0 }));
    view.rerender(ui());
    await act(async () => {});
    mockUseOrders.mockReturnValue(queryResult({ data: [OPEN_ORDER, SECOND_ORDER], isFetching: false, dataUpdatedAt: Date.now() }));
    view.rerender(ui());
    await waitFor(() => expect(document.querySelector('[data-unknown-submit]')).toBeNull());
  }, 15_000);

  it("shows a confirmed entry and unknown stop-loss on that order", async () => {
    const bracketLost = Object.assign(new Error("Order status unknown. Check Orders before trying again."), {
      status: 502,
      body: { order_outcome: "unknown", leg_outcomes: { entry: "confirmed", stop_loss: "unknown" } },
    });
    await expect(submitOrderOnce(
      LIVE_SCOPE,
      { key: "NFO:NIFTY24APR24000CE", symbol: "NIFTY24APR24000CE", exchange: "NFO", action: "BUY", quantity: 75 },
      () => Promise.reject(bracketLost),
    )).rejects.toBe(bracketLost);
    render(ui());
    const line = document.querySelector('[data-unknown-submit="NFO:NIFTY24APR24000CE"]');
    expect(line).toHaveTextContent("Entry filled · Stop-loss status unknown");
    expect(screen.getByText("Entry filled · Stop-loss status unknown")).toBeInTheDocument();
  });
});

describe("toOrderRow", () => {
  it("preserves camelCase trigger and disclosed-quantity aliases", () => {
    const row = toOrderRow({
      ...OPEN_ORDER,
      pricetype: "SL",
      triggerPrice: "1490.5",
      disclosedQuantity: "25",
    });
    expect(row.triggerPriceNum).toBe(1490.5);
    expect(row.disclosedQuantityNum).toBe(25);
    expect(row.hasDisclosedQuantity).toBe(true);
  });

  it("marks omitted disclosure as unknown instead of a synthesised zero", () => {
    const { disclosedQuantity: _omitted, ...unknownDisclosure } = OPEN_ORDER;
    const row = toOrderRow({ ...unknownDisclosure, pricetype: "LIMIT" });
    expect(row.hasDisclosedQuantity).toBe(false);
  });
});

describe("isOpenOrderStatus", () => {
  it("treats open/pending variants as open", () => {
    expect(isOpenOrderStatus("open")).toBe(true);
    expect(isOpenOrderStatus("OPEN")).toBe(true);
    expect(isOpenOrderStatus("trigger pending")).toBe(true);
    expect(isOpenOrderStatus("Modify Pending")).toBe(true);
    expect(isOpenOrderStatus("validation pending")).toBe(true);
  });

  it("treats terminal statuses as not open", () => {
    expect(isOpenOrderStatus("complete")).toBe(false);
    expect(isOpenOrderStatus("rejected")).toBe(false);
    expect(isOpenOrderStatus("cancelled")).toBe(false);
    expect(isOpenOrderStatus("—")).toBe(false);
  });
});
