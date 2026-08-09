/**
 * Real-store and real-TanStack regressions for the Orders/Positions home cards.
 * Only account transports are mocked; mode, broker, connection, provenance,
 * account-read gating, hooks, and query keys are production implementations.
 */
import { onlineManager } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/services/queryKeys";
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
const mockGetPositionbook = vi.hoisted(() => vi.fn());
const mockListBrokerAccounts = vi.hoisted(() => vi.fn());

vi.mock("@/services/api", () => ({
  getOrderbook: mockGetOrderbook,
  getPositionbook: mockGetPositionbook,
}));
vi.mock("@/services/brokerAccountsApi", () => ({
  listBrokerAccounts: mockListBrokerAccounts,
}));

import { useBrokerStore } from "@/stores/brokerStore";
import { useTradingStore } from "@/stores/tradingStore";
import { OrdersCard } from "../OrdersCard";
import { PositionsCard } from "../PositionsCard";

const ORDERS_KEY = queryKeys.orders.list(PRIMARY_SCOPE);
const POSITIONS_KEY = queryKeys.positions.list(PRIMARY_SCOPE);
const SECONDARY_ORDERS_KEY = queryKeys.orders.list("live:native:upstox:B2");
const SECONDARY_POSITIONS_KEY = queryKeys.positions.list("live:native:upstox:B2");

const ORDER = {
  orderId: "ORDER-1",
  symbol: "NIFTY",
  exchange: "NFO",
  action: "BUY" as const,
  quantity: 50,
  price: 100,
  orderType: "LIMIT",
  status: "COMPLETE",
  product: "MIS",
  strategy: "Flint",
  timestamp: "2026-08-09T09:15:00Z",
};

const POSITION = {
  symbol: "RELIANCE",
  exchange: "NSE",
  product: "MIS",
  quantity: 10,
  averagePrice: 100,
  ltp: 105,
  pnl: 50,
  pnlPercent: 5,
};

describe("account query card states with production stores and provenance", () => {
  beforeEach(() => {
    mockGetOrderbook.mockReset();
    mockGetPositionbook.mockReset();
    mockListBrokerAccounts.mockReset();
    mockListBrokerAccounts.mockImplementation(async () => useBrokerStore.getState().accounts);
    setAccountRuntime();
    useTradingStore.setState({ totalPnl: 500 });
    onlineManager.setOnline(true);
  });

  afterEach(() => {
    cleanup();
    onlineManager.setOnline(true);
    resetAccountRuntime();
    useTradingStore.setState({ totalPnl: 0 });
  });

  it("OrdersCard observes the primary account key while disconnected with no cache", () => {
    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");
    const { client } = renderAccountSurface(() => <OrdersCard />);

    expect(currentDataScope()).toBe(PRIMARY_SCOPE);
    expect(client.getQueryCache().find({ queryKey: ORDERS_KEY, exact: true })).toBeDefined();
    expect(currentQueryResult(client, ORDERS_KEY, false)).toMatchObject({
      status: "pending",
      fetchStatus: "idle",
      isPending: true,
      isLoading: false,
    });
    expect(screen.getByText("Connect a broker to load orders")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading orders")).not.toBeInTheDocument();
    expect(mockGetOrderbook).not.toHaveBeenCalled();
  });

  it("PositionsCard observes the primary account key while disconnected with no cache", () => {
    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");
    const { client } = renderAccountSurface(() => <PositionsCard />);

    expect(currentDataScope()).toBe(PRIMARY_SCOPE);
    expect(client.getQueryCache().find({ queryKey: POSITIONS_KEY, exact: true })).toBeDefined();
    expect(currentQueryResult(client, POSITIONS_KEY, false)).toMatchObject({
      status: "pending",
      fetchStatus: "idle",
      isPending: true,
      isLoading: false,
    });
    expect(screen.getByText("Connect a broker to load positions")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading positions")).not.toBeInTheDocument();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
  });

  it("OrdersCard reports an enabled paused query as offline", () => {
    onlineManager.setOnline(false);
    const { client } = renderAccountSurface(() => <OrdersCard />);

    expect(currentQueryResult(client, ORDERS_KEY, true)).toMatchObject({
      status: "pending",
      fetchStatus: "paused",
      isPending: true,
      isLoading: false,
      isFetching: false,
    });
    expect(screen.getByText("Orders unavailable while offline")).toBeInTheDocument();
    expect(screen.queryByText(/connect a broker/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Loading orders")).not.toBeInTheDocument();
    expect(mockGetOrderbook).not.toHaveBeenCalled();
  });

  it("PositionsCard reports an enabled paused query as offline", () => {
    onlineManager.setOnline(false);
    const { client } = renderAccountSurface(() => <PositionsCard />);

    expect(currentQueryResult(client, POSITIONS_KEY, true)).toMatchObject({
      status: "pending",
      fetchStatus: "paused",
      isPending: true,
      isLoading: false,
      isFetching: false,
    });
    expect(screen.getByText("Positions unavailable while offline")).toBeInTheDocument();
    expect(screen.queryByText(/connect a broker/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Loading positions")).not.toBeInTheDocument();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
  });

  it("OrdersCard retains only the primary cache when that account disconnects while another stays connected", async () => {
    setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT] });
    mockGetOrderbook.mockResolvedValueOnce([ORDER]);
    const { client } = renderAccountSurface(() => <OrdersCard />);
    expect(await screen.findByText("NIFTY")).toBeInTheDocument();
    expect(client.getQueryData(ORDERS_KEY)).toEqual([ORDER]);

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
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Broker disconnected — displayed orders are frozen",
    );
    expect(mockGetOrderbook).toHaveBeenCalledTimes(1);
  });

  it("PositionsCard retains only the primary cache when that account disconnects while another stays connected", async () => {
    setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT] });
    mockGetPositionbook.mockResolvedValueOnce([POSITION]);
    const { client } = renderAccountSurface(() => <PositionsCard />);
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();
    expect(client.getQueryData(POSITIONS_KEY)).toEqual([POSITION]);

    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");

    await waitFor(() => {
      expect(currentDataScope()).toBe(PRIMARY_SCOPE);
      expect(currentQueryResult(client, POSITIONS_KEY, false)).toMatchObject({
        status: "success",
        fetchStatus: "idle",
        data: [POSITION],
      });
    });
    expect(client.getQueryCache().find({ queryKey: SECONDARY_POSITIONS_KEY, exact: true })).toBeUndefined();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Broker disconnected — displayed positions are frozen",
    );
    expect(mockGetPositionbook).toHaveBeenCalledTimes(1);
  });

  it("OrdersCard guards retry after a retained error is disconnected", async () => {
    mockGetOrderbook
      .mockResolvedValueOnce([ORDER])
      .mockRejectedValueOnce(new Error("broker offline"));
    const { client } = renderAccountSurface(() => <OrdersCard />);
    expect(await screen.findByText("NIFTY")).toBeInTheDocument();
    await forceExactRefetch(client, ORDERS_KEY);

    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");

    expect(currentQueryResult(client, ORDERS_KEY, false)).toMatchObject({
      status: "error",
      fetchStatus: "idle",
      data: [ORDER],
    });
    const retry = screen.getByRole<HTMLButtonElement>("button", { name: "Retry orders" });
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(mockGetOrderbook).toHaveBeenCalledTimes(2);
  });

  it("PositionsCard guards retry after a retained error is disconnected", async () => {
    mockGetPositionbook
      .mockResolvedValueOnce([POSITION])
      .mockRejectedValueOnce(new Error("broker offline"));
    const { client } = renderAccountSurface(() => <PositionsCard />);
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();
    await forceExactRefetch(client, POSITIONS_KEY);

    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");

    expect(currentQueryResult(client, POSITIONS_KEY, false)).toMatchObject({
      status: "error",
      fetchStatus: "idle",
      data: [POSITION],
    });
    const retry = screen.getByRole<HTMLButtonElement>("button", { name: "Retry positions" });
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(mockGetPositionbook).toHaveBeenCalledTimes(2);
  });

  it("PositionsCard initial no-data error never claims figures are frozen", async () => {
    mockGetPositionbook.mockRejectedValueOnce(new Error("initial failure"));
    const { client } = renderAccountSurface(() => <PositionsCard />);

    const alert = await screen.findByRole("alert");
    expect(currentQueryResult(client, POSITIONS_KEY, true)).toMatchObject({
      status: "error",
      fetchStatus: "idle",
      data: undefined,
    });
    expect(alert).toHaveTextContent(/positions unavailable/i);
    expect(alert).not.toHaveTextContent(/frozen/i);
    expect(screen.getByRole("button", { name: "Retry positions" })).toBeEnabled();
  });
});
