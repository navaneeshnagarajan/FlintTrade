/** OrdersWidget-to-api regression for the pre-commit account-switch race. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

const DISPLAYED_IDENTITY = vi.hoisted(() => Object.freeze({
  mode: "live" as const,
  scopeKey: "live:native:dhan:ACCOUNT-A",
  brokerType: "dhan",
  accountId: "ACCOUNT-A",
}));

const mockUseOrders = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useOrders", () => ({
  useOrders: (...args: unknown[]) => mockUseOrders(...args),
}));
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadContext: () => ({
    identity: DISPLAYED_IDENTITY,
    enabled: true,
    host: "",
    apiKey: "",
  }),
}));
vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";
import OrdersWidget from "../OrdersWidget";

const ACCOUNT_A: BrokerAccount = {
  account_id: "ACCOUNT-A",
  broker: "dhan",
  label: "Account A",
  status: "connected",
  connected_at: null,
  error_message: null,
  is_primary: true,
  source: "native",
};
const ACCOUNT_B: BrokerAccount = {
  account_id: "ACCOUNT-B",
  broker: "upstox",
  label: "Account B",
  status: "connected",
  connected_at: null,
  error_message: null,
  is_primary: false,
  source: "native",
};
const ORDER = {
  orderid: "A-ORDER",
  symbol: "RELIANCE",
  exchange: "NSE",
  action: "BUY",
  quantity: 1,
  price: 100,
  pricetype: "LIMIT",
  product: "MIS",
  order_status: "open",
  disclosedQuantity: "0",
};

function renderWidget(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <OrdersWidget {...makeWidgetPanelProps()} />
    </QueryClientProvider>,
  );
}

function switchImperativeStoresToAccountB(): void {
  // Deliberately do not change the mocked rendered identity. This models the
  // narrow interval after Zustand changes but before React commits the new
  // useAccountReadContext value/ref.
  useBrokerStore.setState({ activeAccountId: brokerAccountKey(ACCOUNT_B) });
}

describe("OrdersWidget exact mutation authority", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "live" });
    useConnectionStore.setState({
      host: "",
      apiKey: "",
      status: "disconnected",
      openAlgoHydrated: true,
    });
    useBrokerStore.setState({
      accounts: [ACCOUNT_A, ACCOUNT_B],
      activeAccountId: brokerAccountKey(ACCOUNT_A),
    });
    mockUseOrders.mockReturnValue({
      data: [ORDER],
      refetch: vi.fn(),
      isFetching: false,
      isError: false,
      error: null,
      isLoading: false,
      isPending: false,
      fetchStatus: "idle",
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "success", data: { orderId: "WRONG-ACCOUNT" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
    useModeStore.setState({ mode: "explore" });
  });

  it("routes a valid account-A cancel through its exact broker and account", async () => {
    renderWidget();
    fireEvent.click(screen.getByLabelText("Cancel order A-ORDER"));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Confirm order cancellation" }))
        .getByRole("button", { name: "Cancel Order" }),
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/dhan/cancel");
    expect(JSON.parse(String(init.body))).toMatchObject({
      orderId: "A-ORDER",
      strategy: "Flint",
      broker: "dhan",
      account_id: "ACCOUNT-A",
    });
  });

  it("routes a valid account-A modify through its exact broker and account", async () => {
    renderWidget();
    fireEvent.click(screen.getByLabelText("Modify order A-ORDER"));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Modify order" }))
        .getByRole("button", { name: "Modify Order" }),
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/dhan/modify");
    expect(JSON.parse(String(init.body))).toMatchObject({
      orderId: "A-ORDER",
      broker: "dhan",
      account_id: "ACCOUNT-A",
    });
  });

  it("refuses cancel when imperative stores switch from displayed account A to B before confirmation", async () => {
    renderWidget();
    fireEvent.click(screen.getByLabelText("Cancel order A-ORDER"));
    const dialog = screen.getByRole("dialog", { name: "Confirm order cancellation" });

    switchImperativeStoresToAccountB();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel Order" }));

    expect(fetch).not.toHaveBeenCalled();
  });

  it("refuses modify when imperative stores switch from displayed account A to B before confirmation", async () => {
    renderWidget();
    fireEvent.click(screen.getByLabelText("Modify order A-ORDER"));
    const dialog = screen.getByRole("dialog", { name: "Modify order" });

    switchImperativeStoresToAccountB();
    fireEvent.click(within(dialog).getByRole("button", { name: "Modify Order" }));

    expect(fetch).not.toHaveBeenCalled();
  });
});
