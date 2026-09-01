/** OrdersWidget query and action-gate regressions with production stores/hooks. */
import { onlineManager } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/services/queryKeys";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import {
  PRIMARY_NATIVE_ACCOUNT,
  PRIMARY_SCOPE,
  SECONDARY_NATIVE_ACCOUNT,
  currentDataScope,
  currentQueryResult,
  forceExactRefetch,
  renderAccountSurface,
  resetAccountRuntime,
  setAccountRuntime,
  setNativeAccountStatus,
} from "@/test-utils/accountQueryHarness";

const mockGetOrderbook = vi.hoisted(() => vi.fn());
const mockCancelOrder = vi.hoisted(() => vi.fn());
const mockModifyOrder = vi.hoisted(() => vi.fn());
const mockListBrokerAccounts = vi.hoisted(() => vi.fn());

vi.mock("@/services/api", () => ({
  cancelOrder: mockCancelOrder,
  getOrderbook: mockGetOrderbook,
  modifyOrder: mockModifyOrder,
}));
vi.mock("@/services/brokerAccountsApi", () => ({
  listBrokerAccounts: mockListBrokerAccounts,
}));

import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import OrdersWidget from "../OrdersWidget";

const ORDERS_KEY = queryKeys.orders.list(PRIMARY_SCOPE);
const SECONDARY_ORDERS_KEY = queryKeys.orders.list("live:native:upstox:B2");
const WIDGET_PROPS = makeWidgetPanelProps();
const ORDER = {
  orderid: "ORDER-1",
  symbol: "NIFTY",
  exchange: "NFO",
  action: "BUY",
  quantity: 50,
  price: 100,
  pricetype: "LIMIT",
  product: "MIS",
  order_status: "open",
  disclosedQuantity: "0",
};

function renderWidget() {
  return renderAccountSurface(() => <OrdersWidget {...WIDGET_PROPS} />);
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("OrdersWidget production query/account state", () => {
  beforeEach(() => {
    mockGetOrderbook.mockReset();
    mockCancelOrder.mockReset();
    mockModifyOrder.mockReset();
    mockListBrokerAccounts.mockReset();
    mockListBrokerAccounts.mockImplementation(async () => useBrokerStore.getState().accounts);
    setAccountRuntime();
    onlineManager.setOnline(true);
  });

  afterEach(() => {
    cleanup();
    onlineManager.setOnline(true);
    resetAccountRuntime();
    vi.restoreAllMocks();
  });

  it("observes the primary account key while disconnected with no cache", () => {
    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");
    const { client } = renderWidget();

    expect(currentDataScope()).toBe(PRIMARY_SCOPE);
    expect(client.getQueryCache().find({ queryKey: ORDERS_KEY, exact: true })).toBeDefined();
    expect(currentQueryResult(client, ORDERS_KEY, false)).toMatchObject({
      status: "pending",
      fetchStatus: "idle",
      isPending: true,
      isLoading: false,
    });
    expect(screen.getByText("Connect a broker to load orders")).toBeInTheDocument();
    expect(mockGetOrderbook).not.toHaveBeenCalled();
  });

  it("shows Explore without starting an account query", () => {
    setAccountRuntime({ mode: "explore", accounts: [] });
    renderWidget();

    expect(screen.queryByLabelText("Loading orders")).not.toBeInTheDocument();
    expect(mockGetOrderbook).not.toHaveBeenCalled();
  });

  it("reports an enabled paused query as offline", () => {
    onlineManager.setOnline(false);
    const { client } = renderWidget();

    expect(currentQueryResult(client, ORDERS_KEY, true)).toMatchObject({
      status: "pending",
      fetchStatus: "paused",
      isPending: true,
      isLoading: false,
      isFetching: false,
    });
    expect(screen.getByText("Orders unavailable while offline")).toBeInTheDocument();
    expect(screen.queryByText("Broker required")).not.toBeInTheDocument();
    expect(mockGetOrderbook).not.toHaveBeenCalled();
  });

  it("retains the primary cache after disconnect without switching to another connected account", async () => {
    setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT] });
    mockGetOrderbook.mockResolvedValueOnce([ORDER]);
    const { client } = renderWidget();
    expect(await screen.findByText("NIFTY")).toBeInTheDocument();

    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");

    await waitFor(() => {
      expect(currentDataScope()).toBe(PRIMARY_SCOPE);
      expect(currentQueryResult(client, ORDERS_KEY, false)).toMatchObject({
        status: "success",
        fetchStatus: "idle",
        data: [ORDER],
      });
    });
    expect(client.getQueryCache().find({ queryKey: SECONDARY_ORDERS_KEY, exact: true })).toBeUndefined();
    expect(screen.getByText("Broker disconnected — displayed orders are frozen")).toBeInTheDocument();
    expect(screen.getByLabelText("Cancel order ORDER-1")).toBeDisabled();
    expect(screen.getByLabelText("Modify order ORDER-1")).toBeDisabled();
    expect(mockGetOrderbook).toHaveBeenCalledTimes(1);
  });

  it("guards retry after a retained error is disconnected", async () => {
    mockGetOrderbook
      .mockResolvedValueOnce([ORDER])
      .mockRejectedValueOnce(new Error("broker offline"));
    const { client } = renderWidget();
    expect(await screen.findByText("NIFTY")).toBeInTheDocument();
    await forceExactRefetch(client, ORDERS_KEY);

    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");

    expect(currentQueryResult(client, ORDERS_KEY, false)).toMatchObject({
      status: "error",
      fetchStatus: "idle",
      data: [ORDER],
    });
    const retry = screen.getByRole<HTMLButtonElement>("button", { name: "Retry" });
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(mockGetOrderbook).toHaveBeenCalledTimes(2);
  });

  it("does not call an initial Orders error frozen", async () => {
    mockGetOrderbook.mockRejectedValueOnce(new Error("initial failure"));
    const { client } = renderWidget();

    const alert = await screen.findByRole("alert");
    expect(currentQueryResult(client, ORDERS_KEY, true)).toMatchObject({
      status: "error",
      fetchStatus: "idle",
      data: undefined,
    });
    expect(alert).not.toHaveTextContent(/frozen/i);
  });

  it("revokes an open Cancel intent when connected account A switches to connected B", async () => {
    setAccountRuntime({
      accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT],
      activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT),
    });
    mockGetOrderbook.mockResolvedValue([ORDER]);
    renderWidget();
    await screen.findByText("NIFTY");
    fireEvent.click(screen.getByLabelText("Cancel order ORDER-1"));
    expect(screen.getByRole("dialog", { name: "Confirm order cancellation" })).toBeInTheDocument();

    act(() => {
      useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) });
    });
    await waitFor(() => expect(currentDataScope()).toBe("live:native:upstox:B2"));

    const staleConfirm = screen.queryByRole<HTMLButtonElement>("button", { name: "Cancel Order" });
    if (staleConfirm) fireEvent.click(staleConfirm);
    expect(
      staleConfirm === null || staleConfirm.disabled,
      "stale Cancel intent must close or disable",
    ).toBe(true);
    expect(mockCancelOrder).not.toHaveBeenCalled();
  });

  it("revokes an open Modify intent when Live changes to Practice", async () => {
    mockGetOrderbook.mockResolvedValue([ORDER]);
    renderWidget();
    await screen.findByText("NIFTY");
    fireEvent.click(screen.getByLabelText("Modify order ORDER-1"));
    expect(screen.getByRole("dialog", { name: "Modify order" })).toBeInTheDocument();

    act(() => {
      useModeStore.setState({ mode: "practice" });
    });
    await waitFor(() => expect(currentDataScope()).toBe("practice:sandbox:default"));

    const staleConfirm = screen.queryByRole<HTMLButtonElement>("button", { name: "Modify Order" });
    if (staleConfirm) fireEvent.click(staleConfirm);
    expect(
      staleConfirm === null || staleConfirm.disabled,
      "stale Modify intent must close or disable",
    ).toBe(true);
    expect(mockModifyOrder).not.toHaveBeenCalled();
  });

  it("does not refetch connected B when an in-flight cancel that began under A completes", async () => {
    setAccountRuntime({
      accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT],
      activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT),
    });
    const pendingCancel = deferred<void>();
    mockGetOrderbook.mockResolvedValue([ORDER]);
    mockCancelOrder.mockReturnValueOnce(pendingCancel.promise);
    const { client } = renderWidget();
    await screen.findByText("NIFTY");
    const invalidate = vi.spyOn(client, "invalidateQueries");

    fireEvent.click(screen.getByLabelText("Cancel order ORDER-1"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel Order" }));
    expect(mockCancelOrder).toHaveBeenCalledTimes(1);

    act(() => {
      useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) });
    });
    await waitFor(() => expect(mockGetOrderbook).toHaveBeenCalledTimes(2));
    await act(async () => {
      pendingCancel.resolve();
      await pendingCancel.promise;
      await Promise.resolve();
    });

    expect(invalidate).not.toHaveBeenCalled();
    expect(mockGetOrderbook).toHaveBeenCalledTimes(2);
  });
});
