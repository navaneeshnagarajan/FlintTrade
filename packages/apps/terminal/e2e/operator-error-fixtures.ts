import type { Locator, Page, Request, TestInfo } from "@playwright/test";
import type { QueryClient } from "@tanstack/react-query";
import type { SyntheticFixtureRegistry } from "./fixture-registry";
import { FIXED_TIME, LIVE_TOKEN, expect, nativePath, registerDeskReads, registerRead, tickUntil } from "./order-flow-fixtures";

export const ERROR_BROKER = "kotakneo";
export const ERROR_A = "KOTAK-OFFLINE";
export const ERROR_B = "KOTAK-OFFLINE-B";
export const ERROR_WRITE = "/ft-api/api/v1/orders/kotakneo/place";
export const ERROR_SCOPE = "live:native:kotakneo:KOTAK-OFFLINE";
export const ERROR_BODY = { symbol: "INFY", exchange: "NSE", action: "BUY", product: "MIS", orderType: "MARKET", quantity: 1, price: 0, triggerPrice: 0, strategy: "FlintOrderPad", rationale: "", order_type: "MARKET", trigger_price: 0, broker: ERROR_BROKER, account_id: ERROR_A };
export const errorPath = (kind: string, account = ERROR_A) => nativePath(kind, account, ERROR_BROKER);
export const errorRaw = (outcome = "unknown_after_dispatch") => ({ status: "error", message: "Order dispatch failed", dispatch_outcome: outcome, retry_safe: false, affected_item: { broker: ERROR_BROKER, account_id: ERROR_A, operation: "place", symbol: "INFY", exchange: "NSE", product: "MIS", action: "BUY" }, broker_code: "1021", broker_message: "Order is completed" });
export const errorPad = (page: Page): Locator => page.locator('[data-tour-target="order-pad"]').first();

const unicodeUnknown = "Order outcome unknown. An order may still execute. Check broker positions and orders. Do not retry automatically.";
const unicodeRefused = "Order refused before dispatch. No order was sent. No automatic retry.";
const unicodeOrigin = " Origin: kotakneo / KOTAK-OFFLINE · BUY INFY (NSE / MIS).";
const unicodeCode = " Broker code: 1021.";
const printableReason = "السعر غير متاح · कीमत उपलब्ध नहीं";

// Literal synthetic response variants, not native/live correspondence evidence.
// Escape invisible marks so reviewers can inspect every adversarial byte.
export const UNICODE_ERROR_MARKS = [
  { name: "U+061C Arabic letter mark", mark: "\u061c" },
  { name: "U+200E left-to-right mark", mark: "\u200e" },
  { name: "U+200F right-to-left mark", mark: "\u200f" },
] as const;
export const UNICODE_ERROR_CASES = [
  ...UNICODE_ERROR_MARKS.map(({ name, mark }) => ({
    name: `${name} omitted from unknown native reason`, status: 500,
    raw: { ...errorRaw(), broker_message: `Order${mark} is completed` },
    expected: unicodeUnknown + unicodeOrigin + unicodeCode, refused: false,
  })),
  ...UNICODE_ERROR_MARKS.map(({ name, mark }) => ({
    name: `${name} omitted from structured refusal summary`, status: 400,
    raw: { ...errorRaw("refused_before_dispatch"), message: `Unsupported${mark} protection intent`, broker_message: "Protection is unavailable" },
    expected: unicodeRefused + unicodeOrigin + " Broker reason (observation): Protection is unavailable." + unicodeCode,
    refused: true,
  })),
  {
    name: "ordinary Arabic and Devanagari printable reason stays literal", status: 500,
    raw: { ...errorRaw(), broker_message: printableReason },
    expected: unicodeUnknown + unicodeOrigin + ` Broker reason (observation): ${printableReason}.` + unicodeCode,
    refused: false,
  },
] as const;

// Synthetic instruments selected through the ordinary native search dropdown.
// Unsafe identities are omitted whole from notices, never repaired in requests.
export const CAPTURED_ORIGIN_CASES: ReadonlyArray<{ name: string; symbol: string; safe: boolean; status?: number; raw?: unknown; title?: string; expected?: string }> = [
  { name: "U+061C Arabic letter mark", symbol: "INFY\u061c", safe: false },
  { name: "U+200E left-to-right mark", symbol: "INFY\u200e", safe: false },
  { name: "U+200F right-to-left mark", symbol: "INFY\u200f", safe: false },
  { name: "U+202A left-to-right embedding", symbol: "INFY\u202a", safe: false },
  { name: "U+202B right-to-left embedding", symbol: "INFY\u202b", safe: false },
  { name: "U+202C pop directional formatting", symbol: "INFY\u202c", safe: false },
  { name: "U+202D left-to-right override", symbol: "INFY\u202d", safe: false },
  { name: "U+202E right-to-left override", symbol: "INFY\u202e", safe: false },
  { name: "U+2066 left-to-right isolate", symbol: "INFY\u2066", safe: false },
  { name: "U+2067 right-to-left isolate", symbol: "INFY\u2067", safe: false },
  { name: "U+2068 first strong isolate", symbol: "INFY\u2068", safe: false },
  { name: "U+2069 pop directional isolate", symbol: "INFY\u2069", safe: false },
  { name: "C0 U+0001", symbol: "INFY\u0001", safe: false },
  { name: "C1 U+0080", symbol: "INFY\u0080", safe: false },
  { name: "257-character identity", symbol: "S".repeat(257), safe: false },
  { name: "literal uppercase ASCII", symbol: "INFY", safe: true },
  { name: "literal Arabic", symbol: "سهم", safe: true },
  { name: "literal Devanagari", symbol: "इन्फी", safe: true },
  { name: "256-character printable title", symbol: "S".repeat(256), safe: true },
  { name: "401 captured fallback title", symbol: "INFY\u200f", safe: false, status: 401, raw: { status: "error", message: "secret server detail" }, title: "Order failed", expected: "API key invalid. Check Settings → Connection." },
  { name: "403 captured fallback title", symbol: "INFY\u200f", safe: false, status: 403, raw: { status: "error", message: "Live mode is locked. Unlock with your PIN." }, title: "Order failed", expected: "Live mode is locked. Unlock with your PIN." },
  { name: "503 explicit activation fallback title", symbol: "INFY\u200f", safe: false, status: 503, raw: { status: "error", message: "INDstocks activation is unavailable. No order was sent." }, title: "Order failed", expected: "INDstocks activation is unavailable. No order was sent." },
] as const;

export function observeCapturedOriginReads(page: Page) {
  const getRequests: string[] = []; const pending = new Set<Request>(); const completed = new Map<string, number>();
  const path = (request: Request) => { const url = new URL(request.url()); return `${url.pathname}${url.search}`; };
  page.on("request", request => {
    if (request.method() !== "GET" || !new URL(request.url()).pathname.startsWith("/ft-api")) return;
    getRequests.push(path(request));
    if (path(request) !== "/ft-api/api/v1/ping") pending.add(request);
  });
  page.on("requestfinished", async request => {
    if (!pending.has(request)) return;
    const response = await request.response();
    if (response?.ok()) completed.set(path(request), (completed.get(path(request)) ?? 0) + 1);
    pending.delete(request);
  });
  page.on("requestfailed", request => pending.delete(request));
  return { getRequests, pending, completed };
}

export async function awaitCapturedOriginStartup(page: Page, reads: ReturnType<typeof observeCapturedOriginReads>, symbol: string, info: TestInfo): Promise<void> {
  let advanced = 0;
  const sample = () => page.evaluate(async () => {
    // Fixed import adapter; neither the path nor data enters executable code.
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<{ queryClient: QueryClient }>;
    const { queryClient } = await importModule("/src/providers/QueryProvider.tsx");
    return queryClient.getQueryCache().getAll().map(query => ({ key: query.queryKey, active: query.isActive(), status: query.state.status, fetchStatus: query.state.fetchStatus, invalidated: query.state.isInvalidated, dataUpdatedAt: query.state.dataUpdatedAt, failureCount: query.state.fetchFailureCount }));
  });
  const required = [["broker", "accounts"], ["timings"], ["positions", "list", ERROR_SCOPE], ["orders", "list", ERROR_SCOPE], ["funds", "detail", ERROR_SCOPE]];
  // Network-idle is insufficient: the mounted timings query can be waiting
  // for its normal startup retry before discovery and the scoped GET begin.
  // Drive only the existing bounded notification clock until public query
  // status AND actual successful startup bodies are complete, never refetch.
  await expect.poll(async () => {
    const queries = await sample();
    const ready = required.every(key => queries.some(query => JSON.stringify(query.key) === JSON.stringify(key) && query.status === "success" && query.fetchStatus === "idle" && !query.invalidated))
      && queries.filter(query => query.active).every(query => query.status === "success" && query.fetchStatus === "idle" && !query.invalidated)
      && reads.pending.size === 0
      && [errorPath("positions"), errorPath("orders"), errorPath("timings"), `${errorPath("search")}?query=${encodeURIComponent(symbol)}&exchange=NSE`].every(path => (reads.completed.get(path) ?? 0) >= 1);
    if (!ready && advanced < 2_000) { await page.clock.runFor(25); advanced += 25; }
    return ready;
  }, { timeout: 15_000, intervals: [50] }).toBe(true);
  await info.attach("captured-origin-completed-startup", { body: JSON.stringify({ advanced, queries: await sample(), completed: Object.fromEntries(reads.completed), pending: reads.pending.size, getRequests: reads.getRequests }, null, 2), contentType: "application/json" });
}

export function registerCapturedOriginReads(registry: SyntheticFixtureRegistry, symbol: string): void {
  registerErrorReads(registry);
  const instrument = { symbol, exchange: "NSE", lotsize: 1, tick_size: 0.05 };
  registerRead(registry, `${errorPath("search")}?query=SYNTHETIC`, { json: { status: "success", data: [instrument] } }, { minimum: 1, maximum: 2 });
  if (symbol !== "INFY") {
    registerRead(registry, `${errorPath("search")}?query=${encodeURIComponent(symbol)}&exchange=NSE`, { json: { status: "success", data: [instrument] } }, { minimum: 1, maximum: 2 });
    registerRead(registry, `${errorPath("margin")}?symbol=${encodeURIComponent(symbol)}&exchange=NSE&qty=1&product=MIS&action=BUY&pricetype=MARKET`, { json: { status: "success", data: { total_margin: 100, span_margin: 100, exposure_margin: 0 } } }, { minimum: 0, maximum: 2 });
  }
}

export async function selectCapturedOrigin(page: Page, symbol: string): Promise<void> {
  const field = errorPad(page).getByRole("textbox", { name: "Symbol", exact: true });
  await field.fill("SYNTHETIC");
  const suggestion = errorPad(page).getByRole("button", { name: `${symbol} NSE`, exact: true });
  await tickUntil(page, suggestion); await suggestion.click();
  await expect(field).toHaveValue(symbol);
  await page.clock.runFor(100);
}

// Plain glyphs may extend outside an overflow-visible line box. Require full
// native intersection, literal-range hits and every actual clipping ancestor.
export async function measureCapturedTextPainted(locator: Locator, literal?: string) {
  return locator.evaluate(async (node, literal) => {
    const ancestors: Element[] = [];
    for (let ancestor: Element | null = node; ancestor; ancestor = ancestor.parentElement) ancestors.push(ancestor);
    const clipping = ancestors.filter(ancestor => { const style = getComputedStyle(ancestor); return style.overflowX !== "visible" || style.overflowY !== "visible"; });
    // ResizeObserver reports the actual floating-point content viewport, with
    // physical scrollbar gutters excluded. Integer client sizes are evidence,
    // not a reconstruction of a fractional CSS clipping edge.
    const content = new Map<Element, { width: number; height: number }>();
    if (clipping.length) await new Promise<void>(resolve => {
      const observer = new ResizeObserver(entries => {
        for (const entry of entries) content.set(entry.target, { width: entry.contentRect.width, height: entry.contentRect.height });
        if (content.size === clipping.length) { observer.disconnect(); resolve(); }
      });
      clipping.forEach(ancestor => observer.observe(ancestor));
    });
    const bounds = node.getBoundingClientRect();
    const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    const geometry = { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
      viewport: { width: innerWidth, height: innerHeight }, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
      painted: hit !== null && (hit === node || node.contains(hit)) };
    const clips: Array<{ tag: string; overflowX: string; overflowY: string; top: number; bottom: number; left: number; right: number; scrollbarWidth: number; scrollbarHeight: number }> = [];
    for (const ancestor of ancestors) {
      const style = getComputedStyle(ancestor); const r = ancestor.getBoundingClientRect();
      const borderLeft = parseFloat(style.borderLeftWidth); const borderRight = parseFloat(style.borderRightWidth);
      const borderTop = parseFloat(style.borderTopWidth); const borderBottom = parseFloat(style.borderBottomWidth);
      const paddingX = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      const paddingY = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
      const viewport = content.get(ancestor);
      const width = viewport ? viewport.width + paddingX : r.width - borderLeft - borderRight;
      const height = viewport ? viewport.height + paddingY : r.height - borderTop - borderBottom;
      const scrollbarWidth = r.width - borderLeft - borderRight - width;
      const scrollbarHeight = r.height - borderTop - borderBottom - height;
      const leftGutter = style.scrollbarGutter.includes("both-edges") ? scrollbarWidth / 2 : style.direction === "rtl" ? scrollbarWidth : 0;
      const left = r.left + borderLeft + leftGutter; const top = r.top + borderTop;
      clips.push({ tag: ancestor.tagName, overflowX: style.overflowX, overflowY: style.overflowY,
        top, bottom: top + height, left, right: left + width, scrollbarWidth, scrollbarHeight });
    }
    const boxes: Array<{ text: string; top: number; bottom: number; left: number; right: number; painted: boolean }> = [];
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT); let child: Node | null;
    while ((child = walker.nextNode())) {
      if (!child.textContent?.trim()) continue;
      const range = document.createRange();
      if (literal !== undefined) {
        const start = child.textContent.indexOf(literal);
        if (start < 0) continue;
        range.setStart(child, start); range.setEnd(child, start + literal.length);
      } else range.selectNodeContents(child);
      for (const r of range.getClientRects()) {
        const target = document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2);
        boxes.push({ text: range.toString(), top: r.top, bottom: r.bottom, left: r.left, right: r.right,
          painted: target !== null && (target === node || node.contains(target)) });
      }
    }
    const inside = boxes.length > 0 && boxes.every((r) => r.top >= 0 && r.bottom <= innerHeight
      && r.left >= 0 && r.right <= innerWidth && r.painted && clips.every((clip) =>
        (clip.overflowY === "visible" || (r.top >= clip.top && r.bottom <= clip.bottom))
        && (clip.overflowX === "visible" || (r.left >= clip.left && r.right <= clip.right))));
    return { geometry, literal: { expected: literal, boxes, clips, inside } };
  }, literal);
}

export async function assertCapturedTextPainted(locator: Locator, info: TestInfo, label: string, literal?: string): Promise<void> {
  await locator.evaluate((node) => node.scrollIntoView({ block: "center", inline: "nearest" }));
  await expect(locator).toBeInViewport({ ratio: 1 });
  const observed = await measureCapturedTextPainted(locator, literal);
  await info.attach(`${label}-paint-geometry`, { body: JSON.stringify(observed.geometry, null, 2), contentType: "application/json" });
  await info.attach(`${label}-literal-text-geometry`, { body: JSON.stringify(observed.literal, null, 2), contentType: "application/json" });
  expect(observed.geometry.painted).toBe(true);
  expect(observed.geometry.scrollWidth).toBeLessThanOrEqual(observed.geometry.clientWidth);
  // Keep each failed native measurement red while collecting the other surface
  // and exact persistence/read/write guards in the same actual journey.
  expect.soft(observed.literal.inside).toBe(true);
}

export function registerErrorReads(registry: SyntheticFixtureRegistry, mode: "live" | "practice" = "live", switchAccount = false): void {
  registerDeskReads(registry, switchAccount, { broker: ERROR_BROKER, accountIds: [ERROR_A, ERROR_B] });
  for (const account of [ERROR_A, ERROR_B]) {
    registerRead(registry, errorPath("positions", account), { json: { status: "success", data: account === ERROR_B ? [{ symbol: "INFY", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 100, ltp: 101, pnl: 10, pnlPercent: 1 }] : [] } }, { minimum: account === ERROR_A && mode === "live" ? 1 : 0, maximum: 4 });
    registerRead(registry, errorPath("orders", account), { json: { status: "success", data: [] } }, { minimum: account === ERROR_A && mode === "live" ? 1 : 0, maximum: 4 });
    registerRead(registry, errorPath("funds", account), { json: { status: "success", data: { available_balance: 100_000, used_margin: 0, total_balance: 100_000 } } }, { minimum: 0, maximum: 2 });
    registerRead(registry, `${errorPath("search", account)}?query=INFY&exchange=NSE`, { json: { status: "success", data: [{ symbol: "INFY", exchange: "NSE", lotsize: 1, tick_size: 0.05 }] } }, { minimum: 0, maximum: 2 });
    registerRead(registry, `${errorPath("margin", account)}?symbol=INFY&exchange=NSE&qty=1&product=MIS&action=BUY&pricetype=MARKET`, { json: { status: "success", data: { total_margin: 100, span_margin: 100, exposure_margin: 0 } } }, { minimum: 0, maximum: 2 });
  }
  registerRead(registry, "/ft-api/api/v1/broker/capabilities?broker=kotakneo", { json: { status: "success", data: { broker: ERROR_BROKER, capabilities: { broker_name: "Kotak Neo", broker_type: "equity", supported_exchanges: ["NSE"] } } } }, { minimum: 0, maximum: 2 });
  registerRead(registry, "/ft-api/v1/sandbox/positions", { json: { status: "success", data: { positions: [] } } }, { minimum: 0, maximum: 4 });
  // Positive Practice placement adds its production mutation/feed book read
  // to the same four-call startup bound. Failed Live requests add none.
  registerRead(registry, "/ft-api/v1/sandbox/orders", { json: { status: "success", data: { orders: [] } } }, { minimum: 0, maximum: mode === "practice" ? 5 : 4 });
  registerRead(registry, "/ft-api/v1/sandbox/funds", { json: { status: "success", data: { funds: { starting_capital: 100_000, available_balance: 100_000, used_margin: 0, realized_pnl: 0, current_balance: 100_000 } } } }, { minimum: 0, maximum: 2 });
}

export async function mountErrorPad(page: Page, mode: "live" | "practice" = "live", narrow = false): Promise<void> {
  await page.clock.install({ time: FIXED_TIME }); await page.clock.pauseAt(FIXED_TIME);
  await page.addInitScript(({ narrow }) => {
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true"); localStorage.setItem("flinttrade:tourComplete", "true");
    localStorage.setItem("flinttrade:layouts", JSON.stringify({ state: { tabs: [{ id: "operator-error", name: "Synthetic operator errors", serializedLayout: { global: { tabEnableRename: false, tabSetEnableSingleTabStretch: true, tabSetMinWidth: 100, tabSetMinHeight: 80 }, borders: [], layout: { type: "row", weight: 100, children: [
      { type: "tabset", weight: narrow ? 45 : 65, children: [{ type: "tab", id: "error-pad", component: "orderpad", name: "Order Pad", config: { symbol: "INFY", exchange: "NSE" } }] },
      { type: "tabset", weight: narrow ? 55 : 35, children: [{ type: "tab", id: "error-book", component: "positions", name: "Positions" }] },
    ] } } }], activeTabId: "operator-error" }, version: 0 }));
    const observed = window as Window & { __presentationNotifications?: unknown[] }; observed.__presentationNotifications = [];
    window.addEventListener("flinttrade:notify", (event) => observed.__presentationNotifications?.push((event as CustomEvent<unknown>).detail));
  }, { narrow });
  await page.goto("/welcome");
  await page.evaluate(async ({ token, mode, account }) => {
    // Fixed import adapter: the function body never interpolates data.
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const auth = await importModule("/src/stores/authStore.ts") as { useAuthStore: { getState: () => { setLoggedIn: (token: string, user: string, expiry: string) => void } } };
    const modes = await importModule("/src/stores/modeStore.ts") as { useModeStore: { getState: () => { setMode: (mode: "live" | "practice") => void } } };
    const brokers = await importModule("/src/stores/brokerStore.ts") as { useBrokerStore: { getState: () => { setActiveAccount: (selector: string) => void } } };
    auth.useAuthStore.getState().setLoggedIn(token, "synthetic-order-flow-operator", ""); modes.useModeStore.getState().setMode(mode); brokers.useBrokerStore.getState().setActiveAccount(`native:kotakneo:${account}`);
    await Promise.all([importModule("/src/routes/TerminalRoute.tsx"), importModule("/src/widgets/trading/OrderPad/OrderPadWidget.tsx"), importModule("/src/widgets/trading/Positions/PositionsWidget.tsx")]);
    window.history.pushState(null, "", "/trade"); window.dispatchEvent(new PopStateEvent("popstate"));
  }, { token: LIVE_TOKEN, mode, account: ERROR_A });
  await expect(page).toHaveURL(/\/trade$/); await tickUntil(page, errorPad(page).getByText("Lot: 1", { exact: true }));
}

export async function assertPainted(locator: Locator, info: TestInfo, label: string): Promise<void> {
  await locator.evaluate((node) => node.scrollIntoView({ block: "center", inline: "nearest" }));
  await expect(locator).toBeInViewport({ ratio: 1 });
  const geometry = await locator.evaluate((node) => { const r = node.getBoundingClientRect(); const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return { x: r.x, y: r.y, width: r.width, height: r.height, scrollWidth: node.scrollWidth, clientWidth: node.clientWidth, painted: hit !== null && (hit === node || node.contains(hit)) }; });
  await info.attach(`${label}-paint-geometry`, { body: JSON.stringify(geometry, null, 2), contentType: "application/json" });
  expect(geometry.painted).toBe(true); expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  const textGeometry = await locator.evaluate((node) => {
    const bounds = node.getBoundingClientRect(); const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT); const boxes: Array<{ text: string; top: number; bottom: number; left: number; right: number }> = [];
    let text: Node | null;
    while ((text = walker.nextNode())) { if (!text.textContent?.trim()) continue; const range = document.createRange(); range.selectNodeContents(text); for (const r of range.getClientRects()) boxes.push({ text: text.textContent, top: r.top, bottom: r.bottom, left: r.left, right: r.right }); }
    return { boxes, inside: boxes.length > 0 && boxes.every((r) => r.top >= bounds.top && r.bottom <= bounds.bottom && r.left >= bounds.left && r.right <= bounds.right) };
  });
  await info.attach(`${label}-literal-text-geometry`, { body: JSON.stringify(textGeometry, null, 2), contentType: "application/json" });
  expect(textGeometry.inside).toBe(true);
}
