/**
 * OrdersWidget.test.tsx
 *
 * Tests for the Orders trading widget.
 * Verifies rendering, empty state, order row display, and the per-order
 * Cancel/Modify actions wired to the REAL broker order id.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUseOrders = vi.fn();
const mockUseBrokerConnected = vi.fn();
const mockMode = vi.hoisted(() => ({ value: "live" }));
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
  useAccountReadContext: () => ({
    identity: {
      mode: mockMode.value,
      scopeKey:
        mockMode.value === "explore"
          ? "explore:mock:default"
          : mockMode.value === "practice"
            ? "practice:sandbox:default"
            : "live:openalgo:test",
      brokerType:
        mockMode.value === "explore"
          ? "mock"
          : mockMode.value === "practice"
            ? "sandbox"
            : "openalgo",
      accountId: "default",
    },
    enabled: mockUseBrokerConnected(),
    host: "",
    apiKey: "",
  }),
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
        scopeKey: "live:openalgo:test",
        brokerType: "openalgo",
        accountId: "default",
      });
    });
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
        }),
        {
          mode: "live",
          scopeKey: "live:openalgo:test",
          brokerType: "openalgo",
          accountId: "default",
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
