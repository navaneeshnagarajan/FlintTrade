/** Real TanStack Query state regressions for OrdersWidget. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

const mockGetOrderbook = vi.hoisted(() => vi.fn());
const brokerState = vi.hoisted(() => ({ connected: false }));

vi.mock("@/services/api", () => ({
  cancelOrder: vi.fn(),
  getOrderbook: mockGetOrderbook,
  modifyOrder: vi.fn(),
}));
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => brokerState.connected,
}));
vi.mock("@/hooks/useDataScope", () => ({
  useDataScope: () => "test:account",
}));
vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useModeStore } from "@/stores/modeStore";
import OrdersWidget from "../OrdersWidget";

function renderWidget() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <OrdersWidget {...makeWidgetPanelProps()} />
    </QueryClientProvider>,
  );
  return { client, ...view };
}

describe("OrdersWidget real query states", () => {
  beforeEach(() => {
    brokerState.connected = false;
    mockGetOrderbook.mockReset();
    useModeStore.setState({ mode: "live" });
  });

  afterEach(() => {
    useModeStore.setState({ mode: "live" });
  });

  it("shows the disconnected state instead of loading for a disabled uncached query", () => {
    renderWidget();

    expect(screen.getByText("Connect a broker to load orders")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading orders")).not.toBeInTheDocument();
    expect(mockGetOrderbook).not.toHaveBeenCalled();
  });

  it("does not show loading in Explore for a disabled uncached query", () => {
    useModeStore.setState({ mode: "explore" });
    renderWidget();

    expect(screen.queryByLabelText("Loading orders")).not.toBeInTheDocument();
    expect(mockGetOrderbook).not.toHaveBeenCalled();
  });

  it("keeps retained rows visible with frozen status after a real-query refetch error", async () => {
    brokerState.connected = true;
    mockGetOrderbook
      .mockResolvedValueOnce([{
        orderid: "ORDER-1",
        symbol: "NIFTY",
        exchange: "NFO",
        action: "BUY",
        quantity: 50,
        price: 100,
        pricetype: "LIMIT",
        product: "MIS",
        order_status: "open",
      }])
      .mockRejectedValueOnce(new Error("broker offline"));
    const { client } = renderWidget();
    expect(await screen.findByText("NIFTY")).toBeInTheDocument();

    await act(async () => {
      await client.refetchQueries({ queryKey: ["orders"] });
    });

    expect(screen.getByText("NIFTY")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(/frozen/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeEnabled();
  });
});
