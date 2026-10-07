/** Ordinary widget/client/feed seams; only exact HTTP responses are inert. */
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useNotificationFeed } from "@/components/NotificationCentre/useNotificationFeed";
import { clearAll, getSnapshot } from "@/components/NotificationCentre/notificationStore";
import { renderAccountSurface, resetAccountRuntime, setAccountRuntime } from "@/test-utils/accountQueryHarness";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import { OrderApiError, placeOrder } from "@/services/api";
import type { BrokerAccount } from "@/types/broker";
import OrderPadWidget from "../OrderPadWidget";

const a: BrokerAccount = { account_id: "KOTAK-OFFLINE", broker: "kotakneo", source: "native", label: "Synthetic Kotak", status: "connected", is_primary: true, connected_at: null, error_message: null };
const b: BrokerAccount = { ...a, account_id: "KOTAK-OFFLINE-B", is_primary: false };
const writeUrl = "/ft-api/api/v1/orders/kotakneo/place";
let suppliedSymbol = "INFY";
let props = makeWidgetPanelProps({ params: { symbol: suppliedSymbol, exchange: "NSE" } });
const params = { symbol: "INFY", exchange: "NSE", action: "BUY" as const, product: "MIS" as const, orderType: "MARKET" as const, quantity: 1, price: 0, triggerPrice: 0, strategy: "FlintOrderPad" };
const originalSignals = useOperatorSignalStore.getState();
const events: Array<Record<string, unknown>> = [];
const unexpected: string[] = [];
const notify = (event: Event) => events.push((event as CustomEvent<Record<string, unknown>>).detail);
let fault: unknown;
let status: number;
let writeResponse: () => Promise<Response>;
let clock = Date.now();
const rawUnknown = () => ({ status: "error", message: "Order dispatch failed", dispatch_outcome: "unknown_after_dispatch", retry_safe: false, affected_item: { broker: "kotakneo", account_id: a.account_id, operation: "place", symbol: suppliedSymbol, exchange: "NSE", product: "MIS", action: "BUY" }, broker_code: "1021", broker_message: "Order is completed" });
const response = (body: unknown, httpStatus = 200) => new Response(JSON.stringify(body), { status: httpStatus, headers: { "Content-Type": "application/json" } });
const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
  const url = String(input); const method = init.method ?? "GET";
  try {
    if (method === "GET" && url === "/ft-api/api/v1/native/accounts") return Promise.resolve(response({ status: "success", data: { accounts: [a, b].map((account) => ({ adapter_id: account.broker, account_id: account.account_id, has_session: true, is_primary: account.is_primary })) } }));
    if (method === "GET" && url === "/ft-api/api/v1/broker/capabilities?broker=kotakneo") return Promise.resolve(response({ status: "success", data: { broker: "kotakneo", capabilities: { broker_name: "Kotak Neo", broker_type: "equity", supported_exchanges: ["NSE"] } } }));
    for (const account of [a, b]) {
      const prefix = `/ft-api/api/v1/native/accounts/kotakneo/${account.account_id}`;
      if (method === "GET" && url === `${prefix}/search?query=${encodeURIComponent(suppliedSymbol)}&exchange=NSE`) return Promise.resolve(response({ status: "success", data: [{ symbol: suppliedSymbol, exchange: "NSE", lotsize: 1, tick_size: 0.05 }] }));
      if (method === "GET" && (url === `${prefix}/positions` || url === `${prefix}/orders`)) return Promise.resolve(response({ status: "success", data: [] }));
      if (method === "GET" && url === `${prefix}/margin?symbol=${encodeURIComponent(suppliedSymbol)}&exchange=NSE&qty=1&product=MIS&action=BUY&pricetype=MARKET`) return Promise.resolve(response({ status: "success", data: { total_margin: 100, span_margin: 100, exposure_margin: 0 } }));
    }
    if (method === "GET" && url === "/ft-api/v1/sandbox/positions") return Promise.resolve(response({ status: "success", data: { positions: [] } }));
    if (method === "GET" && url === "/ft-api/v1/sandbox/orders") return Promise.resolve(response({ status: "success", data: { orders: [] } }));
    if (method === "POST" && url === writeUrl) {
      expect(init.headers).toMatchObject({ "X-FlintTrade-Mode": "live", "Content-Type": "application/json" });
      expect(JSON.parse(String(init.body))).toMatchObject({ ...params, symbol: suppliedSymbol, order_type: "MARKET", trigger_price: 0, broker: "kotakneo", account_id: a.account_id });
      return writeResponse();
    }
    if (method === "POST" && url === "/ft-api/api/v1/orders/place") {
      expect(init.headers).toMatchObject({ "X-FlintTrade-Mode": "practice" });
      const body = JSON.parse(String(init.body));
      expect(body).not.toHaveProperty("broker"); expect(body).not.toHaveProperty("account_id");
      return Promise.resolve(response({ status: "success", data: { order_id: "SYNTHETIC-PAPER" } }));
    }
    throw new Error(`Unregistered request: ${method} ${url}`);
  } catch (error) { unexpected.push(String(error)); return Promise.reject(error); }
});
function Surface() { useNotificationFeed(); return <OrderPadWidget {...props} />; }
async function submit() {
  renderAccountSurface(() => <Surface />);
  await screen.findByText("Lot: 1");
  fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
  const alert = await screen.findByRole("alert");
  await waitFor(() => expect(events).toHaveLength(1));
  expect(getSnapshot()[0]).toMatchObject({ title: events[0]?.title, body: events[0]?.body });
  expect(events[0]).toMatchObject({ accountScopeKey: "live:native:kotakneo:KOTAK-OFFLINE", skipAccountRefresh: true });
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  return alert;
}
function assertUnknown(alert: HTMLElement) {
  expect(alert).toHaveTextContent("Order outcome unknown. An order may still execute. Check broker positions and orders. Do not retry automatically.");
  expect(alert).not.toHaveTextContent(/Not placed|No order was sent|Order filled|Position closed|Try again/i);
  expect(events[0]?.title).toBe("Order outcome unknown: BUY INFY");
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  expect(getSnapshot()[0]).not.toHaveProperty("action");
}
beforeEach(() => {
  suppliedSymbol = "INFY"; props = makeWidgetPanelProps({ params: { symbol: suppliedSymbol, exchange: "NSE" } });
  clock = Math.max(clock, Date.now()) + 1000; vi.spyOn(Date, "now").mockReturnValue(clock);
  events.length = 0; unexpected.length = 0; fetchMock.mockClear(); clearAll();
  window.addEventListener("flinttrade:notify", notify);
  setAccountRuntime({ accounts: [a, b], activeAccountId: brokerAccountKey(a) });
  useOperatorSignalStore.setState({ ...originalSignals, decisionStatus: "ready", layaPracticeStatus: "ready" });
  fault = rawUnknown(); status = 500; writeResponse = () => Promise.resolve(response(fault, status));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup(); window.removeEventListener("flinttrade:notify", notify); resetAccountRuntime(); clearAll();
  useOperatorSignalStore.setState(originalSignals); vi.unstubAllGlobals(); vi.restoreAllMocks();
  expect(unexpected).toEqual([]);
});
describe("bounded truthful operator order errors", () => {
  it("retains the original body at the real client without treating its native reason as a fill", async () => {
    let error: unknown; try { await placeOrder(params); } catch (value) { error = value; }
    expect(error).toBeInstanceOf(OrderApiError); expect((error as OrderApiError).body).toEqual(fault);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });
  it("renders the literal native code/reason separately from unknown outcome in the pad and central feed", async () => {
    const beforeFault = useOperatorSignalStore.getState().brokerReject;
    const alert = await submit(); assertUnknown(alert);
    expect(alert).toHaveTextContent("Broker reason (observation): Order is completed. Broker code: 1021.");
    expect(getSnapshot()[0]?.body).toBe(alert.textContent);
    expect(useOperatorSignalStore.getState().brokerReject).toEqual(beforeFault);
  });
  it("renders a complete matching pre-invocation refusal truthfully without a retry", async () => {
    fault = { ...rawUnknown(), dispatch_outcome: "refused_before_dispatch", message: "Unsupported protection intent", broker_message: "Protection is unavailable", broker_code: "UNSUPPORTED" }; status = 400;
    const alert = await submit(); expect(alert).toHaveTextContent("Order refused before dispatch. No order was sent. No automatic retry.");
    expect(alert).toHaveTextContent("Protection is unavailable"); expect(alert).toHaveTextContent("UNSUPPORTED");
    expect(events[0]?.title).toBe("Order refused: BUY INFY"); expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });
  const malformed: Array<{ name: string; patch: Record<string, unknown> }> = [
    { name: "successful status with error fields", patch: { status: "success" } },
    { name: "absent status", patch: { status: undefined } },
    { name: "unknown outcome enum", patch: { dispatch_outcome: "completed" } },
    { name: "missing retry observation", patch: { retry_safe: undefined } },
    { name: "unsafe optimistic retry", patch: { retry_safe: true } },
    { name: "coerced retry flag", patch: { retry_safe: "false" } },
    { name: "missing affected origin", patch: { affected_item: undefined } },
    { name: "case-only account mismatch", patch: { affected_item: { ...rawUnknown().affected_item, account_id: "kotak-offline" } } },
    { name: "another account", patch: { affected_item: { ...rawUnknown().affected_item, account_id: b.account_id } } },
    { name: "another broker", patch: { affected_item: { ...rawUnknown().affected_item, broker: "dhan" } } },
    { name: "cancel operation", patch: { affected_item: { ...rawUnknown().affected_item, operation: "cancel" } } },
    { name: "missing product", patch: { affected_item: { ...rawUnknown().affected_item, product: undefined } } },
    { name: "other symbol", patch: { affected_item: { ...rawUnknown().affected_item, symbol: "OTHER" } } },
    { name: "noncanonical side", patch: { affected_item: { ...rawUnknown().affected_item, action: "buy" } } },
  ];
  it.each(malformed)("$name cannot manufacture a pre-dispatch refusal from HTTP 400", async ({ patch }) => {
    fault = { ...rawUnknown(), dispatch_outcome: "refused_before_dispatch", message: "Not placed", ...patch }; status = 400;
    const alert = await submit(); assertUnknown(alert); expect(alert).not.toHaveTextContent("1021");
  });
  it("unknown dispatch takes precedence over conflicting legacy refusal/Laya codes", async () => {
    fault = { ...rawUnknown(), code: "gtt_unsupported", reason: "Not placed. Filled.", retry_safe: false }; status = 422;
    assertUnknown(await submit()); expect(screen.queryByText("Laya denied")).not.toBeInTheDocument();
  });
  it("incomplete native error fields cannot turn HTTP 400 into no-send authority", async () => {
    status = 400; fault = { status: "error", message: "Not placed", broker_code: "1021", broker_message: "Order is completed" };
    assertUnknown(await submit());
  });
  it.each([
    { name: "oversized code", patch: { broker_code: "X".repeat(65) }, absent: "XXXXX" },
    { name: "control code", patch: { broker_code: "1021\nSECRET" }, absent: "SECRET" },
    { name: "trailing newline code", patch: { broker_code: "CANARY\n" }, absent: "CANARY" },
    { name: "object code", patch: { broker_code: { raw: "SECRET" } }, absent: "SECRET" },
    { name: "oversized native reason", patch: { broker_message: "SECRET".repeat(50) }, absent: "SECRET" },
    { name: "object native reason", patch: { broker_message: { raw: "SECRET" } }, absent: "SECRET" },
    { name: "bidi native reason", patch: { broker_message: "SECRET\u202ecompleted" }, absent: "SECRET" },
    { name: "trailing newline reason", patch: { broker_message: "CANARY\n" }, absent: "CANARY" },
  ])("$name is omitted without exposing arbitrary JSON or changing uncertainty", async ({ patch, absent }) => {
    fault = { ...rawUnknown(), ...patch, raw_response: { token: "RAW_SECRET" }, exception: "EXCEPTION_SECRET" };
    const alert = await submit(); assertUnknown(alert);
    expect(alert).not.toHaveTextContent(absent); expect(JSON.stringify(getSnapshot())).not.toMatch(/RAW_SECRET|EXCEPTION_SECRET/);
  });
  const bidiControls = [
    { name: "Arabic letter mark", control: "\u061c" },
    { name: "left-to-right mark", control: "\u200e" },
    { name: "right-to-left mark", control: "\u200f" },
    { name: "left-to-right embedding", control: "\u202a" },
    { name: "right-to-left embedding", control: "\u202b" },
    { name: "pop directional formatting", control: "\u202c" },
    { name: "left-to-right override", control: "\u202d" },
    { name: "right-to-left override", control: "\u202e" },
    { name: "left-to-right isolate", control: "\u2066" },
    { name: "right-to-left isolate", control: "\u2067" },
    { name: "first strong isolate", control: "\u2068" },
    { name: "pop directional isolate", control: "\u2069" },
  ];
  it.each(bidiControls)("omits $name from broker observations in the pad and central feed", async ({ control }) => {
    fault = { ...rawUnknown(), broker_message: `SYNTHETIC_REASON${control}NOT_FILLED` };
    const alert = await submit(); assertUnknown(alert);
    expect(alert).not.toHaveTextContent("SYNTHETIC_REASON");
    expect(alert.textContent).not.toContain(control);
    expect(alert).toHaveTextContent("Broker code: 1021.");
    expect(getSnapshot()[0]?.body).toBe(alert.textContent);
    expect(JSON.stringify(getSnapshot())).not.toContain("SYNTHETIC_REASON");
  });
  it.each(bidiControls)("omits $name from a structured refusal summary without changing its safe observations", async ({ control }) => {
    fault = { ...rawUnknown(), dispatch_outcome: "refused_before_dispatch", message: `SYNTHETIC_SUMMARY${control}NOT_SENT`, broker_message: "Protection is unavailable", broker_code: "UNSUPPORTED" }; status = 400;
    const alert = await submit();
    expect(alert).toHaveTextContent("Order refused before dispatch. No order was sent. No automatic retry.");
    expect(alert).toHaveTextContent("Broker reason (observation): Protection is unavailable. Broker code: UNSUPPORTED.");
    expect(alert).not.toHaveTextContent("SYNTHETIC_SUMMARY");
    expect(alert.textContent).not.toContain(control);
    expect(getSnapshot()[0]?.body).toBe(alert.textContent);
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(getSnapshot()[0]).not.toHaveProperty("action");
  });
  it.each(["السوق مغلق", "बाज़ार बंद है"])("retains printable native Unicode reason %s literally", async (reason) => {
    fault = { ...rawUnknown(), broker_message: reason };
    const alert = await submit(); assertUnknown(alert);
    expect(alert).toHaveTextContent(`Broker reason (observation): ${reason}. Broker code: 1021.`);
    expect(getSnapshot()[0]?.body).toBe(alert.textContent);
  });
  it.each(bidiControls)("omits an unsafe captured $name symbol whole from the notification title without changing the request", async ({ control }) => {
    suppliedSymbol = `SYNTHETIC_SYMBOL${control}NOT_FILLED`;
    props = makeWidgetPanelProps({ params: { symbol: suppliedSymbol, exchange: "NSE" } });
    fault = rawUnknown();
    const alert = await submit();
    expect(alert).toHaveTextContent("Order outcome unknown. An order may still execute. Check broker positions and orders. Do not retry automatically.");
    expect(alert.textContent).not.toContain("SYNTHETIC_SYMBOL");
    expect(events[0]?.title).toBe("Order outcome unknown");
    expect(getSnapshot()[0]?.title).toBe("Order outcome unknown");
    expect(getSnapshot()[0]?.body).toBe(alert.textContent);
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(getSnapshot()[0]).not.toHaveProperty("action");
    const write = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(write?.[1]?.body)).symbol).toBe(suppliedSymbol);
  });
  it.each(["BRK-B", "السوق", "बाज़ार"])("retains safe captured symbol %s literally in the notification title and request", async (symbol) => {
    suppliedSymbol = symbol;
    props = makeWidgetPanelProps({ params: { symbol, exchange: "NSE" } });
    fault = rawUnknown();
    const alert = await submit();
    expect(alert).toHaveTextContent("Order outcome unknown. An order may still execute. Check broker positions and orders. Do not retry automatically.");
    expect(events[0]?.title).toBe(`Order outcome unknown: BUY ${symbol}`);
    expect(getSnapshot()[0]?.title).toBe(events[0]?.title);
    expect(getSnapshot()[0]?.body).toBe(alert.textContent);
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(getSnapshot()[0]).not.toHaveProperty("action");
    const write = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(write?.[1]?.body)).symbol).toBe(symbol);
  });
  it.each([
    { name: "authentication", http: 401, body: { status: "error", message: "Synthetic server detail" }, copy: "API key invalid. Check Settings → Connection." },
    { name: "ordinary refusal", http: 403, body: { status: "error", message: "Live mode is locked. Unlock with your PIN." }, copy: "Live mode is locked. Unlock with your PIN." },
    { name: "frozen activation", http: 503, body: { status: "error", message: "INDstocks activation is unavailable. No order was sent." }, copy: "INDstocks activation is unavailable. No order was sent." },
  ])("omits an unsafe captured symbol from the $name fallback title without changing its refusal copy or request", async ({ http, body, copy }) => {
    suppliedSymbol = "INFY\u200f";
    props = makeWidgetPanelProps({ params: { symbol: suppliedSymbol, exchange: "NSE" } });
    status = http; fault = body;
    const alert = await submit();
    expect(alert).toHaveTextContent(copy);
    expect(events[0]?.title).toBe("Order failed");
    expect(getSnapshot()[0]?.title).toBe("Order failed");
    expect(getSnapshot()[0]?.body).toBe(alert.textContent);
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(getSnapshot()[0]).not.toHaveProperty("action");
    const write = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(write?.[1]?.body)).symbol).toBe(suppliedSymbol);
  });
  it("keeps an unsafe captured symbol out of an acknowledged Live title without claiming a fill or changing the request", async () => {
    suppliedSymbol = "INFY\u200f";
    props = makeWidgetPanelProps({ params: { symbol: suppliedSymbol, exchange: "NSE" } });
    status = 200; fault = { status: "success", data: "SYNTHETIC-ACK" };
    renderAccountSurface(() => <Surface />);
    await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
    await screen.findByRole("alert");
    await waitFor(() => expect(events).toHaveLength(1));
    expect(events[0]).toMatchObject({ category: "order", accountScopeKey: "live:native:kotakneo:KOTAK-OFFLINE", title: "Order requested" });
    expect(events[0]?.body).toMatch(/Submission acknowledgement is not a fill\. Check broker positions and orders\./);
    expect(getSnapshot()[0]?.title).toBe("Order requested");
    expect(getSnapshot()[0]).not.toHaveProperty("action");
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    const write = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(write?.[1]?.body)).symbol).toBe(suppliedSymbol);
  });
  it("preserves the documented 64/256 native field bounds literally", async () => {
    fault = { ...rawUnknown(), broker_code: "C".repeat(64), broker_message: "R".repeat(256) };
    const alert = await submit(); assertUnknown(alert); expect(alert).toHaveTextContent("C".repeat(64)); expect(alert).toHaveTextContent("R".repeat(256));
  });
  it("renders native markup as text rather than HTML", async () => {
    fault = { ...rawUnknown(), broker_message: '<img src=x onerror="throw 1">' };
    const alert = await submit(); assertUnknown(alert); expect(alert).toHaveTextContent('<img src=x onerror="throw 1">'); expect(alert.querySelector("img")).toBeNull();
  });
  it("does not show oversized arbitrary unstructured HTTP error text", async () => {
    fault = { status: "error", message: "SECRET".repeat(200), raw_response: { token: "SECRET" } }; status = 400;
    const alert = await submit(); expect(alert).not.toHaveTextContent("SECRET"); expect(alert.textContent?.length).toBeLessThan(700);
  });
  it.each([null, { status: "error", message: "Not placed. Try again." }, { status: "error", code: "gtt_unsupported", message: "Not placed" }])("unstructured 5xx %j is not evidence of no-send or safe retry", async (raw) => {
    fault = raw; assertUnknown(await submit());
  });
  it("connection loss cannot expose the exception or offer a duplicate-write Retry", async () => {
    writeResponse = () => Promise.reject(new TypeError("ARBITRARY_SECRET")); assertUnknown(await submit());
  });
  it("a successful-HTTP error body cannot masquerade as a local guard and disclose arbitrary exception text", async () => {
    status = 200; fault = { status: "ERROR", message: "Order blocked: ARBITRARY_SECRET" };
    const alert = await submit(); assertUnknown(alert); expect(alert).not.toHaveTextContent("ARBITRARY_SECRET");
  });
  it("server text identical to a readiness guard is not proof of a local preflight refusal", async () => {
    status = 200; fault = { status: "ERROR", message: "Your selected native broker is not available for live writes — its session may still be establishing, may need re-authentication, or may be read-only. Wait a moment, reconnect it, or choose a trading-capable broker session in Settings → Brokers." };
    assertUnknown(await submit());
  });
  it.each([
    { status: 401, fault: { status: "error", message: "secret server detail" }, visible: "API key invalid. Check Settings → Connection." },
    { status: 403, fault: { status: "error", message: "Live mode is locked. Unlock with your PIN." }, visible: "Live mode is locked. Unlock with your PIN." },
    { status: 422, fault: { status: "error", code: "exit_pending", message: "refused" }, visible: "Not placed. An exit for INFY is already pending." },
  ])("retains ordinary $status authentication and validation refusal copy", async (fixture) => {
    status = fixture.status; fault = fixture.fault; expect(await submit()).toHaveTextContent(fixture.visible);
  });
  for (const next of ["B", "Practice"] as const) for (const outcome of ["unknown_after_dispatch", "refused_before_dispatch"] as const) {
    it(`keeps late ${outcome} with A after switching to ${next}, without B/paper writes, receipts or refresh`, async () => {
      let release!: (value: Response) => void;
      writeResponse = () => new Promise((resolve) => { release = resolve; });
      fault = { ...rawUnknown(), dispatch_outcome: outcome };
      const { client } = renderAccountSurface(() => <Surface />);
      await screen.findByText("Lot: 1"); fireEvent.click(screen.getByRole("button", { name: "Place BUY Order" }));
      await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1));
      act(() => { useBrokerStore.getState().setActiveAccount(brokerAccountKey(b)); if (next === "Practice") useModeStore.setState({ mode: "practice" }); });
      expect(screen.getByRole("textbox", { name: "Symbol" })).toHaveValue("INFY");
      const targetScope = next === "Practice" ? "practice:sandbox:default" : "live:native:kotakneo:KOTAK-OFFLINE-B";
      await waitFor(() => {
        const queries = client.getQueryCache().getAll().filter((query) => query.queryKey.includes(targetScope) && ["orders", "positions"].includes(String(query.queryKey[0])));
        expect(queries).toHaveLength(2); expect(queries.every((query) => query.state.status === "success" && query.state.fetchStatus === "idle")).toBe(true);
      });
      const beforeReads = fetchMock.mock.calls.filter(([, init]) => !init?.method || init.method === "GET").map(([url]) => String(url));
      const beforeQueries = client.getQueryCache().getAll().map((query) => ({ key: query.queryKey, data: query.state.data }));
      const before = [...getSnapshot()]; const beforeEvents = [...events];
      try { await act(async () => { release(response(fault, status)); }); await waitFor(() => expect(events.length).toBe(beforeEvents.length + 1));
        expect(events.at(-1)).toMatchObject({ accountScopeKey: "live:native:kotakneo:KOTAK-OFFLINE", skipAccountRefresh: true, body: expect.stringContaining("Origin: kotakneo / KOTAK-OFFLINE · BUY INFY") });
        expect(events.at(-1)?.title).toBe(outcome === "unknown_after_dispatch" ? "Order outcome unknown: BUY INFY" : "Order refused: BUY INFY");
        expect(getSnapshot().slice(1)).toEqual(before); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        expect(fetchMock.mock.calls.filter(([, init]) => !init?.method || init.method === "GET").map(([url]) => String(url))).toEqual(beforeReads);
        expect(client.getQueryCache().getAll().map((query) => ({ key: query.queryKey, data: query.state.data }))).toEqual(beforeQueries);
        expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
      } finally { release(response(fault, status)); }
    });
  }
  it.each(["practice", "explore"] as const)("keeps %s on its existing paper review path", async (mode) => {
    setAccountRuntime({ accounts: [a, b], activeAccountId: brokerAccountKey(a), mode });
    renderAccountSurface(() => <Surface />); await screen.findByText("Lot: 1");
    fireEvent.click(screen.getByRole("button", { name: mode === "practice" ? "Practice Buy" : "Example Buy" }));
    await screen.findByRole("dialog"); fireEvent.click(screen.getByRole("button", { name: mode === "practice" ? "Confirm simulated Practice order" : "Confirm Example order" }));
    const alert = await screen.findByRole("alert"); expect(alert).not.toHaveTextContent(/Broker reason|Order outcome unknown/);
    expect(fetchMock.mock.calls.filter(([input, init]) => String(input) === writeUrl && init?.method === "POST")).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(mode === "practice" ? 1 : 0);
  });
});
