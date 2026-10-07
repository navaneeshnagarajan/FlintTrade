/** Real OrderPad, stores, query hooks, placeOrder and native readiness guard. */
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import {
  renderAccountSurface,
  resetAccountRuntime,
  setAccountRuntime,
} from "@/test-utils/accountQueryHarness";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import type { BrokerAccount } from "@/types/broker";
import OrderPadWidget from "../OrderPadWidget";

const IND_ACCOUNT: BrokerAccount = {
  account_id: "IND-OFFLINE", broker: "indmoney", source: "native",
  label: "Synthetic INDstocks", status: "connected", is_primary: true,
  connected_at: null, error_message: null,
};
const MARKET_NOTICE = "INDstocks documents MARKET requests converting to LIMIT orders at the broker’s live price. The effective limit price is unknown until the broker reports it. Execution is not guaranteed.";
const NATIVE_PREFIX = "/ft-api/api/v1/native/accounts/indmoney/IND-OFFLINE";
const WRITE_URL = "/ft-api/api/v1/orders/indmoney/place";
const props = makeWidgetPanelProps({ params: { symbol: "RELIANCE", exchange: "NSE" } });
const originalSignals = useOperatorSignalStore.getState();
const unexpected: string[] = [];
const notifications: Array<Record<string, unknown>> = [];
const captureNotification = (event: Event) => notifications.push((event as CustomEvent<Record<string, unknown>>).detail);
let writeResponse: () => Response | Promise<Response>;
let caseClock = Date.now();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = String(input);
  const method = init.method ?? "GET";
  try {
    if (method === "GET" && url === "/ft-api/api/v1/native/accounts") {
      return Promise.resolve(jsonResponse({ status: "success", data: { accounts: [{
        adapter_id: "indmoney", account_id: "IND-OFFLINE", has_session: true, is_primary: true,
      }] } }));
    }
    if (method === "GET" && url === "/ft-api/api/v1/broker/capabilities?broker=indmoney") {
      return Promise.resolve(jsonResponse({ status: "success", data: {
        broker: "indmoney", capabilities: { broker_name: "INDstocks", broker_type: "equity", supported_exchanges: ["NSE", "NFO"] },
      } }));
    }
    if (method === "GET" && url === `${NATIVE_PREFIX}/search?query=RELIANCE&exchange=NSE`) {
      return Promise.resolve(jsonResponse({ status: "success", data: [{
        symbol: "RELIANCE", exchange: "NSE", lotsize: 1, tick_size: 0.05,
      }] }));
    }
    if (method === "GET" && (url === `${NATIVE_PREFIX}/positions` || url === `${NATIVE_PREFIX}/orders`)) {
      return Promise.resolve(jsonResponse({ status: "success", data: [] }));
    }
    if (method === "GET" && url === `${NATIVE_PREFIX}/margin?symbol=RELIANCE&exchange=NSE&qty=1&product=MIS&action=BUY&pricetype=MARKET`) {
      return Promise.resolve(jsonResponse({ status: "success", data: { total_margin: 100, span_margin: 100, exposure_margin: 0 } }));
    }
    if (method === "GET" && url === "/ft-api/v1/sandbox/positions") {
      return Promise.resolve(jsonResponse({ status: "success", data: { positions: [] } }));
    }
    if (method === "GET" && url === "/ft-api/v1/sandbox/orders") {
      return Promise.resolve(jsonResponse({ status: "success", data: { orders: [] } }));
    }
    if (method === "POST" && url === WRITE_URL) return Promise.resolve(writeResponse());
    if (method === "POST" && url === "/ft-api/api/v1/orders/place") {
      expect(init.headers).toMatchObject({ "X-FlintTrade-Mode": "practice" });
      return Promise.resolve(jsonResponse({ status: "success", data: { order_id: "SANDBOX-OFFLINE" } }));
    }
    throw new Error(`Unregistered synthetic request: ${method} ${url}`);
  } catch (error) {
    unexpected.push(String(error));
    return Promise.reject(error);
  }
});

beforeEach(() => {
  // Each transport fixture is a separate session. Advance Date.now rather
  // than mocking the real limiters; their refill/tryConsume guards still run.
  caseClock = Math.max(caseClock, Date.now()) + 1_000;
  vi.spyOn(Date, "now").mockReturnValue(caseClock);
  unexpected.length = 0;
  notifications.length = 0;
  window.addEventListener("flinttrade:notify", captureNotification);
  fetchMock.mockClear();
  setAccountRuntime({ accounts: [IND_ACCOUNT], activeAccountId: brokerAccountKey(IND_ACCOUNT) });
  useOperatorSignalStore.setState({ ...originalSignals, decisionStatus: "ready", layaPracticeStatus: "ready" });
  writeResponse = () => jsonResponse({ status: "error", message: "INDstocks activation is unavailable. No order was sent." }, 503);
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  window.removeEventListener("flinttrade:notify", captureNotification);
  resetAccountRuntime();
  useOperatorSignalStore.setState(originalSignals);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  expect(unexpected).toEqual([]);
});

describe("OrderPad INDstocks execution disclosure", () => {
  it("discloses the documented conversion before the existing Live submit without bypassing activation", async () => {
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    const notice = screen.getByText(MARKET_NOTICE);
    const submit = screen.getByRole("button", { name: "Place BUY Order" });
    expect(notice.compareDocumentPosition(submit) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(submit);
    expect(await screen.findByRole("alert")).toHaveTextContent("INDstocks activation is unavailable. No order was sent.");
    const writes = fetchMock.mock.calls.filter(([input, init]) => String(input) === WRITE_URL && init?.method === "POST");
    expect(writes).toHaveLength(1);
    const request = writes[0]?.[1];
    expect(JSON.parse(String(request?.body))).toEqual({
      symbol: "RELIANCE", exchange: "NSE", action: "BUY", product: "MIS", orderType: "MARKET",
      quantity: 1, price: 0, triggerPrice: 0, strategy: "FlintOrderPad", rationale: "",
      order_type: "MARKET", trigger_price: 0, broker: "indmoney", account_id: "IND-OFFLINE",
    });
    expect(request?.headers).toMatchObject({ "X-FlintTrade-Mode": "live" });
    expect(screen.getByText(MARKET_NOTICE)).toBeInTheDocument();
    await waitFor(() => expect(submit).toBeEnabled());
  });

  it.each(["disconnected", "read-only", "bare selector", "missing selection"])(
    "keeps the real native-write refusal with %s rather than treating disclosure as readiness", async (state) => {
      renderAccountSurface(() => <OrderPadWidget {...props} />);
      await screen.findByText("Lot: 1");
      act(() => {
        if (state === "disconnected") useBrokerStore.getState().updateAccount(brokerAccountKey(IND_ACCOUNT), { status: "disconnected" });
        if (state === "read-only") useBrokerStore.getState().updateAccount(brokerAccountKey(IND_ACCOUNT), { read_only: true });
        if (state === "bare selector") useBrokerStore.setState({ activeAccountId: IND_ACCOUNT.account_id });
        if (state === "missing selection") useBrokerStore.setState({ activeAccountId: null });
      });
      fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Your selected native broker is not available for live writes");
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
    },
  );

  it("does not describe a requested LIMIT as a market conversion or discard its price", async () => {
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("radio", { name: "LIMIT" }));
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "73.55" } });
    expect(screen.queryByText(MARKET_NOTICE)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
    await screen.findByRole("alert");
    const request = fetchMock.mock.calls.find(([input, init]) => String(input) === WRITE_URL && init?.method === "POST")?.[1];
    expect(JSON.parse(String(request?.body))).toEqual({
      symbol: "RELIANCE", exchange: "NSE", action: "BUY", product: "MIS", orderType: "LIMIT",
      quantity: 1, price: 73.55, triggerPrice: 0, strategy: "FlintOrderPad", rationale: "",
      order_type: "LIMIT", trigger_price: 0, broker: "indmoney", account_id: "IND-OFFLINE",
    });
  });

  it.each(["practice", "explore"] as const)("keeps %s review on the paper path without native conversion/protection claims", async (mode) => {
    setAccountRuntime({ accounts: [IND_ACCOUNT], activeAccountId: brokerAccountKey(IND_ACCOUNT), mode });
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    expect(screen.queryByText(MARKET_NOTICE)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "GTT" })).toHaveAttribute("title", "GTT orders aren't supported right now.");
    fireEvent.click(screen.getByRole("button", { name: mode === "practice" ? "Practice Buy" : "Example Buy" }));
    const review = await screen.findByRole("dialog");
    expect(review).not.toHaveTextContent(/INDstocks|converting to LIMIT|trailing protection/i);
    fireEvent.click(screen.getByRole("button", { name: mode === "practice" ? "Confirm simulated Practice order" : "Confirm Example order" }));
    await screen.findByRole("alert");
    expect(fetchMock.mock.calls.filter(([input, init]) => String(input) === WRITE_URL && init?.method === "POST")).toHaveLength(0);
    const sandboxWrites = fetchMock.mock.calls.filter(([input, init]) => String(input) === "/ft-api/api/v1/orders/place" && init?.method === "POST");
    expect(sandboxWrites).toHaveLength(mode === "practice" ? 1 : 0);
    if (mode === "practice") {
      const body = JSON.parse(String(sandboxWrites[0]?.[1]?.body));
      expect(body.order_type).toBe("MARKET");
      expect(body).not.toHaveProperty("broker");
      expect(body).not.toHaveProperty("account_id");
      expect(body).not.toHaveProperty("execution_effects");
    }
  });

  it("treats the legacy scalar response without additive evidence as an acknowledgement, retaining its ID without claiming execution", async () => {
    writeResponse = () => jsonResponse({ status: "success", orderid: "EQ-OFFLINE", data: "EQ-OFFLINE" });
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
    const receipt = await screen.findByRole("alert");
    expect(receipt).toHaveTextContent("Order requested · ID: EQ-OFFLINE");
    expect(receipt).not.toHaveTextContent(/filled|closed|trailing protection is active/i);
    expect(screen.getByText(MARKET_NOTICE)).toBeInTheDocument();
  });

  it.each(["native scalar-data/top-level envelope", "legacy object-data wrapper"])("renders %s requested/effective fields as documented semantics, retaining unknown price and inactive trailing", async (shape) => {
    // The first shape is pinned by the normal gated backend HTTP regression;
    // the second remains a legacy compatibility control, not native correspondence.
    const evidence = {
      order_ids: ["EQ-OFFLINE"], child_order_id: null,
      broker_response: { order_id: "EQ-OFFLINE", order_status: "INITIATED", extra_info: { observations: ["accepted", null] } },
      execution_effects: {
        requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: null,
        trailing_active: false, limitations: ["MARKET_TO_LIMIT"],
      },
    };
    writeResponse = () => jsonResponse(shape === "native scalar-data/top-level envelope"
      ? { status: "success", orderid: "EQ-OFFLINE", data: "EQ-OFFLINE", ...evidence }
      : { status: "success", data: { order_id: "EQ-OFFLINE", ...evidence } });
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
    const disclosure = await screen.findByRole("status", { name: "INDstocks submission disclosure" });
    expect(disclosure).toHaveTextContent("Submission ID: EQ-OFFLINE");
    expect(disclosure).toHaveTextContent("Requested: MARKET. Documented execution: LIMIT.");
    expect(disclosure).toHaveTextContent("Effective limit price: unknown.");
    expect(disclosure).toHaveTextContent("Trailing protection: inactive.");
    expect(disclosure).toHaveTextContent("Submission acknowledgement is not a fill.");
    fireEvent.click(screen.getByRole("radio", { name: "LIMIT" }));
    expect(disclosure).toHaveTextContent("Requested: MARKET.");
    expect(screen.queryByText(MARKET_NOTICE)).not.toBeInTheDocument();
    act(() => { useModeStore.setState({ mode: "practice" }); });
    expect(screen.queryByRole("status", { name: "INDstocks submission disclosure" })).not.toBeInTheDocument();
  });

  it.each([
    { name: "missing effects", effects: undefined },
    { name: "null effects", effects: null },
    { name: "array effects", effects: [] },
    { name: "mismatched request", effects: { requested_type: "LIMIT", effective_type: "LIMIT", effective_limit_price: null, trailing_active: false, limitations: [] } },
    { name: "missing price", effects: { requested_type: "MARKET", effective_type: "LIMIT", trailing_active: false, limitations: [] } },
    { name: "coerced price", effects: { requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: "73.55", trailing_active: false, limitations: [] } },
    { name: "zero price", effects: { requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: 0, trailing_active: false, limitations: [] } },
    { name: "active trailing", effects: { requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: null, trailing_active: true, limitations: [] } },
    { name: "missing limitations", effects: { requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: null, trailing_active: false } },
    { name: "non-string limitation", effects: { requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: null, trailing_active: false, limitations: [null] } },
  ])("does not manufacture a known disclosure from $name", async ({ effects }) => {
    writeResponse = () => jsonResponse({ status: "success", orderid: "SYNTHETIC-UNVERIFIED-EFFECTS", data: "SYNTHETIC-UNVERIFIED-EFFECTS", order_ids: ["SYNTHETIC-UNVERIFIED-EFFECTS"], execution_effects: effects });
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Order requested · ID: SYNTHETIC-UNVERIFIED-EFFECTS");
    expect(screen.queryByRole("status", { name: "INDstocks submission disclosure" })).not.toBeInTheDocument();
    expect(screen.getByText(MARKET_NOTICE)).toBeInTheDocument();
  });

  it.each([
    { name: "null price and observed empty limitations", price: null, limitations: [] },
    { name: "reported positive price and extension metadata", price: 73.55, limitations: ["MARKET_TO_LIMIT"] },
  ])("retains $name without inferring fills or a new scope", async ({ price, limitations }) => {
    writeResponse = () => jsonResponse({ status: "success", orderid: "SYNTHETIC-KNOWN-EFFECTS", data: "SYNTHETIC-KNOWN-EFFECTS",
      order_ids: ["SYNTHETIC-KNOWN-EFFECTS"], child_order_id: null,
      broker_response: { order_status: "INITIATED", native_metadata: { nullable: null, inactive: false } },
      execution_effects: Object.freeze({ requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: price, trailing_active: false, limitations, unknown_native_json: { nullable: null, inactive: false, observations: [0, "0"] } }),
    });
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
    const disclosure = await screen.findByRole("status", { name: "INDstocks submission disclosure" });
    expect(disclosure).toHaveTextContent("Submission ID: SYNTHETIC-KNOWN-EFFECTS");
    expect(disclosure).toHaveTextContent("Requested: MARKET. Documented execution: LIMIT.");
    expect(disclosure).toHaveTextContent(price === null ? "Effective limit price: unknown." : "Effective limit price: ₹73.55.");
    expect(disclosure).toHaveTextContent("Trailing protection: inactive. Submission acknowledgement is not a fill.");
    expect(disclosure).not.toHaveTextContent(/filled|closed|protection is active/i);
  });

  it("keeps a delayed native acknowledgement bound to its original scope after switching to Practice", async () => {
    let finish!: (response: Response) => void;
    writeResponse = () => new Promise<Response>((resolve) => { finish = resolve; });
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1));
    act(() => { useModeStore.setState({ mode: "practice" }); });
    await act(async () => { finish(jsonResponse({ status: "success", orderid: "EQ-LATE-NATIVE", data: "EQ-LATE-NATIVE",
      order_ids: ["EQ-LATE-NATIVE"], child_order_id: null,
      execution_effects: { requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: null, trailing_active: false, limitations: ["MARKET_TO_LIMIT"] },
      broker_response: { order_id: "EQ-LATE-NATIVE", order_status: "INITIATED" },
    })); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Practice Buy" })).toBeEnabled());
    expect(screen.queryByText(/EQ-LATE-NATIVE/)).not.toBeInTheDocument();
    expect(screen.queryByText(MARKET_NOTICE)).not.toBeInTheDocument();
    expect(notifications).toEqual([expect.objectContaining({
      accountScopeKey: "live:native:indmoney:IND-OFFLINE", skipAccountRefresh: true,
      title: "Order requested: BUY 1 RELIANCE", body: expect.stringContaining("EQ-LATE-NATIVE"),
    })]);
  });

  it("explains the ignored trailing limitation on the existing unavailable native GTT control without activating it", async () => {
    renderAccountSurface(() => <OrderPadWidget {...props} />);
    await screen.findByText("Lot: 1");
    const gtt = screen.getByRole("button", { name: "GTT" });
    expect(gtt).toBeDisabled();
    expect(gtt).toHaveAttribute("title", "GTT creation is unavailable in this Order Pad. INDstocks currently ignores trailing-stop fields; active trailing requests are refused, not treated as protection.");
    fireEvent.click(gtt);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  });
});
