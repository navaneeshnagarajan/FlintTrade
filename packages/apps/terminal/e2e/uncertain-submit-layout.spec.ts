import type { Locator, Page, Request } from "@playwright/test";
import { registerSystemDiagnosticsRead } from "./visual/desk-mocks";
import {
  ACCOUNT_A,
  BROKER,
  expect,
  mountWidget,
  nativePath,
  positionSurface,
  recordLostSubmit,
  registerAccountBooks,
  registerDeskReads,
  registerRead,
  seedInstrumentTick,
  test,
  tickUntil,
} from "./order-flow-fixtures";
import { registerExploreAdvisorStatusProbe, registerOperatorStatusProbes } from "./fixture-registry";

const UNKNOWN = "Order status unknown. Check Orders before trying again.";
const CE = "NIFTY27AUG26100CE";
const PLACE = "/ft-api/api/v1/orders/place";
const LIVE_PLACE = "/ft-api/api/v1/orders/dhan/place";
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 2560, height: 1440 },
] as const;

const LIVE_AUTHORITY_TOKEN = [
  Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
  Buffer.from(JSON.stringify({
    sub: "synthetic-order-pad-operator", mode: "live", live_mode_unlocked: true, exp: 4_102_444_800,
  })).toString("base64url"),
  "synthetic-e2e-signature",
].join(".");

const OPEN_ORDER = {
  orderid: "ORD123",
  symbol: "NIFTY24APR24000CE",
  exchange: "NFO",
  action: "BUY",
  quantity: 75,
  price: 150,
  pricetype: "LIMIT",
  product: "MIS",
  order_status: "open",
};

const FUNDS = {
  status: "success",
  data: {
    funds: {
      starting_capital: 100_000,
      available_balance: 100_000,
      used_margin: 0,
      realized_pnl: 0,
      current_balance: 100_000,
      ledger_balance: 100_000,
      futures_mtm_in_ledger: false,
    },
  },
};

type Box = { x: number; y: number; width: number; height: number };

async function collectBoxes(locators: Locator[]): Promise<Box[]> {
  const boxes: Box[] = [];
  for (const locator of locators) {
    await expect(locator).toBeVisible();
    const box = await locator.boundingBox();
    expect(box, "visible control should have a bounding box").not.toBeNull();
    boxes.push(box!);
  }
  return boxes;
}

function expectUnmoved(before: Box[], after: Box[], label: string, tolerance = 1): void {
  expect(after, label).toHaveLength(before.length);
  before.forEach((start, index) => {
    const end = after[index]!;
    (["x", "y", "width", "height"] as const).forEach((edge) => {
      expect(
        Math.abs(end[edge] - start[edge]),
        `${label} ${index} ${edge}`,
      ).toBeLessThanOrEqual(tolerance);
    });
  });
}


async function rereadOrderBook(page: Page): Promise<void> {
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("flinttrade:ordersChanged"));
  });
}

/** The element is inside the viewport and nothing, such as the status footer, paints over it. */
async function expectOnScreenAndUncovered(page: Page, locator: Locator, label: string): Promise<Box> {
  await expect(locator, label).toBeVisible();
  const box = (await locator.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.y, `${label} top`).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height, `${label} bottom`).toBeLessThanOrEqual(viewport.height);
  const covered = await locator.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const points = [
      [rect.left + 2, rect.top + rect.height / 2],
      [rect.left + rect.width / 2, rect.top + rect.height / 2],
      [rect.right - 2, rect.top + rect.height / 2],
    ];
    for (const [x, y] of points) {
      const hit = document.elementFromPoint(x!, y!);
      if (!hit || !(node === hit || node.contains(hit)
        || (node instanceof HTMLButtonElement && node.disabled && hit === node.parentElement))) {
        return hit ? `${hit.tagName}.${String(hit.className).slice(0, 80)} ${hit.textContent?.slice(0, 40) ?? ""}` : "nothing";
      }
    }
    return null;
  });
  expect(covered, `${label} is painted over`).toBeNull();
  return box;
}

/** The line fits its reserved slot: Open Orders stays on one line and nothing is clipped. */
async function expectLineFits(slot: Locator, label: string): Promise<void> {
  const fit = await slot.evaluate((node) => {
    const button = Array.from(node.querySelectorAll("button")).find((el) => el.textContent?.trim() === "Open Orders");
    const lineHeight = button ? parseFloat(getComputedStyle(button).lineHeight) || 0 : 0;
    const rect = button?.getBoundingClientRect();
    const slotRect = node.getBoundingClientRect();
    return {
      buttonHeight: rect?.height ?? -1,
      lineHeight,
      clipped: node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1,
      inside: rect ? rect.top >= slotRect.top - 0.5 && rect.bottom <= slotRect.bottom + 0.5 && rect.right <= slotRect.right + 0.5 : false,
    };
  });
  expect(fit.buttonHeight, `${label} Open Orders exists`).toBeGreaterThan(0);
  expect(fit.buttonHeight, `${label} Open Orders wraps`).toBeLessThanOrEqual(Math.max(fit.lineHeight, 16) + 2);
  expect(fit.clipped, `${label} slot clips the line`).toBe(false);
  expect(fit.inside, `${label} Open Orders sits inside the slot`).toBe(true);
}

async function setScalperPanelWidth(slot: Locator, width: number): Promise<void> {
  await slot.evaluate((node, widthPx) => {
    const panel = node.closest("[data-scalper-panel]") as HTMLElement | null;
    if (!panel) throw new Error("Scalper panel not found");
    panel.style.width = `${widthPx}px`;
    panel.style.maxWidth = `${widthPx}px`;
    panel.style.flex = `0 0 ${widthPx}px`;
  }, width);
}

async function waitForScalperUnknown(page: Page, slot: Locator): Promise<void> {
  const openOrders = slot.getByRole("button", { name: "Open Orders" });
  let advanced = 0;
  await expect.poll(async () => {
    if (advanced < 2_000) {
      await page.clock.runFor(25);
      advanced += 25;
    }
    return openOrders.isVisible();
  }, { timeout: 15_000, intervals: [50] }).toBe(true);
  const sentence = slot.getByText(UNKNOWN, { exact: true });
  if (await sentence.isVisible()) {
    await expect(sentence).toBeVisible();
    return;
  }
  await expect(slot.getByRole("status")).toHaveAttribute("title", UNKNOWN);
}

async function expectLockHeld(page: Page, buy: Locator, line: Locator, ms = 3_000): Promise<void> {
  const started = Date.now();
  await expect(line).toBeVisible();
  await expect(buy).toBeDisabled();
  while (Date.now() - started < ms) {
    await expect(line).toBeVisible();
    await expect(buy).toBeDisabled();
    await page.waitForTimeout(200);
  }
  expect(Date.now() - started).toBeGreaterThanOrEqual(ms);
}

function expectAuthenticatedGet(request: Request): void {
  expect(request.headers()["authorization"]).toBe(`Bearer ${LIVE_AUTHORITY_TOKEN}`);
  expect(request.postData()).toBeNull();
}

async function seedOrderPadWorkspace(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem("flinttrade:app-layouts:v1:terminal", JSON.stringify({
      Current: {
        global: { tabEnableRename: false, tabSetEnableSingleTabStretch: true, tabSetMinWidth: 100, tabSetMinHeight: 80 },
        borders: [],
        layout: {
          type: "row", weight: 100,
          children: [{
            type: "tabset", weight: 100,
            children: [{ type: "tab", id: "practice-order-pad-widget", component: "orderpad", name: "Order Pad" }],
          }],
        },
      },
    }));
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  });
}

async function installPracticeAuthority(page: Page): Promise<void> {
  await page.evaluate(async (token) => {
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const auth = await importModule("/src/stores/authStore.ts") as {
      useAuthStore: { getState: () => { setLoggedIn: (jwt: string, username: string, expiresAt: string) => void } };
    };
    const mode = await importModule("/src/stores/modeStore.ts") as {
      useModeStore: { getState: () => { setMode: (mode: "practice") => void } };
    };
    auth.useAuthStore.getState().setLoggedIn(token, "synthetic-order-pad-operator", "");
    mode.useModeStore.getState().setMode("practice");
    window.history.pushState(null, "", "/trade");
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, LIVE_AUTHORITY_TOKEN);
}

function registerPracticePadReads(
  syntheticApi: Parameters<typeof registerSystemDiagnosticsRead>[0],
  options: { delayOrdersAfterSubmit?: number; submitted?: { current: boolean } } = {},
): { orderReads: { count: number; startedAt: number[]; completedAt: number[] } } {
  const orderReads = { count: 0, startedAt: [] as number[], completedAt: [] as number[] };
  const poll = { minimum: 0, maximum: 80 };
  const submitted = options.submitted ?? { current: false };
  registerSystemDiagnosticsRead(syntheticApi, LIVE_AUTHORITY_TOKEN);
  syntheticApi.register({
    name: "list native accounts for Practice market-data resolution",
    method: "GET",
    path: "/ft-api/api/v1/native/accounts",
    expectedCalls: poll,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return { json: { accounts: [] } };
    },
  });
  syntheticApi.register({
    name: "read Practice sandbox funds",
    method: "GET",
    path: "/ft-api/v1/sandbox/funds",
    expectedCalls: poll,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return { json: FUNDS };
    },
  });
  syntheticApi.register({
    name: "read empty Practice sandbox positions",
    method: "GET",
    path: "/ft-api/v1/sandbox/positions",
    expectedCalls: poll,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return { json: { status: "success", data: { positions: [] } } };
    },
  });
  syntheticApi.register({
    name: "read Practice sandbox orders",
    method: "GET",
    path: "/ft-api/v1/sandbox/orders",
    expectedCalls: poll,
    handler: async (request) => {
      expectAuthenticatedGet(request);
      const startedAt = Date.now();
      orderReads.startedAt.push(startedAt);
      orderReads.count += 1;
      if (submitted.current && options.delayOrdersAfterSubmit) {
        await new Promise((resolve) => setTimeout(resolve, options.delayOrdersAfterSubmit));
      }
      orderReads.completedAt.push(Date.now());
      return { json: { status: "success", data: { orders: [] } } };
    },
  });
  registerExploreAdvisorStatusProbe(syntheticApi, { expectedCalls: poll });
  registerOperatorStatusProbes(syntheticApi, { expectedCalls: poll });
  syntheticApi.register({
    name: "welcome and Mode menu Live-arm status",
    method: "GET",
    path: "/ft-api/v1/auth/status",
    expectedCalls: poll,
    handler: (request) => {
      expect(request.postData()).toBeNull();
      const authorization = request.headers()["authorization"];
      if (authorization !== undefined) {
        expect(authorization).toBe(`Bearer ${LIVE_AUTHORITY_TOKEN}`);
      }
      return { json: { status: "success", data: { is_setup: true, is_locked: false, has_pin: false, totp_enabled: false } } };
    },
  });
  syntheticApi.register({
    name: "read inactive safety configuration",
    method: "GET",
    path: "/ft-api/api/v1/safety/config",
    expectedCalls: poll,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return { json: { status: "success", data: { l1_order: {}, l2_position: {}, l3_portfolio: {}, l4_pnl: {}, l5_kill: {} } } };
    },
  });
  syntheticApi.register({
    name: "read broker capabilities without a connected account",
    method: "GET",
    path: "/ft-api/api/v1/broker/capabilities",
    expectedCalls: poll,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return {
        json: {
          status: "success",
          data: {
            broker_name: "Practice",
            broker_type: "multi",
            supported_exchanges: ["NSE", "BSE", "NFO", "BFO", "MCX"],
            features: {},
          },
        },
      };
    },
  });
  return { orderReads };
}

async function confirmLostPracticeBuy(
  page: Page,
  beforeConfirm?: () => void,
  beforeBuy?: () => Promise<void>,
): Promise<void> {
  await page.goto("/welcome");
  await installPracticeAuthority(page);
  await page.evaluate(async () => {
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<unknown>;
    await Promise.all([
      importModule("/src/routes/UnifiedAppRoute.tsx"),
      importModule("/src/widgets/trading/OrderPad/OrderPadWidget.tsx"),
    ]);
  });
  await expect(page).toHaveURL(/\/terminal$/);
  const limit = page.getByRole("radio", { name: "LIMIT" });
  await expect(limit).toBeVisible({ timeout: 20_000 });
  await limit.click();
  await page.getByRole("spinbutton", { name: "Price", exact: true }).fill("123.45");
  await beforeBuy?.();
  await page.getByRole("button", { name: "Practice Buy" }).click();
  const review = page.getByRole("dialog", { name: "Review Practice order" });
  await expect(review).toBeVisible();
  beforeConfirm?.();
  await review.getByRole("button", { name: "Confirm simulated Practice order" }).click();
}

function registerScalperReads(syntheticApi: Parameters<typeof registerDeskReads>[0]): void {
  registerDeskReads(syntheticApi, false, { marketScopeVisits: 12 });
  registerAccountBooks(syntheticApi, {
    positionCalls: { minimum: 0, maximum: 8 },
    orderCalls: { minimum: 0, maximum: 16 },
  });
  registerRead(syntheticApi, "/ft-api/api/v1/broker/capabilities?broker=dhan", {
    json: { status: "success", data: { capabilities: { historical_intervals: ["5m", "1D"] } } },
  }, { minimum: 0, maximum: 8 });
  registerRead(syntheticApi, `${nativePath("symbol")}?query=${CE}&exchange=NFO`, {
    json: { status: "success", data: [{ symbol: CE, exchange: "NFO", lotsize: 65, tick_size: 0.05, name: CE }] },
  }, { minimum: 0, maximum: 4 });
  registerRead(syntheticApi, `${nativePath("search")}?query=${CE}&exchange=NFO`, {
    json: { status: "success", data: [{ symbol: CE, exchange: "NFO", lotsize: 65, tick_size: 0.05, name: CE }] },
  }, { minimum: 0, maximum: 4 });
  registerRead(syntheticApi, `/ft-api/api/v1/safety/config?broker=dhan&account_id=${ACCOUNT_A}`, {
    json: { status: "success", data: { l1_order: {}, l2_position: {}, l3_portfolio: {}, l4_pnl: {}, l5_kill: {} } },
  }, { minimum: 0, maximum: 2 });
  const historyPath = (symbol: string, exchange: string) =>
    `${nativePath("history")}?symbol=${symbol}&exchange=${exchange}&interval=5m&start_date=2026-07-12&end_date=2026-08-11`;
  for (const symbol of [CE, "NIFTY27AUG26100PE"]) {
    registerRead(syntheticApi, `${nativePath("quotes")}?symbol=${symbol}&exchange=NFO`, {
      json: { status: "success", data: { symbol, exchange: "NFO", ltp: 12, prev_close: 12 } },
    }, { minimum: 0, maximum: 8 });
    registerRead(syntheticApi, historyPath(symbol, "NFO"), {
      json: { status: "success", data: [] },
    }, { minimum: 0, maximum: 4 });
  }
  registerRead(syntheticApi, historyPath("NIFTY", "NSE_INDEX"), {
    json: { status: "success", data: [] },
  }, { minimum: 0, maximum: 4 });
  registerRead(syntheticApi, "/ft-api/api/v1/screener/lot-size?symbol=NIFTY&exchange=NFO", {
    json: { symbol: "NIFTY", exchange: "NFO", lot_size: 65, is_sample_data: false },
  }, { minimum: 0, maximum: 4 });
}

function registerQuickTradeReads(syntheticApi: Parameters<typeof registerDeskReads>[0]): void {
  registerDeskReads(syntheticApi, false, { marketScopeVisits: 8 });
  registerAccountBooks(syntheticApi, {
    positionCalls: { minimum: 0, maximum: 8 },
    orderCalls: { minimum: 0, maximum: 16 },
  });
  registerRead(syntheticApi, `${nativePath("search")}?query=RELIANCE&exchange=NSE`, {
    json: { status: "success", data: [{ symbol: "RELIANCE", exchange: "NSE", lotsize: 1, tick_size: 0.05, name: "RELIANCE" }] },
  }, { minimum: 0, maximum: 8 });
}

function registerOptionChainReads(syntheticApi: Parameters<typeof registerDeskReads>[0]): void {
  registerDeskReads(syntheticApi, false, { marketScopeVisits: 8 });
  registerAccountBooks(syntheticApi, {
    positionCalls: { minimum: 0, maximum: 8 },
    orderCalls: { minimum: 0, maximum: 16 },
  });
  const strikes = [];
  for (let strike = 24_800; strike <= 25_200; strike += 50) {
    strikes.push({
      strike_price: strike,
      ce_ltp: Math.max(5, 25_000 - strike + 120), ce_bid: 1, ce_ask: 2, ce_oi: 1_000, ce_volume: 100,
      pe_ltp: Math.max(5, strike - 25_000 + 120), pe_bid: 1, pe_ask: 2, pe_oi: 1_000, pe_volume: 100,
    });
  }
  const chain = { json: { status: "success", data: { underlying_ltp: 25_000, atm_strike: 25_000, expiry: "27AUG26", strikes } } };
  registerRead(syntheticApi, `${nativePath("optionchain")}?underlying=NIFTY&exchange=NFO`, chain, { minimum: 0, maximum: 8 });
  registerRead(syntheticApi, `${nativePath("optionchain")}?underlying=NIFTY&exchange=NFO&expiry=27AUG26`, chain, { minimum: 0, maximum: 8 });
  registerRead(syntheticApi, nativePath("scrip_master"), { json: { status: "success", data: [] } }, { minimum: 0, maximum: 4 });
  registerRead(syntheticApi, `${nativePath("search")}?query=NIFTY&exchange=NFO`, {
    json: { status: "success", data: [{ symbol: "NIFTY", exchange: "NFO", lotsize: 65, tick_size: 0.05, name: "NIFTY" }] },
  }, { minimum: 0, maximum: 8 });
  syntheticApi.register({
    name: "Option Chain max pain", method: "POST", path: "/ft-api/api/v1/maxpain",
    expectedCalls: { minimum: 0, maximum: 8 },
    handler: () => ({ json: { status: "success", data: { max_pain_strike: 25_000, total_loss_at_max_pain: 0, strike_losses: [] } } }),
  });
}

function registerLadderReads(syntheticApi: Parameters<typeof registerDeskReads>[0]): void {
  registerDeskReads(syntheticApi, false, { marketScopeVisits: 12 });
  registerAccountBooks(syntheticApi, {
    positionCalls: { minimum: 0, maximum: 8 },
    orderCalls: { minimum: 0, maximum: 16 },
  });
  registerRead(syntheticApi, `${nativePath("quotes")}?symbol=NIFTY&exchange=NSE`, {
    json: { status: "success", data: { symbol: "NIFTY", exchange: "NSE", ltp: 24_000, prev_close: 24_000 } },
  }, { minimum: 0, maximum: 16 });
  registerRead(syntheticApi, `${nativePath("depth")}?symbol=NIFTY&exchange=NSE`, {
    json: {
      status: "success",
      data: {
        buy: [
          { price: 23_999.95, quantity: 150, orders: 3 },
          { price: 23_999.90, quantity: 80, orders: 2 },
        ],
        sell: [
          { price: 24_000.05, quantity: 120, orders: 2 },
          { price: 24_000.10, quantity: 90, orders: 1 },
        ],
      },
    },
  }, { minimum: 0, maximum: 16 });
  registerRead(syntheticApi, `${nativePath("search")}?query=NIFTY&exchange=NSE`, {
    json: { status: "success", data: [{ symbol: "NIFTY", exchange: "NSE", lotsize: 1, tick_size: 0.05, name: "NIFTY" }] },
  }, { minimum: 0, maximum: 8 });
  registerRead(syntheticApi, "/ft-api/api/v1/screener/lot-size?symbol=NIFTY&exchange=NSE", {
    json: { symbol: "NIFTY", exchange: "NSE", lot_size: 1, is_sample_data: false },
  }, { minimum: 0, maximum: 8 });
}

function registerOrdersReads(syntheticApi: Parameters<typeof registerDeskReads>[0]): void {
  registerDeskReads(syntheticApi, false, { marketScopeVisits: 8 });
  registerAccountBooks(syntheticApi, {
    orders: { json: { status: "success", data: [OPEN_ORDER] } },
    positionCalls: { minimum: 0, maximum: 8 },
    orderCalls: { minimum: 1, maximum: 16 },
  });
}

test.describe("lost Practice submit holds the lock in real time", () => {
  test.describe("immediate empty re-read", () => {
    test.use({
      benignConsoleErrors: [{
        text: "Failed to load resource: net::ERR_CONNECTION_RESET",
        url: `http://localhost:5173${PLACE}`,
        expectedCalls: 1,
      }],
    });

    test("keeps Buy disabled and the unknown line visible for at least 3s", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      await seedOrderPadWorkspace(page);
      const { orderReads } = registerPracticePadReads(syntheticApi);
      await page.route(`**${PLACE}`, async (route) => { await route.abort("connectionreset"); });
      await confirmLostPracticeBuy(page);
      const line = page.getByTestId("order-pad-status-unknown");
      const buy = page.getByRole("button", { name: "Practice Buy" });
      await expect(line).toBeVisible({ timeout: 15_000 });
      await expect(line.getByRole("button", { name: "Open Orders" })).toBeVisible();
      const watermark = orderReads.startedAt.length;
      await rereadOrderBook(page);
      await expectLockHeld(page, buy, line, 3_000);
      const postLoss = orderReads.startedAt
        .map((started, index) => ({ started, duration: (orderReads.completedAt[index] ?? started) - started }))
        .slice(watermark);
      expect(postLoss.some((read) => read.duration < 500)).toBe(true);
    });
  });

  test.describe("order read delayed by about 2s", () => {
    test.use({
      benignConsoleErrors: [{
        text: "Failed to load resource: net::ERR_CONNECTION_RESET",
        url: `http://localhost:5173${PLACE}`,
        expectedCalls: 1,
      }],
    });

    test("keeps Buy disabled through the delayed empty read for at least 3s", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      await seedOrderPadWorkspace(page);
      const submitted = { current: false };
      const { orderReads } = registerPracticePadReads(syntheticApi, {
        delayOrdersAfterSubmit: 2_000,
        submitted,
      });
      await page.route(`**${PLACE}`, async (route) => { await route.abort("connectionreset"); });
      await confirmLostPracticeBuy(page);
      const line = page.getByTestId("order-pad-status-unknown");
      const buy = page.getByRole("button", { name: "Practice Buy" });
      await expect(line).toBeVisible({ timeout: 15_000 });
      const watermark = orderReads.startedAt.length;
      submitted.current = true;
      await rereadOrderBook(page);
      await expectLockHeld(page, buy, line, 3_000);
      const delayed = orderReads.startedAt
        .map((started, index) => (orderReads.completedAt[index] ?? started) - started)
        .slice(watermark)
        .some((duration) => duration >= 1_800);
      expect(delayed).toBe(true);
    });
  });
  test.describe("scheduled settle read", () => {
    test.use({
      benignConsoleErrors: [{
        text: "Failed to load resource: net::ERR_CONNECTION_RESET",
        url: `http://localhost:5173${PLACE}`,
        expectedCalls: 1,
      }],
    });

    test("one order-book read about 5s after the loss clears the lock within 5-7s", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      await seedOrderPadWorkspace(page);
      const { orderReads } = registerPracticePadReads(syntheticApi);
      let lostAt = 0;
      await page.route(`**${PLACE}`, async (route) => {
        lostAt = Date.now();
        await route.abort("connectionreset");
      });
      await confirmLostPracticeBuy(page);
      const line = page.getByTestId("order-pad-status-unknown").getByText(UNKNOWN);
      const buy = page.getByRole("button", { name: "Practice Buy" });
      await expect(line).toBeVisible({ timeout: 15_000 });
      expect(lostAt).toBeGreaterThan(0);
      while (Date.now() < lostAt + 4_700) {
        await expect(line).toBeVisible();
        await expect(buy).toBeDisabled();
        await page.waitForTimeout(150);
      }
      await expect(line).toBeHidden({ timeout: 7_000 - (Date.now() - lostAt) });
      const unlockedAfter = Date.now() - lostAt;
      await expect(buy).toBeEnabled();
      expect(unlockedAfter).toBeGreaterThanOrEqual(5_000);
      expect(unlockedAfter).toBeLessThan(7_000);
      const settling = orderReads.startedAt.filter((started) => started >= lostAt + 5_000 && started <= lostAt + 6_500);
      expect(settling.length).toBeGreaterThanOrEqual(1);
    });
  });
});

for (const viewport of VIEWPORTS) {
  test.describe(`Order Pad unknown line on screen at ${viewport.width}×${viewport.height}`, () => {
    test.use({
      viewport,
      benignConsoleErrors: [{
        text: "Failed to load resource: net::ERR_CONNECTION_RESET",
        url: `http://localhost:5173${PLACE}`,
        expectedCalls: 1,
      }],
    });

    test("Buy and the unknown line stay inside the viewport, uncovered and unmoved", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      await seedOrderPadWorkspace(page);
      registerPracticePadReads(syntheticApi);
      await page.route(`**${PLACE}`, async (route) => { await route.abort("connectionreset"); });
      const buy = page.getByRole("button", { name: "Practice Buy" });
      let before: Box | null = null;
      await confirmLostPracticeBuy(page, undefined, async () => {
        before = await expectOnScreenAndUncovered(page, buy, `Buy before at ${viewport.width}`);
      });
      const slot = page.getByTestId("order-pad-status-unknown");
      const line = slot.getByText(UNKNOWN);
      await expect(line).toBeVisible({ timeout: 15_000 });
      await expectOnScreenAndUncovered(page, line, `unknown line at ${viewport.width}`);
      await expectOnScreenAndUncovered(page, slot.getByRole("button", { name: "Open Orders" }), `Open Orders at ${viewport.width}`);
      const after = await expectOnScreenAndUncovered(page, buy, `Buy after at ${viewport.width}`);
      expectUnmoved([before!], [after], `Order Pad Buy ${viewport.width}`);
    });
  });
}

for (const viewport of VIEWPORTS) {
  test.describe(`no layout shift at ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport });

    test("Scalper Buy/Sell stay put when the unknown line appears", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerScalperReads(syntheticApi);
      await mountWidget(page, "scalper");
      await page.clock.runFor(5_000);
      await expect(page.getByText("1 (65)", { exact: true })).toBeAttached({ timeout: 15_000 });
      const controls = [
        page.getByRole("button", { name: /^Buy CE/ }).first(),
        page.getByRole("button", { name: /^Sell CE/ }).first(),
        page.getByRole("button", { name: /^Buy PE/ }).first(),
        page.getByRole("button", { name: /^Sell PE/ }).first(),
      ];
      const before = await collectBoxes(controls);
      await recordLostSubmit(page, { key: `NFO:${CE}`, symbol: CE, exchange: "NFO", action: "BUY", quantity: 65 });
      const slot = page.getByTestId("scalper-ce-status-slot");
      await waitForScalperUnknown(page, slot);
      expectUnmoved(before, await collectBoxes(controls), `scalper ${viewport.width}`);
      await expectLineFits(slot, `scalper ${viewport.width}`);
    });

    test("Ladder Buy/Sell and price rows stay put when the unknown line appears", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerLadderReads(syntheticApi);
      await mountWidget(page, "orderladder", false, { params: { symbol: "NIFTY", exchange: "NSE", tick: 0.05 } });
      await seedInstrumentTick(page, "NSE", "NIFTY", 24_000);
      await page.clock.runFor(100);
      const ladder = page.getByLabel("Price ladder");
      await expect(ladder).toBeVisible({ timeout: 15_000 });
      await expect(ladder.getByLabel("Price level", { exact: false }).first()).toBeVisible({ timeout: 15_000 });
      const rows = ladder.getByLabel("Price level", { exact: false });
      const buyButtons = page.getByRole("button", { name: /^(Buy |Place buy )/i });
      const sellButtons = page.getByRole("button", { name: /^(Sell |Place sell )/i });
      const beforeRows = await collectBoxes(await rows.all());
      const beforeBuy = await collectBoxes((await buyButtons.all()).slice(0, 6));
      const beforeSell = await collectBoxes((await sellButtons.all()).slice(0, 6));
      await recordLostSubmit(page, { key: "NSE:NIFTY", symbol: "NIFTY", exchange: "NSE", action: "BUY", quantity: 25 });
      const line = page.getByTestId("ladder-status-unknown").getByText(UNKNOWN);
      let advanced = 0;
      await expect.poll(async () => {
        if (advanced < 2_000) {
          await page.clock.runFor(25);
          advanced += 25;
        }
        return line.isVisible();
      }, { timeout: 15_000, intervals: [50] }).toBe(true);
      expectUnmoved(beforeRows, await collectBoxes(await rows.all()), `ladder rows ${viewport.width}`);
      expectUnmoved(beforeBuy, await collectBoxes((await buyButtons.all()).slice(0, 6)), `ladder buy ${viewport.width}`);
      expectUnmoved(beforeSell, await collectBoxes((await sellButtons.all()).slice(0, 6)), `ladder sell ${viewport.width}`);
    });

    test("Ladder price rows never move when the locked price changes, and the line sits outside the list", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerLadderReads(syntheticApi);
      await mountWidget(page, "orderladder", false, { params: { symbol: "NIFTY", exchange: "NSE", tick: 0.05 } });
      await seedInstrumentTick(page, "NSE", "NIFTY", 24_000);
      await page.clock.runFor(100);
      const ladder = page.getByLabel("Price ladder");
      await expect(ladder.getByLabel("Price level", { exact: false }).first()).toBeVisible({ timeout: 15_000 });
      const rows = ladder.getByLabel("Price level", { exact: false });
      const slot = page.getByTestId("ladder-status-unknown");
      await expect(ladder.getByTestId("ladder-status-unknown")).toHaveCount(0);
      const idleRows = await collectBoxes(await rows.all());
      const idleSlot = await collectBoxes([slot]);
      const tick = async (locator: Locator) => {
        let advanced = 0;
        await expect.poll(async () => {
          if (advanced < 2_000) {
            await page.clock.runFor(25);
            advanced += 25;
          }
          return locator.isVisible();
        }, { timeout: 15_000, intervals: [50] }).toBe(true);
      };
      await recordLostSubmit(page, { key: "NSE:NIFTY@24000.1", symbol: "NIFTY", exchange: "NSE", action: "BUY", quantity: 25 });
      await tick(slot.getByText(UNKNOWN));
      await expect(ladder.getByTestId("ladder-status-unknown")).toHaveCount(0);
      await expect(ladder.getByText(UNKNOWN)).toHaveCount(0);
      expectUnmoved(idleRows, await collectBoxes(await rows.all()), `ladder rows, first locked price ${viewport.width}`);
      expectUnmoved(idleSlot, await collectBoxes([slot]), `ladder slot ${viewport.width}`);
      await expectLineFits(slot, `ladder ${viewport.width}`);
      await recordLostSubmit(page, { key: "NSE:NIFTY@23999.9", symbol: "NIFTY", exchange: "NSE", action: "SELL", quantity: 25 });
      await page.clock.runFor(200);
      expectUnmoved(idleRows, await collectBoxes(await rows.all()), `ladder rows, second locked price ${viewport.width}`);
      expectUnmoved(idleSlot, await collectBoxes([slot]), `ladder slot after second lock ${viewport.width}`);
    });

    test("a locked Positions row keeps its height, with Open Orders on the row and the sentence in its tooltip", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerDeskReads(syntheticApi);
      registerAccountBooks(syntheticApi, { positionCalls: { minimum: 1, maximum: 8 }, orderCalls: { minimum: 0, maximum: 16 } });
      await mountWidget(page, "positions");
      const surface = positionSurface(page);
      const squareOff = surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA", exact: true });
      await tickUntil(page, squareOff);
      const row = surface.getByRole("row").filter({ hasText: "SYNTHETIC-ALPHA" }).first();
      const before = await collectBoxes([row, squareOff]);
      await recordLostSubmit(page, { key: "NSE:SYNTHETIC-ALPHA", symbol: "SYNTHETIC-ALPHA", exchange: "NSE", action: "SELL", quantity: 10 });
      const link = row.getByRole("button", { name: "Open Orders" });
      await tickUntil(page, link);
      await expect(squareOff).toBeDisabled();
      await expect(link).toHaveAttribute("title", UNKNOWN);
      await expect(link).toHaveAccessibleDescription(UNKNOWN);
      expectUnmoved(before, await collectBoxes([row, squareOff]), `positions row ${viewport.width}`);
      const linkBox = (await link.boundingBox())!;
      const rowBox = (await row.boundingBox())!;
      expect(linkBox.y).toBeGreaterThanOrEqual(rowBox.y - 0.5);
      expect(linkBox.y + linkBox.height).toBeLessThanOrEqual(rowBox.y + rowBox.height + 0.5);
    });

    test("the Square off dialog keeps its size when the unknown line appears", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerDeskReads(syntheticApi);
      registerAccountBooks(syntheticApi, { positionCalls: { minimum: 1, maximum: 8 }, orderCalls: { minimum: 0, maximum: 16 } });
      await mountWidget(page, "positions");
      const surface = positionSurface(page);
      const squareOff = surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA", exact: true });
      await tickUntil(page, squareOff);
      await squareOff.click();
      const dialog = page.getByRole("dialog", { name: "Square off position?" });
      const confirm = dialog.getByRole("button", { name: "Confirm square off SYNTHETIC-ALPHA", exact: true });
      const cancel = dialog.getByRole("button", { name: "Cancel", exact: true });
      await expect(confirm).toBeVisible();
      await page.clock.runFor(500);
      const before = await collectBoxes([dialog, confirm, cancel]);
      await recordLostSubmit(page, { key: "NSE:SYNTHETIC-ALPHA", symbol: "SYNTHETIC-ALPHA", exchange: "NSE", action: "SELL", quantity: 10 });
      await tickUntil(page, dialog.getByText(UNKNOWN, { exact: true }));
      await expect(dialog.getByRole("button", { name: "Open Orders" })).toBeVisible();
      await expect(confirm).toBeDisabled();
      expectUnmoved(before, await collectBoxes([dialog, confirm, cancel]), `square off dialog ${viewport.width}`);
    });

    test("Quick Trade BUY/SELL and the note stay put, with the line in a slot directly above them", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerQuickTradeReads(syntheticApi);
      await mountWidget(page, "quicktrade", false, { params: { symbol: "RELIANCE", exchange: "NSE" } });
      const buy = page.getByRole("button", { name: /^Buy .* of RELIANCE$/ });
      const sell = page.getByRole("button", { name: /^Sell .* of RELIANCE$/ });
      const note = page.locator("#quicktrade-admission-note");
      await expect(buy).toBeVisible();
      await page.clock.runFor(500);
      const before = await collectBoxes([buy, sell, note]);
      await recordLostSubmit(page, { key: "NSE:RELIANCE", symbol: "RELIANCE", exchange: "NSE", action: "BUY", quantity: 1 });
      const slot = page.getByTestId("quicktrade-status-slot");
      await tickUntil(page, slot.getByText(UNKNOWN));
      await expect(buy).toBeDisabled();
      expectUnmoved(before, await collectBoxes([buy, sell, note]), `quick trade ${viewport.width}`);
      const lineBox = (await slot.getByRole("status").boundingBox())!;
      const buyBox = (await buy.boundingBox())!;
      expect(lineBox.y + lineBox.height, "line sits above BUY/SELL").toBeLessThanOrEqual(buyBox.y + 0.5);
      expect(buyBox.y - (lineBox.y + lineBox.height), "line sits directly above BUY/SELL").toBeLessThanOrEqual(16);
      await expectLineFits(slot, `quick trade ${viewport.width}`);
    });

    test.describe("lost Option Chain basket order", () => {
      test.use({
        benignConsoleErrors: [{
          text: "Failed to load resource: net::ERR_CONNECTION_RESET",
          url: `http://localhost:5173${LIVE_PLACE}`,
          expectedCalls: 1,
        }],
      });

      test("shows no red strip, and Buy All and the grid stay put when the unknown line appears", async ({ page, syntheticApi }) => {
        test.setTimeout(60_000);
        registerOptionChainReads(syntheticApi);
        let posts = 0;
        await page.route(`**${LIVE_PLACE}`, async (route) => {
          posts += 1;
          await route.abort("connectionreset");
        });
        await mountWidget(page, "optionchain");
        const panel = page.getByRole("tabpanel", { name: "Option Chain" });
        const canvas = panel.getByTestId("data-grid-canvas");
        await tickUntil(page, panel.getByRole("status").filter({ hasText: /strikes loaded/ }));
        await page.clock.runFor(200);
        // The CALL action column of the first visible strike.
        const callColumn = { x: 38 + 52 + 60 + 54 + 26, y: 26 + 12 };
        const grid = (await canvas.boundingBox())!;
        await page.mouse.move(grid.x + callColumn.x, grid.y + callColumn.y);
        await page.clock.runFor(50);
        await page.mouse.down();
        await page.clock.runFor(50);
        await page.mouse.up();
        await page.clock.runFor(100);
        const buyAll = panel.getByRole("button", { name: "Buy All", exact: true });
        await tickUntil(page, buyAll);
        await page.clock.runFor(200);
        const before = await collectBoxes([buyAll, canvas]);
        await buyAll.click();
        const slot = panel.getByTestId("basket-status-slot");
        await tickUntil(page, slot.getByText(UNKNOWN));
        await page.clock.runFor(200);
        await expect(buyAll).toBeDisabled();
        await expect(panel.getByText(UNKNOWN)).toHaveCount(1);
        expectUnmoved(before, await collectBoxes([buyAll, canvas]), `option chain ${viewport.width}`);
        await expectLineFits(slot, `option chain ${viewport.width}`);
        expect(posts).toBe(1);
      });
    });

    test("Orders table rows stay put when the unknown line appears", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerOrdersReads(syntheticApi);
      await mountWidget(page, "orders");
      const table = page.getByRole("tabpanel", { name: "Orders" }).getByRole("table");
      let advanced = 0;
      await expect.poll(async () => {
        if (advanced < 5_000) {
          await page.clock.runFor(50);
          advanced += 50;
        }
        return table.isVisible();
      }, { timeout: 15_000, intervals: [50] }).toBe(true);
      const rows = table.getByRole("row");
      await expect(rows.nth(1)).toBeVisible();
      const before = await collectBoxes(await rows.all());
      await recordLostSubmit(page, {
        key: "NFO:NIFTY24APR24000CE",
        symbol: "NIFTY24APR24000CE",
        exchange: "NFO",
        action: "BUY",
        quantity: 75,
      });
      const line = page.getByTestId("orders-notice-slot").getByText("1 order status unknown");
      let lineAdvanced = 0;
      await expect.poll(async () => {
        if (lineAdvanced < 2_000) {
          await page.clock.runFor(25);
          lineAdvanced += 25;
        }
        return line.isVisible();
      }, { timeout: 15_000, intervals: [50] }).toBe(true);
      expectUnmoved(before, await collectBoxes(await rows.all()), `orders rows ${viewport.width}`);
      const noticeBox = await page.getByTestId("orders-notice-slot").boundingBox();
      expect(noticeBox?.height, `orders notice slot ${viewport.width}`).toBe(44);
      const rowBox = await table.getByRole("row").nth(1).boundingBox();
      expect(rowBox?.height, `orders row ${viewport.width}`).toBeLessThanOrEqual(33);
    });
  });
}

const SHIFT_VIEWPORTS = [
  { width: 1280, height: 800 },
  { width: 2560, height: 1440 },
] as const;

const REFUSAL = "Not placed. Limit is 10 orders per second per exchange. Retry in 1 second.";
const REFUSAL_MESSAGE = `Regulation · ${REFUSAL}`;
const SL_UNKNOWN = "Entry placed · Stop-loss status unknown";

async function recordLostBracketSubmit(page: Page): Promise<void> {
  await page.evaluate(async ({ scope }) => {
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const { submitOrderOnce } = await importModule("/src/lib/orderSubmitGuard.ts") as {
      submitOrderOnce: (scope: string, intent: unknown, send: () => Promise<unknown>) => Promise<unknown>;
    };
    const error = Object.assign(new Error("Order status unknown. Check Orders before trying again."), {
      status: 502,
      body: { order_outcome: "unknown", leg_outcomes: { entry: "confirmed", stop_loss: "unknown" } },
    });
    await submitOrderOnce(
      scope,
      { key: "NFO:NIFTY24APR24000CE", symbol: "NIFTY24APR24000CE", exchange: "NFO", action: "BUY", quantity: 75 },
      () => Promise.reject(error),
    ).catch(() => undefined);
  }, { scope: `live:${BROKER}:${ACCOUNT_A}` });
}

for (const viewport of SHIFT_VIEWPORTS) {
  test.describe(`Order Pad refusal stays in the reserved slot at ${viewport.width}×${viewport.height}`, () => {
    test.use({
      viewport,
      benignConsoleErrors: [{
        text: "Failed to load resource: the server responded with a status of 429 (Too Many Requests)",
        url: `http://localhost:5173${PLACE}`,
        expectedCalls: 1,
      }],
    });

    test("Buy does not move when a Not placed refusal appears", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      await seedOrderPadWorkspace(page);
      registerPracticePadReads(syntheticApi);
      await page.route(`**${PLACE}`, async (route) => {
        await route.fulfill({
          status: 429,
          contentType: "application/json",
          body: JSON.stringify({
            status: "error",
            code: "order_rule_blocked",
            message: REFUSAL_MESSAGE,
          }),
        });
      });
      const buy = page.getByRole("button", { name: "Practice Buy" });
      let before: Box | null = null;
      await confirmLostPracticeBuy(page, undefined, async () => {
        before = await expectOnScreenAndUncovered(page, buy, `Buy before refusal at ${viewport.width}`);
      });
      const review = page.getByRole("dialog", { name: "Review Practice order" });
      await expect(review).toBeVisible();
      await review.getByRole("button", { name: "Back to edit" }).click();
      await expect(review).toHaveCount(0);
      const slot = page.getByTestId("order-pad-status-slot");
      const outcome = slot.getByTestId("order-pad-outcome");
      await expect(outcome).toBeVisible({ timeout: 15_000 });
      await expect(outcome).toContainText("Not placed.");
      await expect(outcome).toContainText(REFUSAL);
      const after = await expectOnScreenAndUncovered(page, buy, `Buy after refusal at ${viewport.width}`);
      expectUnmoved([before!], [after], `Order Pad Buy refusal ${viewport.width}`);
    });
  });
}

for (const viewport of SHIFT_VIEWPORTS) {
  test.describe(`Orders mixed-leg row stays compact at ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport });

    test("SL unknown sits on the row and the notice stays h-11", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerOrdersReads(syntheticApi);
      await mountWidget(page, "orders");
      const table = page.getByRole("tabpanel", { name: "Orders" }).getByRole("table");
      let advanced = 0;
      await expect.poll(async () => {
        if (advanced < 5_000) {
          await page.clock.runFor(50);
          advanced += 50;
        }
        return table.isVisible();
      }, { timeout: 15_000, intervals: [50] }).toBe(true);
      await recordLostBracketSubmit(page);
      const chip = page.getByTestId("orders-leg-unknown");
      let chipAdvanced = 0;
      await expect.poll(async () => {
        if (chipAdvanced < 2_000) {
          await page.clock.runFor(25);
          chipAdvanced += 25;
        }
        return chip.isVisible();
      }, { timeout: 15_000, intervals: [50] }).toBe(true);
      await expect(chip).toHaveText("SL unknown");
      await expect(chip).toHaveAttribute("title", SL_UNKNOWN);
      await expect(page.getByTestId("orders-notice-slot")).toContainText("1 order status unknown");
      await expect(page.getByText(SL_UNKNOWN, { exact: true })).toHaveCount(0);
      const noticeBox = await page.getByTestId("orders-notice-slot").boundingBox();
      expect(noticeBox?.height, `orders notice slot ${viewport.width}`).toBe(44);
      const rowBox = await table.getByRole("row").nth(1).boundingBox();
      expect(rowBox?.height, `orders mixed-leg row ${viewport.width}`).toBeLessThanOrEqual(33);
    });
  });
}

const SCALPER_FIT_VIEWPORTS = [
  { width: 1280, height: 800 },
  { width: 2560, height: 1440 },
] as const;

const SCALPER_PANEL_WIDTHS = [180, 299, 379, 480] as const;

for (const viewport of SCALPER_FIT_VIEWPORTS) {
  test.describe(`Scalper unknown line fits one row at ${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport });

    test("the default panel keeps the unknown line on one unclipped row", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerScalperReads(syntheticApi);
      await mountWidget(page, "scalper");
      await page.clock.runFor(5_000);
      await expect(page.getByText("1 (65)", { exact: true })).toBeAttached({ timeout: 15_000 });
      const slot = page.getByTestId("scalper-ce-status-slot");
      await recordLostSubmit(page, { key: `NFO:${CE}`, symbol: CE, exchange: "NFO", action: "BUY", quantity: 65 });
      await waitForScalperUnknown(page, slot);
      await expectLineFits(slot, `scalper default panel at ${viewport.width}`);
    });

    for (const panelWidth of SCALPER_PANEL_WIDTHS) {
      test(`keeps the unknown line on one unclipped row in a ${panelWidth}px panel`, async ({ page, syntheticApi }) => {
        test.setTimeout(60_000);
        registerScalperReads(syntheticApi);
        await mountWidget(page, "scalper");
        await page.clock.runFor(5_000);
        await expect(page.getByText("1 (65)", { exact: true })).toBeAttached({ timeout: 15_000 });
        const slot = page.getByTestId("scalper-ce-status-slot");
        await setScalperPanelWidth(slot, panelWidth);
        await recordLostSubmit(page, { key: `NFO:${CE}`, symbol: CE, exchange: "NFO", action: "BUY", quantity: 65 });
        await waitForScalperUnknown(page, slot);
        expect(
          await slot.evaluate((node) => Math.round(node.getBoundingClientRect().width)),
          `panel is ${panelWidth}px`,
        ).toBeLessThanOrEqual(panelWidth);
        await expectLineFits(slot, `scalper ${panelWidth}px panel at ${viewport.width}`);
        if (panelWidth === 180) {
          const status = slot.getByRole("status");
          await expect(status).toContainText("Status unknown Open Orders");
          await expect(status).not.toContainText("·");
          const gap = await status.evaluate((node) => getComputedStyle(node).columnGap);
          expect(gap).toBe("4px");
          await expect(slot.getByRole("button", { name: "Open Orders" })).toBeVisible();
          await expect(slot.getByText(UNKNOWN, { exact: true })).toBeHidden();
        }
      });
    }
  });
}
