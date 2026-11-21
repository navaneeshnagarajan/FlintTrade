import type { Locator, Page, Request } from "@playwright/test";
import { registerSystemDiagnosticsRead } from "./visual/desk-mocks";
import {
  ACCOUNT_A,
  BROKER,
  expect,
  mountWidget,
  nativePath,
  recordLostSubmit,
  registerAccountBooks,
  registerDeskReads,
  registerRead,
  seedInstrumentTick,
  test,
} from "./order-flow-fixtures";
import { registerExploreAdvisorStatusProbe, registerOperatorStatusProbes } from "./fixture-registry";

const UNKNOWN = "Order status unknown. Check Orders before trying again.";
const CE = "NIFTY27AUG26100CE";
const PLACE = "/ft-api/api/v1/orders/place";
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

async function confirmLostPracticeBuy(page: Page, beforeConfirm?: () => void): Promise<void> {
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
});

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
      const line = page.getByTestId("scalper-ce-status-slot").getByText(UNKNOWN);
      let advanced = 0;
      await expect.poll(async () => {
        if (advanced < 2_000) {
          await page.clock.runFor(25);
          advanced += 25;
        }
        return line.isVisible();
      }, { timeout: 15_000, intervals: [50] }).toBe(true);
      expectUnmoved(before, await collectBoxes(controls), `scalper ${viewport.width}`);
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
      const line = page.getByTestId("orders-notice-slot").getByText(UNKNOWN);
      let lineAdvanced = 0;
      await expect.poll(async () => {
        if (lineAdvanced < 2_000) {
          await page.clock.runFor(25);
          lineAdvanced += 25;
        }
        return line.isVisible();
      }, { timeout: 15_000, intervals: [50] }).toBe(true);
      expectUnmoved(before, await collectBoxes(await rows.all()), `orders rows ${viewport.width}`);
    });
  });
}
