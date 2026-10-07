/** Real stores, query hooks and fetch decoding; synthetic responses only. */
import { onlineManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { brokerOrderKeys } from "@/lib/brokerOrdersApi";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import {
  PRIMARY_NATIVE_ACCOUNT,
  SECONDARY_NATIVE_ACCOUNT,
  renderAccountSurface,
  resetAccountRuntime,
  setAccountRuntime,
  setNativeAccountStatus,
} from "@/test-utils/accountQueryHarness";
import ForeverOrdersWidget from "./ForeverOrdersWidget";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  window.HTMLElement.prototype.hasPointerCapture = vi.fn();
});

const ROW = {
  order_id: "TRIGGER-A", symbol: "NIFTY26OCT24000CE", exchange: "NFO", product: "NRML",
  action: "SELL", quantity: 75, status: "ACTIVE", trigger_price: 100, price: 100,
  pricetype: "LIMIT", validity: "DAY",
};
const PRIMARY_LIST_URL = "/ft-api/api/v1/orders/forever?broker=dhan&account_id=A1";
const SECONDARY_LIST_URL = "/ft-api/api/v1/orders/forever?broker=upstox&account_id=B2";
const PRIMARY_KEY = brokerOrderKeys.forever.list({ broker: "dhan", account_id: "A1" });
const CANCEL_PENDING = "Cancel pending. This order may still fill.";
const CHILD_CAVEAT = "Trigger status does not confirm the outcome of any spawned order. Check broker positions and orders.";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let respond: (url: string, init: RequestInit) => Response | Promise<Response>;
const unexpected: string[] = [];
const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = String(input);
  try {
    return Promise.resolve(respond(url, init));
  } catch (error) {
    unexpected.push(`${init.method ?? "GET"} ${url}: ${String(error)}`);
    return Promise.reject(error);
  }
});

function refuseUnexpected(url: string, init: RequestInit): never {
  const call = `${init.method ?? "GET"} ${url}`;
  unexpected.push(call);
  throw new Error(`Unregistered synthetic request: ${call}`);
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

async function refreshListing() {
  fireEvent.click(screen.getByRole("button", { name: "Refresh forever orders" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Refresh forever orders" })).toBeEnabled());
}

beforeEach(() => {
  fetchMock.mockClear();
  unexpected.length = 0;
  respond = (url, init) => {
    if (init.method === "GET" && url === PRIMARY_LIST_URL) {
      return jsonResponse({ status: "success", data: [ROW] });
    }
    return refuseUnexpected(url, init);
  };
  setAccountRuntime({ activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
  onlineManager.setOnline(true);
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  resetAccountRuntime();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  expect(unexpected).toEqual([]);
});

describe("ForeverOrders real-hook account availability", () => {
  it.each(["explore", "practice", "live"] as const)(
    "renders an inert no-account surface in %s without fetching or reusing cached rows", (mode) => {
      setAccountRuntime({ accounts: [], activeAccountId: null, mode });
      const { client } = renderAccountSurface(() => <ForeverOrdersWidget />);
      act(() => {
        client.setQueryData(PRIMARY_KEY, [ROW]);
        client.setQueryData(brokerOrderKeys.forever.list({ broker: "upstox", account_id: "B2" }), [ROW]);
      });
      expect(screen.getByText("Forever (GTT) Orders")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Place GTT" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Refresh forever orders" })).toBeDisabled();
      expect(screen.queryByText(ROW.symbol)).not.toBeInTheDocument();
      expect(screen.queryByText("No resting forever orders for this broker account.")).not.toBeInTheDocument();
      expect(screen.getByText(mode === "live"
        ? /currently implements native GTT management for writable Dhan and Upstox accounts/
        : /live-broker constructs/)).toBeInTheDocument();
      expect(fetchMock).not.toHaveBeenCalled();
      client.clear();
    },
  );

  it("disconnects to an inert surface without leaking the connected account's cached book", async () => {
    const { client } = renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByText(ROW.symbol)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(PRIMARY_KEY)).toEqual([ROW]);
    setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh forever orders" })).toBeDisabled());
    expect(screen.queryByText(ROW.symbol)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Place GTT" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh forever orders" }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(PRIMARY_KEY)).toEqual([ROW]);
    client.clear();
  });
});

describe("ForeverOrders real-hook book evidence", () => {
  const malformedBooks = [
    { status: "success", data: null },
    { status: "success" },
    { status: "success", data: { orders: [] } },
    { status: "success", orders: [] },
    { status: "success", data: [null, "garbage", 42, []] },
    { status: "success", data: [ROW, null] },
  ];

  it.each(malformedBooks)("keeps malformed successful listings unavailable, not empty: %j", async (body) => {
    respond = (url, init) => init.method === "GET" && url === PRIMARY_LIST_URL
      ? jsonResponse(body) : refuseUnexpected(url, init);
    renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByText(/listing is malformed or incomplete/i)).toBeInTheDocument();
    expect(screen.getByTestId("forever-orders-unavailable")).toBeInTheDocument();
    expect(screen.queryByText("No resting forever orders for this broker account.")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps invalid JSON unavailable and retains the last valid non-equity book on a failed refresh", async () => {
    renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByText(ROW.symbol)).toBeInTheDocument();
    respond = (url, init) => init.method === "GET" && url === PRIMARY_LIST_URL
      ? new Response("{invalid-json", { status: 200 }) : refuseUnexpected(url, init);
    await refreshListing();
    expect(await screen.findByText(/invalid JSON response/i)).toBeInTheDocument();
    expect(screen.getByTestId("forever-orders-unavailable")).toBeInTheDocument();
    expect(screen.getByText(ROW.symbol)).toBeInTheDocument();
    expect(screen.queryByText("No resting forever orders for this broker account.")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("renders a genuinely empty successful book without the unavailable warning", async () => {
    respond = (url, init) => init.method === "GET" && url === PRIMARY_LIST_URL
      ? jsonResponse({ status: "success", data: [] }) : refuseUnexpected(url, init);
    renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByText("No resting forever orders for this broker account.")).toBeInTheDocument();
    expect(screen.queryByTestId("forever-orders-unavailable")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retains the exact unsupported-broker refusal alongside the unavailable classification", async () => {
    const reason = "broker adapter 'dhan' does not support the 'forever_orders' listing";
    respond = (url, init) => init.method === "GET" && url === PRIMARY_LIST_URL
      ? jsonResponse({ status: "error", message: reason }, 501) : refuseUnexpected(url, init);
    renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByText("Not available for this broker.")).toBeInTheDocument();
    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(screen.getByTestId("forever-orders-unavailable")).toBeInTheDocument();
  });
});

describe("ForeverOrders real-hook cancellation evidence", () => {
  it("retains an ACK through disappearing, unavailable and unrelated rows until newer matching terminal evidence", async () => {
    const clock = vi.spyOn(Date, "now").mockReturnValue(1000);
    const cancellation = deferred<Response>();
    const listing = deferred<Response>();
    let getCount = 0;
    let nextListing = () => listing.promise;
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) {
        getCount += 1;
        return getCount === 1 ? jsonResponse({ status: "success", data: [ROW] }) : nextListing();
      }
      if (init.method === "DELETE" && url === "/ft-api/api/v1/orders/forever/TRIGGER-A?broker=dhan&account_id=A1") {
        expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("live");
        expect(init.body).toBeUndefined();
        return cancellation.promise;
      }
      return refuseUnexpected(url, init);
    };
    const { client } = renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByText(ROW.symbol)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("button", { name: "Cancel" })).toBeDisabled();
    await act(async () => { cancellation.resolve(jsonResponse({ status: "success", data: { order_id: ROW.order_id } })); });
    expect(await screen.findByText(CANCEL_PENDING)).toBeInTheDocument();
    expect(screen.getByText(ROW.symbol)).toBeInTheDocument();
    await waitFor(() => expect(getCount).toBe(2));
    clock.mockReturnValue(2000);
    await act(async () => { listing.resolve(jsonResponse({ status: "success", data: [] })); });
    await waitFor(() => expect(client.getQueryData(PRIMARY_KEY)).toEqual([]));
    expect(await screen.findByRole("alert", { name: `Cancellation for ${ROW.order_id}` })).toHaveTextContent(CANCEL_PENDING);

    nextListing = () => Promise.resolve(jsonResponse({ status: "error", message: "Native broker HTTP reads are unavailable until the read cutover" }, 409));
    await refreshListing();
    expect(await screen.findByText("Native broker HTTP reads are unavailable until the read cutover")).toBeInTheDocument();
    expect(screen.getByTestId("forever-orders-unavailable")).toBeInTheDocument();
    expect(screen.getByText(CANCEL_PENDING)).toBeInTheDocument();

    clock.mockReturnValue(3000);
    nextListing = () => Promise.resolve(jsonResponse({ status: "success", data: [{ ...ROW, order_id: "UNRELATED", status: "CANCELLED" }] }));
    await refreshListing();
    expect(screen.getByText("UNRELATED")).toBeInTheDocument();
    expect(screen.getByText(CANCEL_PENDING)).toBeInTheDocument();

    clock.mockReturnValue(4000);
    nextListing = () => Promise.resolve(jsonResponse({ status: "success", data: [{ ...ROW, status: "CANCELLED", child_order_id: "CHILD-A", child_status: "UNKNOWN" }] }));
    await refreshListing();
    await waitFor(() => expect(screen.queryByText(CANCEL_PENDING)).not.toBeInTheDocument());
    expect(screen.getByText("CANCELLED")).toBeInTheDocument();
    expect(screen.getByText(CHILD_CAVEAT)).toBeInTheDocument();
    expect(screen.queryByText(/child closed|child filled|child cancelled/i)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(1);
  });

  it.each(["success", "unknown error"] as const)(
    "does not attribute a late cancellation %s from A to connected B", async (outcome) => {
      setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT], activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
      const cancellation = deferred<Response>();
      const rowB = { ...ROW, order_id: "TRIGGER-B", symbol: "B-CONTRACT" };
      respond = (url, init) => {
        if (init.method === "GET" && url === PRIMARY_LIST_URL) return jsonResponse({ status: "success", data: [ROW] });
        if (init.method === "GET" && url === SECONDARY_LIST_URL) return jsonResponse({ status: "success", data: [rowB] });
        if (init.method === "DELETE" && url === "/ft-api/api/v1/orders/forever/TRIGGER-A?broker=dhan&account_id=A1") return cancellation.promise;
        return refuseUnexpected(url, init);
      };
      renderAccountSurface(() => <ForeverOrdersWidget />);
      await screen.findByText(ROW.symbol);
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      act(() => useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) }));
      await screen.findByText(rowB.symbol);
      await act(async () => {
        cancellation.resolve(outcome === "success"
          ? jsonResponse({ status: "success", data: { order_id: ROW.order_id } })
          : jsonResponse({ status: "error", message: "A cancellation response lost" }, 504));
      });
      expect(screen.getByText(rowB.symbol)).toBeInTheDocument();
      expect(screen.queryByText(CANCEL_PENDING)).not.toBeInTheDocument();
      expect(screen.queryByText("Cancel status unknown. This order may still fill.")).not.toBeInTheDocument();
      expect(screen.queryByText("A cancellation response lost")).not.toBeInTheDocument();
      expect(fetchMock.mock.calls.filter(([url]) => String(url) === SECONDARY_LIST_URL)).toHaveLength(1);
    },
  );
});

describe("ForeverOrders real-hook modification races", () => {
  it.each(["success", "unknown error"] as const)(
    "does not let a late A modification %s close B's panel or refetch B", async (outcome) => {
      setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT], activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
      const modification = deferred<Response>();
      const rowB = { ...ROW, order_id: "TRIGGER-B", symbol: "B-CONTRACT" };
      respond = (url, init) => {
        if (init.method === "GET" && url === PRIMARY_LIST_URL) return jsonResponse({ status: "success", data: [ROW] });
        if (init.method === "GET" && url === SECONDARY_LIST_URL) return jsonResponse({ status: "success", data: [rowB] });
        if (init.method === "PUT" && url === "/ft-api/api/v1/orders/forever/TRIGGER-A") {
          expect(JSON.parse(String(init.body))).toEqual({ broker: "dhan", account_id: "A1",
            changes: { order_flag: "SINGLE", leg_name: "TARGET_LEG", pricetype: "LIMIT", validity: "DAY",
              quantity: 75, price: 100, trigger_price: 100, disclosed_quantity: 0 } });
          expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("live");
          return modification.promise;
        }
        return refuseUnexpected(url, init);
      };
      renderAccountSurface(() => <ForeverOrdersWidget />);
      await screen.findByText(ROW.symbol);
      fireEvent.click(screen.getByRole("button", { name: "Modify" }));
      fireEvent.click(screen.getByRole("button", { name: "Apply" }));
      await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1));
      act(() => useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) }));
      await screen.findByText(rowB.symbol);
      await waitFor(() => expect(screen.queryByRole("form", { name: "Modify forever order" })).not.toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: "Modify" }));
      await act(async () => {
        modification.resolve(outcome === "success" ? jsonResponse({ status: "success", data: { order_id: ROW.order_id } })
          : jsonResponse({ status: "error", message: "A modification response timed out" }, 504));
      });
      expect(screen.getByRole("form", { name: "Modify forever order" })).toBeInTheDocument();
      expect(screen.queryByText("A modification response timed out")).not.toBeInTheDocument();
      expect(screen.queryByText("GTT modification status unknown. The trigger or order may still execute.")).not.toBeInTheDocument();
      expect(fetchMock.mock.calls.filter(([url]) => String(url) === SECONDARY_LIST_URL)).toHaveLength(1);
    },
  );
});
