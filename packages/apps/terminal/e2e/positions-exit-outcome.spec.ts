import {
  expect,
  mountWidget,
  positionSurface,
  registerAccountBooks,
  registerDeskReads,
  tabStopNames,
  test,
  tickUntil,
} from "./order-flow-fixtures";

const UNKNOWN = "Order status unknown. Check Orders before trying again.";
const PLACE = "/ft-api/api/v1/orders/dhan/place";
const EXIT_ALL = "/ft-api/api/v1/positions/exit-all";

type LostExit = {
  name: string;
  consoleError: string;
  lose: (route: import("@playwright/test").Route) => Promise<void>;
};

// The three ways an exit reply goes missing after the request left the browser.
const LOST_EXITS: LostExit[] = [
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

for (const lost of LOST_EXITS) {
  test.describe(`lost Positions square-off: ${lost.name}`, () => {
    test.use({
      benignConsoleErrors: [{ text: lost.consoleError, url: `http://localhost:5173${PLACE}`, expectedCalls: 1 }],
    });

    test("keeps the contract locked with the unknown sentence, has no Retry, and sends one exit", async ({ page, syntheticApi }) => {
      registerDeskReads(syntheticApi);
      // A lost exit keeps the order book polling until a read settles it.
      registerAccountBooks(syntheticApi, {
        positionCalls: { minimum: 1, maximum: 4 },
        orderCalls: { minimum: 1, maximum: 8 },
      });
      let exits = 0;
      await page.route(`**${PLACE}`, async (route) => {
        exits += 1;
        await lost.lose(route);
      });

      await mountWidget(page, "positions");
      const surface = positionSurface(page);
      const squareOff = surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA", exact: true });
      await tickUntil(page, squareOff);
      await squareOff.click();
      const dialog = page.getByRole("dialog", { name: "Square off position?" });
      const confirm = dialog.getByRole("button", { name: "Confirm square off SYNTHETIC-ALPHA", exact: true });
      await confirm.dblclick();

      await tickUntil(page, dialog.getByText(UNKNOWN, { exact: true }));
      await expect(confirm).toBeDisabled();
      await expect(page.getByRole("button", { name: /retry/i })).toHaveCount(0);
      expect((await tabStopNames(page, 20)).filter((name) => /retry/i.test(name))).toEqual([]);

      await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
      await expect(dialog).toHaveCount(0);
      await expect(squareOff).toBeDisabled();
      expect(exits).toBe(1);
    });
  });
}

for (const lost of [LOST_EXITS[0]!, LOST_EXITS[2]!]) {
  test.describe(`lost Live exit-all: ${lost.name}`, () => {
    test.use({
      benignConsoleErrors: [{ text: lost.consoleError, url: `http://localhost:5173${EXIT_ALL}`, expectedCalls: 1 }],
    });

    test("stays unknown, disables Confirm, and sends one exit-all", async ({ page, syntheticApi }) => {
      registerDeskReads(syntheticApi);
      registerAccountBooks(syntheticApi, {
        positionCalls: { minimum: 1, maximum: 4 },
        orderCalls: { minimum: 1, maximum: 4 },
      });
      let exitAlls = 0;
      await page.route(`**${EXIT_ALL}`, async (route) => {
        exitAlls += 1;
        await lost.lose(route);
      });

      await mountWidget(page, "positions");
      const surface = positionSurface(page);
      await tickUntil(page, surface.getByRole("button", { name: "Square off SYNTHETIC-ALPHA", exact: true }));
      await surface.getByRole("button", { name: "Exit all positions", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "Exit all positions?" });
      await dialog.getByRole("textbox", { name: "Type EXIT (in capitals) to confirm" }).fill("EXIT");
      const confirm = dialog.getByRole("button", { name: "Confirm exit all positions", exact: true });
      await confirm.dblclick();

      await tickUntil(page, dialog.getByText(UNKNOWN, { exact: true }));
      await expect(confirm).toBeDisabled();
      await expect(page.getByRole("button", { name: /retry/i })).toHaveCount(0);
      expect(exitAlls).toBe(1);
    });
  });
}
