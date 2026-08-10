/** PositionsWidget query and action-gate regressions with production stores/hooks. */
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

const mockGetPositionbook = vi.hoisted(() => vi.fn());
const mockPlaceOrder = vi.hoisted(() => vi.fn());
const mockPost = vi.hoisted(() => vi.fn());
const mockDownloadExcel = vi.hoisted(() => vi.fn());
const mockListBrokerAccounts = vi.hoisted(() => vi.fn());

vi.mock("@/services/api", () => ({
  getPositionbook: mockGetPositionbook,
  placeOrder: mockPlaceOrder,
}));
vi.mock("@/services/ftApi.helpers", () => ({
  post: mockPost,
}));
vi.mock("@/services/ftApi.data", () => ({
  downloadExcel: mockDownloadExcel,
}));
vi.mock("@/services/brokerAccountsApi", () => ({
  listBrokerAccounts: mockListBrokerAccounts,
}));

import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import PositionsWidget from "../PositionsWidget";

const POSITIONS_KEY = queryKeys.positions.list(PRIMARY_SCOPE);
const SECONDARY_POSITIONS_KEY = queryKeys.positions.list("live:native:upstox:B2");
const WIDGET_PROPS = makeWidgetPanelProps();
const POSITION = {
  symbol: "RELIANCE",
  exchange: "NSE",
  product: "MIS",
  quantity: 10,
  average_price: 100,
  ltp: 105,
  pnl: 50,
  pnl_percent: 5,
};

function renderWidget() {
  return renderAccountSurface(() => <PositionsWidget {...WIDGET_PROPS} />);
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

describe("PositionsWidget production query/account state", () => {
  beforeEach(() => {
    mockGetPositionbook.mockReset();
    mockPlaceOrder.mockReset();
    mockPost.mockReset();
    mockDownloadExcel.mockReset();
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
    expect(client.getQueryCache().find({ queryKey: POSITIONS_KEY, exact: true })).toBeDefined();
    expect(currentQueryResult(client, POSITIONS_KEY, false)).toMatchObject({
      status: "pending",
      fetchStatus: "idle",
      isPending: true,
      isLoading: false,
    });
    expect(screen.getByText("Connect a broker to load positions")).toBeInTheDocument();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
  });

  it("shows Explore without starting an account query", () => {
    setAccountRuntime({ mode: "explore", accounts: [] });
    renderWidget();

    expect(screen.queryByLabelText("Loading positions")).not.toBeInTheDocument();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
  });

  it("reports an enabled paused query as offline without broker-session copy", () => {
    onlineManager.setOnline(false);
    const { client } = renderWidget();

    expect(currentQueryResult(client, POSITIONS_KEY, true)).toMatchObject({
      status: "pending",
      fetchStatus: "paused",
      isPending: true,
      isLoading: false,
      isFetching: false,
    });
    expect(screen.getByText("Positions unavailable while offline")).toBeInTheDocument();
    expect(screen.queryByText(/connect a broker/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/broker session/i)).not.toBeInTheDocument();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
  });

  it("retains the primary cache after disconnect without switching to another connected account", async () => {
    setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT] });
    mockGetPositionbook.mockResolvedValueOnce([POSITION]);
    const { client } = renderWidget();
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();

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
    expect(screen.getByText("Broker disconnected — displayed positions are frozen")).toBeInTheDocument();
    expect(screen.queryByLabelText("Square off RELIANCE")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Convert RELIANCE")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Exit all positions")).not.toBeInTheDocument();
    expect(mockGetPositionbook).toHaveBeenCalledTimes(1);
  });

  it("guards retry after a retained error is disconnected", async () => {
    mockGetPositionbook
      .mockResolvedValueOnce([POSITION])
      .mockRejectedValueOnce(new Error("broker offline"));
    const { client } = renderWidget();
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();
    await forceExactRefetch(client, POSITIONS_KEY);

    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");

    expect(currentQueryResult(client, POSITIONS_KEY, false)).toMatchObject({
      status: "error",
      fetchStatus: "idle",
      data: [POSITION],
    });
    const retry = screen.getByRole<HTMLButtonElement>("button", { name: "Retry" });
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(mockGetPositionbook).toHaveBeenCalledTimes(2);
  });

  it("initial no-data error never claims figures are frozen", async () => {
    mockGetPositionbook.mockRejectedValueOnce(new Error("initial failure"));
    const { client } = renderWidget();

    const alert = await screen.findByRole("alert");
    expect(currentQueryResult(client, POSITIONS_KEY, true)).toMatchObject({
      status: "error",
      fetchStatus: "idle",
      data: undefined,
    });
    expect(alert).not.toHaveTextContent(/frozen/i);
  });

  it("revokes an open Convert intent when connected account A switches to connected B", async () => {
    setAccountRuntime({
      accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT],
      activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT),
    });
    mockGetPositionbook.mockResolvedValue([POSITION]);
    renderWidget();
    await screen.findByText("RELIANCE");
    fireEvent.click(screen.getByLabelText("Convert RELIANCE"));
    expect(screen.getByRole("dialog", { name: "Convert position" })).toBeInTheDocument();

    act(() => {
      useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) });
    });
    await waitFor(() => expect(currentDataScope()).toBe("live:native:upstox:B2"));

    const staleConfirm = screen.queryByRole<HTMLButtonElement>("button", { name: "Convert RELIANCE to CNC" });
    if (staleConfirm) fireEvent.click(staleConfirm);
    expect(
      staleConfirm === null || staleConfirm.disabled,
      "stale Convert intent must close or disable",
    ).toBe(true);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("closes or disables an open Convert intent when Live changes to Practice", async () => {
    mockGetPositionbook.mockResolvedValue([POSITION]);
    renderWidget();
    await screen.findByText("RELIANCE");
    fireEvent.click(screen.getByLabelText("Convert RELIANCE"));

    act(() => {
      useModeStore.setState({ mode: "practice" });
    });
    await waitFor(() => expect(currentDataScope()).toBe("practice:sandbox:default"));

    const staleConfirm = screen.queryByRole<HTMLButtonElement>("button", { name: "Convert RELIANCE to CNC" });
    if (staleConfirm) fireEvent.click(staleConfirm);
    expect(staleConfirm === null || staleConfirm.disabled).toBe(true);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("revokes an open Square-off intent when connected account A switches to connected B", async () => {
    setAccountRuntime({
      accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT],
      activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT),
    });
    mockGetPositionbook.mockResolvedValue([POSITION]);
    renderWidget();
    await screen.findByText("RELIANCE");
    fireEvent.click(screen.getByLabelText("Square off RELIANCE"));
    expect(screen.getByRole("dialog", { name: "Square off position?" })).toBeInTheDocument();

    act(() => {
      useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) });
    });
    await waitFor(() => expect(currentDataScope()).toBe("live:native:upstox:B2"));

    const staleConfirm = screen.queryByRole<HTMLButtonElement>("button", { name: "Confirm square off RELIANCE" });
    if (staleConfirm) fireEvent.click(staleConfirm);
    expect(
      staleConfirm === null || staleConfirm.disabled,
      "stale Square-off intent must close or disable",
    ).toBe(true);
    expect(mockPlaceOrder).not.toHaveBeenCalled();
  });

  it("revokes an open Exit-all intent when connected account A switches to connected B", async () => {
    setAccountRuntime({
      accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT],
      activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT),
    });
    mockGetPositionbook.mockResolvedValue([POSITION]);
    renderWidget();
    await screen.findByText("RELIANCE");
    fireEvent.click(screen.getByLabelText("Exit all positions"));
    fireEvent.change(screen.getByLabelText("Type EXIT (in capitals) to confirm"), {
      target: { value: "EXIT" },
    });
    expect(screen.getByRole("dialog", { name: "Exit all positions?" })).toBeInTheDocument();

    act(() => {
      useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) });
    });
    await waitFor(() => expect(currentDataScope()).toBe("live:native:upstox:B2"));

    const staleConfirm = screen.queryByRole<HTMLButtonElement>("button", { name: "Confirm exit all positions" });
    if (staleConfirm) fireEvent.click(staleConfirm);
    expect(
      staleConfirm === null || staleConfirm.disabled,
      "stale Exit-all intent must close or disable",
    ).toBe(true);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("does not refetch connected B when an in-flight conversion that began under A completes", async () => {
    setAccountRuntime({
      accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT],
      activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT),
    });
    const pendingConvert = deferred<void>();
    mockGetPositionbook.mockResolvedValue([POSITION]);
    mockPost.mockReturnValueOnce(pendingConvert.promise);
    renderWidget();
    await screen.findByText("RELIANCE");

    fireEvent.click(screen.getByLabelText("Convert RELIANCE"));
    fireEvent.click(screen.getByRole("button", { name: "Convert RELIANCE to CNC" }));
    expect(mockPost).toHaveBeenCalledTimes(1);

    act(() => {
      useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) });
    });
    await waitFor(() => expect(mockGetPositionbook).toHaveBeenCalledTimes(2));
    await act(async () => {
      pendingConvert.resolve();
      await pendingConvert.promise;
      await Promise.resolve();
    });

    expect(mockGetPositionbook).toHaveBeenCalledTimes(2);
  });
});
