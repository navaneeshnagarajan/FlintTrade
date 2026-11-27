/** Order safety in the browser: the ticket's reserved line and the stop-loss not-filled chip. No backend. */
import { expect, test } from "./fixture-registry";

test.beforeEach(async ({ page }) => {
  await page.goto("/e2e/order-safety.fixture.html");
});

test("a market option order is refused on the reserved line and Place stays disabled", async ({ page }) => {
  const line = page.locator("#orderpad-qty-error");
  const place = page.getByRole("button", { name: "Place" });
  await expect(place).toBeEnabled();
  await page.getByLabel("Type").selectOption("MARKET");
  await expect(line).toContainText("Market orders aren't accepted on options. Use a limit price.");
  await expect(line).toHaveAttribute("role", "alert");
  await expect(place).toBeDisabled();
  await expect(page.getByTestId("order-rule-more")).toHaveCount(0);
  await page.getByLabel("Type").selectOption("SL-M");
  await expect(line).toContainText("Stop-market orders aren't accepted on options. Use stop-limit.");
  await expect(place).toBeDisabled();
  await expect(page.getByTestId("order-rule-more")).toHaveCount(0);
});

test("a BSE stop-loss limit too far from its trigger is refused; the price is never changed", async ({ page }) => {
  await page.getByLabel("Symbol").fill("SENSEX27NOV2680000CE");
  await page.getByLabel("Exchange").fill("BFO");
  await page.getByLabel("Type").selectOption("SL");
  await page.getByLabel("Trigger").fill("50");
  await page.getByRole("textbox", { name: "Price" }).fill("39.95");
  const line = page.locator("#orderpad-qty-error");
  await expect(line).toContainText("Stop-loss limit must be within ₹10 of trigger.");
  await expect(page.getByRole("button", { name: "Place" })).toBeDisabled();
  await expect(page.getByRole("textbox", { name: "Price" })).toHaveValue("39.95");
  await page.getByRole("textbox", { name: "Price" }).fill("40");
  await expect(line).not.toContainText("Stop-loss limit");
});

test("a price outside the band warns without disabling Place or changing the price", async ({ page }) => {
  await page.getByRole("textbox", { name: "Price" }).fill("200");
  const line = page.locator("#orderpad-qty-error");
  await expect(line).toContainText("Price may be outside the exchange band (₹60–₹140).");
  await expect(line).toHaveAttribute("data-level", "warn");
  await expect(page.getByRole("button", { name: "Place" })).toBeEnabled();
  await expect(page.getByRole("textbox", { name: "Price" })).toHaveValue("200");
});

test("a triggered stop that did not fill shows the chip, and Exit now opens a limit ticket", async ({ page }) => {
  const chip = page.getByTestId("stop-loss-not-filled");
  await expect(chip).toContainText("Stop-loss triggered · not filled");
  await page.getByRole("button", { name: "Exit now NIFTY25NOV2624000CE" }).click();
  const opened = JSON.parse(await page.getByLabel("Opened ticket").innerText()) as unknown;
  expect(opened).toEqual({
    widgetId: "orderpad",
    props: {
      symbol: "NIFTY25NOV2624000CE", exchange: "NFO", action: "SELL", orderType: "LIMIT", qty: 150, product: "MIS", price: 41.3, exitOnly: true, openQuantity: 150,
    },
  });
  await page.getByRole("button", { name: "Stop fills" }).click();
  await expect(chip).toHaveCount(0);
});

test("the first switch to Live asks once; Turn on Live stays disabled until ticked", async ({ page }) => {
  const step = page.getByLabel("Mode step");
  await page.getByRole("button", { name: "Live", exact: true }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByRole("heading", { name: "Turn on Live" })).toBeVisible();
  await expect(dialog).toContainText(
    "Orders will be sent from this computer through your broker account. Losses from your own strategy or automation aren't covered by the exchange grievance process.",
  );
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(step).toHaveText("Practice");

  await page.getByRole("button", { name: "Live", exact: true }).click();
  const confirm = dialog.getByRole("button", { name: "Turn on Live" });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("I understand").check();
  await confirm.click();
  await expect(step).toHaveText("PIN");

  await page.reload();
  await page.getByRole("button", { name: "Live", exact: true }).click();
  await expect(page.getByLabel("Mode step")).toHaveText("PIN");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
});
