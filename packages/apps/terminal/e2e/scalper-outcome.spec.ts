import {
  expect,
  mountWidget,
  nativePath,
  registerAccountBooks,
  registerDeskReads,
  registerRead,
  test,
  tabStopNames,
  tickUntil,
} from "./order-flow-fixtures";

const UNKNOWN = "Order status unknown. Check Orders before trying again.";
const CE = "NIFTY27AUG26100CE";
const PE = "NIFTY27AUG26100PE";
const PLACE = "/ft-api/api/v1/orders/dhan/place";

function historyPath(symbol: string, exchange: string): string {
  // Frozen clock is 2026-08-11. The chart's 5m history request on this
  // runtime asks for the window that starts on 2026-07-12.
  return `${nativePath("history")}?symbol=${symbol}&exchange=${exchange}&interval=5m&start_date=2026-07-12&end_date=2026-08-11`;
}

type LostSubmit = {
  name: string;
  consoleError: string;
  lose: (route: import("@playwright/test").Route) => Promise<void>;
};

// The three ways a place reply goes missing after the request left the browser.
const LOST_SUBMITS: LostSubmit[] = [
  {
    name: "dropped connection",
    consoleError: "Failed to load resource: net::ERR_CONNECTION_RESET",
    lose: (route) => route.abort("connectionreset"),
  },
  {
    name: "hang until timeout",
    consoleError: "Failed to load resource: net::ERR_TIMED_OUT",
    lose: (route) => route.abort("timedout"),
  },
  {
    name: "HTTP 500 after the broker accepted",
    consoleError: "Failed to load resource: the server responded with a status of 500 (Internal Server Error)",
    lose: (route) => route.fulfill({ status: 500, contentType: "text/plain", body: "upstream error" }),
  },
];

function registerScalperReads(syntheticApi: Parameters<typeof registerDeskReads>[0]): void {
  registerDeskReads(syntheticApi, false, { marketScopeVisits: 12 });
  registerAccountBooks(syntheticApi, {
    positionCalls: { minimum: 0, maximum: 2 },
    // A lost submit keeps the order book polling until a read settles it.
    orderCalls: { minimum: 0, maximum: 8 },
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
  registerRead(syntheticApi, `/ft-api/api/v1/safety/config?broker=dhan&account_id=${"SYNTHETIC-A"}`, {
    json: { status: "success", data: { l1_order: {}, l2_position: {}, l3_portfolio: {}, l4_pnl: {}, l5_kill: {} } },
  }, { minimum: 0, maximum: 2 });
  for (const symbol of [CE, PE]) {
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

for (const lost of LOST_SUBMITS) {
  test.describe(`lost Scalper submit: ${lost.name}`, () => {
    test.use({
      benignConsoleErrors: [{
        text: lost.consoleError,
        url: `http://localhost:5173${PLACE}`,
        expectedCalls: 1,
      }],
    });

    test("shows the unknown sentence beside locked Buy/Sell, has no Retry, and sends one order POST", async ({ page, syntheticApi }) => {
      test.setTimeout(60_000);
      registerScalperReads(syntheticApi);

      let posts = 0;
      await page.route(`**${PLACE}`, async (route) => {
        posts += 1;
        await lost.lose(route);
      });

      await mountWidget(page, "scalper");
      // The ticker poll is armed after Scalper subscribes. One interval publishes
      // the synthetic NIFTY quote that resolves the strike.
      await page.clock.runFor(5_000);
      const lot = page.getByText("1 (65)", { exact: true });
      await expect(lot).toBeAttached({ timeout: 15_000 });
      // The CE buttons sit under the chart. Opening the folded note moves focus
      // into the Scalper so Shift+ArrowUp takes the same Buy CE path as the button.
      await page.getByRole("button", { name: "Add a reason (optional)" }).click();
      await expect(page.getByRole("textbox", { name: "Add a reason (optional)" })).toBeFocused();
      await page.keyboard.press("Shift+ArrowUp");
      const confirm = page.getByRole("button", { name: "Confirm BUY", exact: true });
      await expect(confirm).toBeVisible();
      await confirm.click();

      const outcome = page.getByRole("status").filter({ hasText: UNKNOWN });
      await tickUntil(page, outcome);
      await expect(outcome).toBeVisible();
      await expect(outcome.getByRole("button", { name: "Open Orders", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: /^Buy CE/ }).first()).toBeDisabled();
      await expect(page.getByRole("button", { name: /^Sell CE/ }).first()).toBeDisabled();
      await expect(page.getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);

      // The hotkey on a locked contract opens nothing and sends nothing.
      await page.getByRole("button", { name: "Add a reason (optional)" }).click();
      await expect(page.getByRole("textbox", { name: "Add a reason (optional)" })).toBeFocused();
      await page.keyboard.press("Shift+ArrowUp");
      await page.keyboard.press("Shift+ArrowUp");
      await expect(confirm).toHaveCount(0);

      // No focusable control named Retry anywhere Tab reaches.
      const names = await tabStopNames(page);
      expect(names.filter((name) => /retry/i.test(name))).toEqual([]);
      expect(posts).toBe(1);
    });
  });
}
