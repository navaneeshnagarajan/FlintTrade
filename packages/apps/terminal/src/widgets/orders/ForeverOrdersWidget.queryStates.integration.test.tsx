/** Real stores, query hooks and fetch decoding; synthetic responses only. */
import { onlineManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { brokerOrderKeys } from "@/lib/brokerOrdersApi";
import { writePersistedAuthSession } from "@/lib/homeEntry";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import type { BrokerAccount } from "@/types/broker";
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
const CANCEL_PENDING = "Cancellation requested";
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
      expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
      expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
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
      expect(screen.queryByText("Order status unknown. Check Forever Orders before trying again.")).not.toBeInTheDocument();
      expect(screen.queryByText("GTT modification status unknown. The trigger or order may still execute.")).not.toBeInTheDocument();
      expect(fetchMock.mock.calls.filter(([url]) => String(url) === SECONDARY_LIST_URL)).toHaveLength(1);
    },
  );
});

const FOREVER_UNKNOWN = "Order status unknown. Check Forever Orders before trying again.";
const PLACE_URL = "/ft-api/api/v1/orders/place";

describe("synthetic Dhan GTT outcomes", () => {
  async function openBook() {
    renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByRole("button", { name: "Place GTT" })).toBeInTheDocument();
  }

  function placeForever() {
    fireEvent.change(screen.getByLabelText("GTT symbol"), { target: { value: "RELIANCE" } });
    fireEvent.change(screen.getByLabelText("GTT quantity"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("GTT trigger price"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("GTT limit price"), { target: { value: "101" } });
    fireEvent.click(screen.getByRole("button", { name: "Place GTT" }));
  }

  it("a dropped place says to check Forever Orders, offers no Retry, and sends one POST", async () => {
    let posts = 0;
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) return jsonResponse({ status: "success", data: [] });
      if (init.method === "POST" && url === PLACE_URL) {
        posts += 1;
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      return refuseUnexpected(url, init);
    };
    await openBook();
    placeForever();
    expect(await screen.findByText(FOREVER_UNKNOWN)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(posts).toBe(1);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("a lost cancel says Cancellation requested and does not resubmit", async () => {
    let deletes = 0;
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) return jsonResponse({ status: "success", data: [ROW] });
      if (init.method === "DELETE" && url === "/ft-api/api/v1/orders/forever/TRIGGER-A?broker=dhan&account_id=A1") {
        deletes += 1;
        return jsonResponse({
          status: "error",
          message: "Synthetic cancel response lost",
          order_outcome: "unknown",
          reason: "response_unconfirmed",
          retry_safe: false,
        }, 504);
      }
      return refuseUnexpected(url, init);
    };
    await openBook();
    expect(await screen.findByText(ROW.symbol)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Cancellation requested")).toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(deletes).toBe(1);
  });

  it("a dropped cancel becomes Order cancelled when the row is later CANCELLED", async () => {
    let deletes = 0;
    let confirmed = false;
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) {
        return jsonResponse({ status: "success", data: [{ ...ROW, status: confirmed ? "CANCELLED" : "ACTIVE" }] });
      }
      if (init.method === "DELETE" && url === "/ft-api/api/v1/orders/forever/TRIGGER-A?broker=dhan&account_id=A1") {
        deletes += 1;
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      return refuseUnexpected(url, init);
    };
    await openBook();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Cancellation requested")).toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    confirmed = true;
    await refreshListing();
    expect(await screen.findByText("Order cancelled")).toBeInTheDocument();
    expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
    expect(deletes).toBe(1);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(1);
  });

  it.each(["TRIGGERED", "FILLED"])(
    "a dropped cancel followed by %s does not claim the cancel is still pending", async (status) => {
      let deletes = 0;
      let followedUp = false;
      respond = (url, init) => {
        if (init.method === "GET" && url === PRIMARY_LIST_URL) {
          return jsonResponse({ status: "success", data: [{ ...ROW, status: followedUp ? status : "ACTIVE" }] });
        }
        if (init.method === "DELETE" && url === "/ft-api/api/v1/orders/forever/TRIGGER-A?broker=dhan&account_id=A1") {
          deletes += 1;
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        return refuseUnexpected(url, init);
      };
      await openBook();
      fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
      expect(await screen.findByText("Cancellation requested")).toBeInTheDocument();
      followedUp = true;
      await refreshListing();
      expect(await screen.findByText(status)).toBeInTheDocument();
      expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
      expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
      expect(screen.getByText(CHILD_CAVEAT)).toBeInTheDocument();
      expect(deletes).toBe(1);
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(1);
    },
  );

  it("a dropped modify says to check Forever Orders, offers no Retry, and sends one PUT", async () => {
    let puts = 0;
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) return jsonResponse({ status: "success", data: [ROW] });
      if (init.method === "PUT" && url === "/ft-api/api/v1/orders/forever/TRIGGER-A") {
        puts += 1;
        return jsonResponse({
          status: "error",
          message: "Synthetic modify response lost",
          order_outcome: "unknown",
          reason: "response_unconfirmed",
          retry_safe: false,
        }, 504);
      }
      return refuseUnexpected(url, init);
    };
    await openBook();
    expect(await screen.findByText(ROW.symbol)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Modify" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText(FOREVER_UNKNOWN)).toBeInTheDocument();
    expect(screen.queryByText("GTT modification status unknown. The trigger or order may still execute.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(puts).toBe(1);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
  });

  it("shows Order cancelled only after the synthetic status confirms it", async () => {
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) return jsonResponse({ status: "success", data: [ROW] });
      if (init.method === "DELETE" && url === "/ft-api/api/v1/orders/forever/TRIGGER-A?broker=dhan&account_id=A1") {
        return jsonResponse({
          status: "success",
          order_outcome: "cancel_requested",
          reason: "awaiting_confirmation",
          message: "Cancellation requested",
          retry_safe: false,
          data: { orderId: ROW.order_id, status: "PENDING" },
        });
      }
      return refuseUnexpected(url, init);
    };
    await openBook();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Cancellation requested")).toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) {
        return jsonResponse({ status: "success", data: [{ ...ROW, status: "CANCELLED" }] });
      }
      return refuseUnexpected(url, init);
    };
    await refreshListing();
    expect(await screen.findByText("Order cancelled")).toBeInTheDocument();
    expect(screen.queryByText("Cancellation requested")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(1);
  });

  it("a broker rejection stays a refusal and does not offer Retry", async () => {
    let posts = 0;
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) return jsonResponse({ status: "success", data: [] });
      if (init.method === "POST" && url === PLACE_URL) {
        posts += 1;
        return jsonResponse({
          status: "error",
          message: "GTT rejected by broker",
          order_outcome: "rejected",
          reason: "broker_rejected",
          retry_safe: false,
        }, 400);
      }
      return refuseUnexpected(url, init);
    };
    await openBook();
    placeForever();
    expect(await screen.findByText("GTT rejected by broker")).toBeInTheDocument();
    expect(screen.queryByText(FOREVER_UNKNOWN)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(posts).toBe(1);
  });
});

const OPERATOR = "operator";
const OTHER_DHAN_ACCOUNT: BrokerAccount = {
  ...PRIMARY_NATIVE_ACCOUNT,
  account_id: "A2",
  label: "Other Dhan",
  is_primary: false,
};
const OTHER_LIST_URL = "/ft-api/api/v1/orders/forever?broker=dhan&account_id=A2";
const DELETE_URL = "/ft-api/api/v1/orders/forever/TRIGGER-A?broker=dhan&account_id=A1";

function pendingCancelKey(mode: "live" | "practice", accountId: string): string {
  const scope = `${mode}:dhan:${accountId}`;
  return `flinttrade:forever-pending-cancels:${encodeURIComponent(OPERATOR)}:${encodeURIComponent(scope)}`;
}

describe("a dropped Forever cancel survives a fresh client", () => {
  beforeEach(() => {
    writePersistedAuthSession({ token: "operator-session", username: OPERATOR, expiresAt: "" });
  });

  async function dropCancel(): Promise<void> {
    renderAccountSurface(() => <ForeverOrdersWidget />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText(CANCEL_PENDING)).toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    await waitFor(() => expect(sessionStorage.getItem(pendingCancelKey("live", "A1"))).toContain(ROW.order_id));
  }

  async function refreshSettledBook(): Promise<void> {
    const refresh = screen.getByRole("button", { name: "Refresh forever orders" });
    await waitFor(() => expect(refresh).toBeEnabled());
    fireEvent.click(refresh);
    await waitFor(() => expect(refresh).toBeEnabled());
  }

  function remount(): void {
    cleanup();
    renderAccountSurface(() => <ForeverOrdersWidget />);
  }

  it("shows Order cancelled after a remount when the row later reads CANCELLED", async () => {
    let deletes = 0;
    let confirmed = false;
    respond = (url, init) => {
      if (init.method === "GET" && url === PRIMARY_LIST_URL) {
        return jsonResponse({ status: "success", data: [{ ...ROW, status: confirmed ? "CANCELLED" : "ACTIVE" }] });
      }
      if (init.method === "DELETE" && url === DELETE_URL) {
        deletes += 1;
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      return refuseUnexpected(url, init);
    };
    await dropCancel();
    expect(deletes).toBe(1);
    remount();
    expect(await screen.findByText(CANCEL_PENDING)).toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    confirmed = true;
    await refreshSettledBook();
    expect(await screen.findByText("Order cancelled")).toBeInTheDocument();
    expect(screen.queryByText(CANCEL_PENDING)).not.toBeInTheDocument();
    expect(screen.getByText(CHILD_CAVEAT)).toBeInTheDocument();
    expect(deletes).toBe(1);
    await waitFor(() => expect(sessionStorage.getItem(pendingCancelKey("live", "A1"))).toBeNull());
  });

  it.each(["TRIGGERED", "FILLED"])(
    "clears the restored pending cancel when a remounted row later reads %s",
    async (status) => {
      let deletes = 0;
      let followedUp = false;
      respond = (url, init) => {
        if (init.method === "GET" && url === PRIMARY_LIST_URL) {
          return jsonResponse({ status: "success", data: [{ ...ROW, status: followedUp ? status : "ACTIVE" }] });
        }
        if (init.method === "DELETE" && url === DELETE_URL) {
          deletes += 1;
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        return refuseUnexpected(url, init);
      };
      await dropCancel();
      remount();
      expect(await screen.findByText(CANCEL_PENDING)).toBeInTheDocument();
      followedUp = true;
      await refreshSettledBook();
      expect(await screen.findByText(status)).toBeInTheDocument();
      expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
      expect(screen.queryByText(CANCEL_PENDING)).not.toBeInTheDocument();
      expect(screen.getByText(CHILD_CAVEAT)).toBeInTheDocument();
      expect(deletes).toBe(1);
      await waitFor(() => expect(sessionStorage.getItem(pendingCancelKey("live", "A1"))).toBeNull());
    },
  );

  it("keeps the pending cancel on the signed-in Live account that requested it", async () => {
    respond = (url, init) => {
      if (init.method === "GET" && (url === PRIMARY_LIST_URL || url === OTHER_LIST_URL)) {
        return jsonResponse({ status: "success", data: [ROW] });
      }
      if (init.method === "DELETE" && url === DELETE_URL) {
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      return refuseUnexpected(url, init);
    };
    await dropCancel();
    const liveRecord = sessionStorage.getItem(pendingCancelKey("live", "A1"));
    expect(liveRecord).toContain(ROW.order_id);
    expect(sessionStorage.getItem(pendingCancelKey("practice", "A1"))).toBeNull();
    expect(sessionStorage.getItem(pendingCancelKey("live", "A2"))).toBeNull();

    cleanup();
    setAccountRuntime({ mode: "practice", activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
    renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(screen.queryByText(CANCEL_PENDING)).not.toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(pendingCancelKey("practice", "A1"))).toBeNull();
    expect(sessionStorage.getItem(pendingCancelKey("live", "A1"))).toBe(liveRecord);

    cleanup();
    setAccountRuntime({
      accounts: [PRIMARY_NATIVE_ACCOUNT, OTHER_DHAN_ACCOUNT],
      activeAccountId: brokerAccountKey(OTHER_DHAN_ACCOUNT),
      mode: "live",
    });
    renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByText(ROW.symbol)).toBeInTheDocument();
    expect(screen.queryByText(CANCEL_PENDING)).not.toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(pendingCancelKey("live", "A2"))).toBeNull();
    expect(sessionStorage.getItem(pendingCancelKey("live", "A1"))).toBe(liveRecord);

    cleanup();
    setAccountRuntime({
      accounts: [PRIMARY_NATIVE_ACCOUNT, OTHER_DHAN_ACCOUNT],
      activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT),
      mode: "live",
    });
    renderAccountSurface(() => <ForeverOrdersWidget />);
    expect(await screen.findByText(CANCEL_PENDING)).toBeInTheDocument();
    expect(screen.queryByText("Order cancelled")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(pendingCancelKey("live", "A1"))).toBe(liveRecord);
  });
});
