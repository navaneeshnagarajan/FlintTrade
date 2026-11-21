import type { SyntheticPhasedFixtureRegistry } from "./fixture-registry";
import {
  ACCOUNT_A,
  LIVE_TOKEN,
  expect,
  mountWidget,
  nativePath,
  registerAccountBooks,
  registerDeskReads,
  registerRead,
  tabStopNames,
  test,
  tickUntil,
} from "./order-flow-fixtures";
import { registerSystemDiagnosticsRead } from "./visual/desk-mocks";

const CANCEL = "/ft-api/api/v1/orders/dhan/cancel";
const REQUESTED = "Cancellation requested";
const CANCELLED = "Order cancelled";

/**
 * A reload is a second page load. Close the first load's once-per-load reads
 * with their evidence intact, then arm the same reads for the second load.
 */
async function rearmPageLoadReads(syntheticApi: SyntheticPhasedFixtureRegistry): Promise<void> {
  await syntheticApi.retireRead("/ft-api/api/v1/system/diagnostics");
  registerSystemDiagnosticsRead(syntheticApi, LIVE_TOKEN);
  await syntheticApi.retireRead("/ft-api/api/v1/safety/config");
  registerRead(syntheticApi, "/ft-api/api/v1/safety/config", {
    json: { status: "success", data: { l1_order: {}, l2_position: {}, l3_portfolio: {}, l4_pnl: {}, l5_kill: {} } },
  }, { minimum: 1, maximum: 4 });
  await syntheticApi.retireRead("/ft-api/api/v1/ping");
  syntheticApi.register({
    name: "operator desk ping after reload", method: "GET", path: "/ft-api/api/v1/ping",
    expectedCalls: { minimum: 1, maximum: 4 },
    handler: () => ({ json: { status: "ok", laya: "ready" } }),
  });
}

function orderRow(status: string) {
  return {
    orderid: "SYNTHETIC-ORDER-1", symbol: "SYNTHETIC-ALPHA", exchange: "NSE", action: "BUY",
    quantity: 10, price: 99, pricetype: "LIMIT", product: "CNC", order_status: status, strategy: "Flint",
  };
}

type LostCancel = {
  name: string;
  consoleError: string;
  lose: (route: import("@playwright/test").Route) => Promise<void>;
};

// The three ways a cancel reply goes missing after the request left the browser.
const LOST_CANCELS: LostCancel[] = [
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

for (const lost of LOST_CANCELS) test.describe(`lost Orders cancel: ${lost.name}`, () => {
  test.use({
    benignConsoleErrors: [{
      text: lost.consoleError,
      url: `http://localhost:5173${CANCEL}`,
      expectedCalls: 1,
    }],
  });

  test("stays Cancellation requested through a reload, sends one cancel, and confirms only on a CANCELLED read", async ({
    page, syntheticApi,
  }) => {
    test.setTimeout(90_000);
    let book = [orderRow("open")];
    registerDeskReads(syntheticApi, false, { marketScopeVisits: 12 });
    registerAccountBooks(syntheticApi, {
      positionCalls: { minimum: 0, maximum: 8 },
      orders: () => ({ json: { status: "success", data: book } }),
      orderCalls: { minimum: 1, maximum: 24 },
    });

    let cancels = 0;
    await page.route(`**${CANCEL}`, async (route) => {
      cancels += 1;
      await lost.lose(route);
    });

    await mountWidget(page, "orders");
    const cancelButton = page.getByRole("button", { name: "Cancel order SYNTHETIC-ORDER-1", exact: true });
    await tickUntil(page, cancelButton);
    await cancelButton.click();
    await page.getByRole("dialog", { name: "Confirm order cancellation" })
      .getByRole("button", { name: "Cancel Order", exact: true }).click();

    const pending = page.getByRole("status").filter({ hasText: REQUESTED });
    await tickUntil(page, pending);
    await expect(page.getByText(CANCELLED, { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /retry/i })).toHaveCount(0);
    await expect(cancelButton).toBeDisabled();
    expect((await tabStopNames(page)).filter((name) => /retry/i.test(name))).toEqual([]);

    // A full browser reload keeps the pending line; it is not widget state.
    await rearmPageLoadReads(syntheticApi);
    await page.reload();
    await tickUntil(page, page.getByRole("status").filter({ hasText: REQUESTED }));
    await expect(page.getByText(CANCELLED, { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /retry/i })).toHaveCount(0);

    // Only a later read that shows CANCELLED confirms the cancel.
    book = [orderRow("cancelled")];
    await page.clock.runFor(10_000);
    await page.getByRole("button", { name: "Refresh orders", exact: true }).click();
    await tickUntil(page, page.getByRole("status").filter({ hasText: CANCELLED }));
    await expect(page.getByRole("status").filter({ hasText: REQUESTED })).toHaveCount(0);
    expect(cancels).toBe(1);
    expect(syntheticApi.callCount("GET", nativePath("orders", ACCOUNT_A))).toBeGreaterThan(1);
  });
});
