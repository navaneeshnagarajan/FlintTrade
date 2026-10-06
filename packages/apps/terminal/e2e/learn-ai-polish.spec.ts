import { expect, test } from "./fixture-registry";
import { seedExploreDemoSession } from "./helpers";
import { registerExampleDeskReads } from "./visual/desk-mocks";

test.beforeEach(async ({ page, syntheticApi }) => {
  await seedExploreDemoSession(page);
  await page.addInitScript(() => {
    localStorage.setItem("flinttrade:skill", JSON.stringify({
      version: 2,
      state: { globalLevel: "advanced", routeOverrides: {}, helpPrefs: { aiTutor: true } },
    }));
  });
  registerExampleDeskReads(syntheticApi);
});

test("Learn teaches built-in Practice and its Trade link preserves the selected mode", async ({ page }) => {
  await page.goto("/learn");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Learn");
  await page.getByRole("tab", { name: "Practice Trading" }).click();
  const practice = page.getByTestId("practice-trading");
  await expect(practice).toContainText("Practice is built in. Open the Trade desk and place a simulated order, no broker needed.");
  await expect(practice).not.toContainText(/sandbox|Kotak|funded unlock/i);
  await expect(practice.getByRole("link", { name: "Open Trade desk" })).toHaveAttribute("href", "/trade");
  await page.screenshot({ path: "test-results/learn-practice.png", fullPage: true });
  await practice.getByRole("link", { name: "Open Trade desk" }).click();
  await expect(page).toHaveURL(/\/trade$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Trade");
  const mode = await page.evaluate(() => JSON.parse(localStorage.getItem("flinttrade:mode") ?? "{}").state.mode);
  expect(mode).toBe("explore");
  await page.getByRole("button", { name: "Tools", exact: true }).click();
  await page.getByRole("menuitem", { name: "Trade Review", exact: true }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Trade Review" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Trade");
  await page.getByRole("button", { name: "Close trade review" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Trade Review" })).toHaveCount(0);

  await page.goBack();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Learn");
});

test("Schedules uses human names and keeps Explore controls disabled", async ({ page }) => {
  await page.goto("/automate#schedules");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Automate");
  await expect(page.getByText("Pre-market screener", { exact: true })).toBeVisible();
  await expect(page.getByText("End-of-day position snapshot", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "Show system jobs" }).check();
  for (const pause of await page.getByRole("button", { name: "Pause", exact: true }).all()) {
    await expect(pause).toBeDisabled();
  }
  await page.getByRole("checkbox", { name: "Show system jobs" }).uncheck();
  await page.screenshot({ path: "test-results/schedules.png", fullPage: true });
});

test("a retired automation deep link preserves schedules and monitors without flow traffic", async ({ page, syntheticApi }) => {
  syntheticApi.register({
    name: "deny retired flow reads", method: "GET", path: "/ft-api/api/v1/flows",
    expectedCalls: { minimum: 0, maximum: 1 },
    handler: () => { throw new Error("Retired flow APIs must never be requested"); },
  });
  await page.goto("/automate#flows");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Automate");
  await expect(page.getByRole("tab", { name: "Schedules", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("Pre-market screener", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Flows", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "New Flow", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "From Template", exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "Monitors", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Live Strategy Monitors", exact: true })).toBeVisible();
  await expect(page.getByText("No strategies running", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Strategy Builder", exact: true })).toHaveAttribute("href", "/lab");
  expect(syntheticApi.callCount("GET", "/ft-api/api/v1/flows")).toBe(0);
});
