/** Actual stores, account/query hooks, API decoding and native write guards. */
import { onlineManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { queryKeys } from "@/services/queryKeys";
import {
  PRIMARY_NATIVE_ACCOUNT,
  PRIMARY_SCOPE,
  SECONDARY_NATIVE_ACCOUNT,
  forceExactRefetch,
  renderAccountSurface,
  resetAccountRuntime,
  setAccountRuntime,
  setNativeAccountStatus,
} from "@/test-utils/accountQueryHarness";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import PositionsWidget from "../PositionsWidget";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

const POSITION = {
  symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: 10,
  average_price: 100, ltp: 105, pnl: 50, pnl_percent: 5,
};
const POSITION_URL_A = "/ft-api/api/v1/native/accounts/dhan/A1/positions";
const ORDER_URL_A = "/ft-api/api/v1/native/accounts/dhan/A1/orders";
const POSITION_URL_B = "/ft-api/api/v1/native/accounts/upstox/B2/positions";
const ORDER_URL_B = "/ft-api/api/v1/native/accounts/upstox/B2/orders";
const ORDER_KEY_A = queryKeys.orders.list(PRIMARY_SCOPE);
const WARNING = "This prioritises execution. The fill price may differ significantly, and execution isn't guaranteed.";
const props = makeWidgetPanelProps();
const originalSignals = useOperatorSignalStore.getState();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

let respond: (url: string, init: RequestInit) => Response | Promise<Response>;
const unexpected: string[] = [];
const notifications: Array<Record<string, unknown>> = [];
const captureNotification = (event: Event) => notifications.push((event as CustomEvent<Record<string, unknown>>).detail);
const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
  try {
    return Promise.resolve(respond(String(input), init));
  } catch (error) {
    // Product network-error handling must not hide a stub assertion failure.
    unexpected.push(`${init.method ?? "GET"} ${String(input)}: ${String(error)}`);
    return Promise.reject(error);
  }
});
function refuseUnexpected(url: string, init: RequestInit): never {
  const call = `${init.method ?? "GET"} ${url}`;
  unexpected.push(call);
  throw new Error(`Unregistered synthetic request: ${call}`);
}
function isGet(init: RequestInit = {}) { return (init.method ?? "GET") === "GET"; }
function renderWidget() { return renderAccountSurface(() => <PositionsWidget {...props} />); }
function countReads(url: string) { return fetchMock.mock.calls.filter(([input, init]) => isGet(init) && String(input) === url).length; }
function assertExitsUnavailable() {
  expect(screen.getByTestId("exit-orders-unavailable")).toBeInTheDocument();
  expect(screen.queryByLabelText("Square off RELIANCE")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Exit all positions")).not.toBeInTheDocument();
}

beforeEach(() => {
  unexpected.length = 0;
  notifications.length = 0;
  fetchMock.mockClear();
  setAccountRuntime({ activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
  onlineManager.setOnline(true);
  useOperatorSignalStore.setState({ ...originalSignals, decisionStatus: "ready", layaPracticeStatus: "ready" });
  respond = (url, init) => {
    if (isGet(init) && url === POSITION_URL_A) return jsonResponse({ status: "success", data: [POSITION] });
    if (isGet(init) && url === ORDER_URL_A) return jsonResponse({ status: "success", data: [] });
    return refuseUnexpected(url, init);
  };
  vi.stubGlobal("fetch", fetchMock);
  window.addEventListener("flinttrade:notify", captureNotification);
});

afterEach(() => {
  cleanup();
  window.removeEventListener("flinttrade:notify", captureNotification);
  onlineManager.setOnline(true);
  resetAccountRuntime();
  useOperatorSignalStore.setState(originalSignals);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  expect(unexpected).toEqual([]);
});

describe("Positions real order-book availability", () => {
  it("keeps a delayed actual order read unavailable, then enables exits only for a successful empty book", async () => {
    const orders = deferred<Response>();
    respond = (url, init) => {
      if (isGet(init) && url === POSITION_URL_A) return jsonResponse({ status: "success", data: [POSITION] });
      if (isGet(init) && url === ORDER_URL_A) return orders.promise;
      return refuseUnexpected(url, init);
    };
    renderWidget();
    await screen.findByText("RELIANCE");
    assertExitsUnavailable();
    await act(async () => { orders.resolve(jsonResponse({ status: "success", data: [] })); });
    expect(await screen.findByLabelText("Square off RELIANCE")).toBeEnabled();
    expect(screen.getByLabelText("Exit all positions")).toBeEnabled();
    expect(screen.queryByTestId("exit-orders-unavailable")).not.toBeInTheDocument();
    expect(countReads(ORDER_URL_A)).toBe(1);
    expect(countReads(POSITION_URL_A)).toBe(1);
  });

  it.each([
    { name: "read cutover", response: () => jsonResponse({ status: "error", message: "Native broker HTTP reads are unavailable until the read cutover" }, 409), detail: /Native broker HTTP reads are unavailable until the read cutover/ },
    { name: "unsupported", response: () => jsonResponse({ status: "error", message: "Orders are not available for this adapter" }, 501), detail: /Orders are not available for this adapter/ },
    { name: "invalid JSON", response: () => new Response("{invalid-json", { status: 200 }), detail: /JSON/i },
    { name: "missing book", response: () => jsonResponse({ status: "success", data: null }), detail: /null/i },
  ])("retains positions and unavailable controls for an actual $name response", async ({ response, detail }) => {
    respond = (url, init) => {
      if (isGet(init) && url === POSITION_URL_A) return jsonResponse({ status: "success", data: [POSITION] });
      if (isGet(init) && url === ORDER_URL_A) return response();
      return refuseUnexpected(url, init);
    };
    renderWidget();
    await screen.findByText("RELIANCE");
    await waitFor(() => expect(screen.getByTestId("exit-orders-unavailable")).toHaveTextContent(detail));
    assertExitsUnavailable();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(countReads(ORDER_URL_A)).toBe(1);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  });

  it("keeps cached exit evidence visible but unavailable after a real failed order refetch", async () => {
    const order = { orderid: "EXIT-A", symbol: "RELIANCE", exchange: "NSE", product: "MIS", action: "SELL", status: "CANCEL_PENDING" };
    let unavailable = false;
    respond = (url, init) => {
      if (isGet(init) && url === POSITION_URL_A) return jsonResponse({ status: "success", data: [POSITION] });
      if (isGet(init) && url === ORDER_URL_A) return unavailable
        ? jsonResponse({ status: "error", message: "A order book unavailable" }, 503)
        : jsonResponse({ status: "success", data: [order] });
      return refuseUnexpected(url, init);
    };
    const { client } = renderWidget();
    expect(await screen.findByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
    expect(screen.getByLabelText("Square off RELIANCE")).toBeDisabled();
    unavailable = true;
    await forceExactRefetch(client, ORDER_KEY_A);
    await waitFor(() => expect(screen.getByTestId("exit-orders-unavailable")).toHaveTextContent("A order book unavailable"));
    assertExitsUnavailable();
    expect(screen.getByText("Cancel pending. This order may still fill.")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(countReads(ORDER_URL_A)).toBe(2);
  });

  it.each([{}, { orders: null }, { orders: "unreadable" }])(
    "does not treat a malformed successful ordinary order book as verified empty: %j", async (data) => {
      respond = (url, init) => {
        if (isGet(init) && url === POSITION_URL_A) return jsonResponse({ status: "success", data: [POSITION] });
        if (isGet(init) && url === ORDER_URL_A) return jsonResponse({ status: "success", data });
        return refuseUnexpected(url, init);
      };
      const { client } = renderWidget();
      await screen.findByText("RELIANCE");
      await waitFor(() => expect(client.getQueryState(ORDER_KEY_A)?.fetchStatus).toBe("idle"));
      assertExitsUnavailable();
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
    },
  );

  it("keeps a real paused order refetch unavailable even with a successful cached empty book", async () => {
    const { client } = renderWidget();
    await screen.findByLabelText("Square off RELIANCE");
    act(() => { onlineManager.setOnline(false); });
    let pausedRefetch!: Promise<void>;
    act(() => { pausedRefetch = client.refetchQueries({ queryKey: ORDER_KEY_A, exact: true }); });
    await waitFor(() => expect(client.getQueryState(ORDER_KEY_A)?.fetchStatus).toBe("paused"));
    assertExitsUnavailable();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(countReads(ORDER_URL_A)).toBe(1);
    await act(async () => { onlineManager.setOnline(true); await pausedRefetch; });
    await screen.findByLabelText("Square off RELIANCE");
    expect(screen.queryByTestId("exit-orders-unavailable")).not.toBeInTheDocument();
  });

  it("revokes exits after the actual selected native account disconnects", async () => {
    renderWidget();
    await screen.findByLabelText("Square off RELIANCE");
    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");
    await waitFor(() => expect(screen.queryByLabelText("Square off RELIANCE")).not.toBeInTheDocument());
    assertExitsUnavailable();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(countReads(ORDER_URL_A)).toBe(1);
  });
});

function openExit(operation: "square-off" | "exit-all") {
  if (operation === "square-off") {
    fireEvent.click(screen.getByLabelText("Square off RELIANCE"));
  } else {
    fireEvent.click(screen.getByLabelText("Exit all positions"));
    fireEvent.change(screen.getByLabelText("Type EXIT (in capitals) to confirm"), { target: { value: "EXIT" } });
  }
}
function confirmExit(operation: "square-off" | "exit-all") {
  fireEvent.click(screen.getByLabelText(operation === "square-off" ? "Confirm square off RELIANCE" : "Confirm exit all positions"));
}

function verifyExitRequest(operation: "square-off" | "exit-all", url: string, init: RequestInit): boolean {
  const expectedUrl = operation === "square-off" ? "/ft-api/api/v1/orders/dhan/place" : "/ft-api/api/v1/positions/exit-all";
  if (init.method !== "POST" || url !== expectedUrl) return false;
  expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("live");
  const body = JSON.parse(String(init.body)) as Record<string, unknown>;
  expect(body).toMatchObject({ broker: "dhan", account_id: "A1" });
  if (operation === "square-off") {
    expect(body).toMatchObject({ symbol: "RELIANCE", exchange: "NSE", action: "SELL", quantity: 10, product: "MIS", order_type: "MARKET", price: 0, trigger_price: 0 });
  } else {
    expect(body).toEqual({ confirm: true, broker: "dhan", account_id: "A1" });
  }
  return true;
}

describe.each(["square-off", "exit-all"] as const)("Positions real-hook %s outcomes", (operation) => {
  it.each(["ACK", "unknown error"] as const)("isolates a late A %s from B's dialog, notifications and refetches", async (outcome) => {
    setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT], activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
    const request = deferred<Response>();
    respond = (url, init) => {
      if (isGet(init) && (url === POSITION_URL_A || url === POSITION_URL_B)) return jsonResponse({ status: "success", data: [POSITION] });
      if (isGet(init) && (url === ORDER_URL_A || url === ORDER_URL_B)) return jsonResponse({ status: "success", data: [] });
      if (verifyExitRequest(operation, url, init)) return request.promise;
      return refuseUnexpected(url, init);
    };
    renderWidget();
    await screen.findByLabelText("Square off RELIANCE");
    openExit(operation);
    expect(screen.getByText(WARNING)).toBeInTheDocument();
    confirmExit(operation);
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1));
    act(() => { useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) }); });
    await waitFor(() => expect(countReads(POSITION_URL_B)).toBe(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await screen.findByLabelText("Square off RELIANCE");
    openExit(operation);
    const dialogName = operation === "square-off" ? "Square off position?" : "Exit all positions?";
    expect(screen.getByRole("dialog", { name: dialogName })).toBeInTheDocument();
    await act(async () => {
      request.resolve(outcome === "ACK"
        ? jsonResponse({ status: "success", data: { orderId: "ACK-A" } })
        : jsonResponse({ status: "error", message: "A exit response timed out" }, 504));
    });
    expect(screen.getByRole("dialog", { name: dialogName })).toBeInTheDocument();
    expect(screen.queryByText(/A exit response timed out|Exit status unknown/)).not.toBeInTheDocument();
    expect(notifications).toEqual([]);
    expect(countReads(POSITION_URL_B)).toBe(1);
    expect(countReads(ORDER_URL_B)).toBe(1);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("treats the real successful response as an ACK, not a filled or closed position", async () => {
    respond = (url, init) => {
      if (isGet(init) && url === POSITION_URL_A) return jsonResponse({ status: "success", data: [POSITION] });
      if (isGet(init) && url === ORDER_URL_A) return jsonResponse({ status: "success", data: [] });
      if (verifyExitRequest(operation, url, init)) return jsonResponse({ status: "success", data: { orderId: "ACK-A" } });
      return refuseUnexpected(url, init);
    };
    renderWidget();
    await screen.findByLabelText("Square off RELIANCE");
    openExit(operation);
    expect(screen.getByText(WARNING)).toBeInTheDocument();
    confirmExit(operation);
    await waitFor(() => expect(notifications).toHaveLength(1));
    expect(notifications[0].body).toBe(operation === "square-off"
      ? "Exit requested: SELL 10 RELIANCE at market. Check positions and orders for the outcome."
      : "Exit-all requested. Check positions and orders for the outcome.");
    expect(JSON.stringify(notifications)).not.toMatch(/Every open position was squared off|\bCLOSED\b|\bfilled\b/i);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(countReads(POSITION_URL_A)).toBe(2);
  });
});
