/**
 * A reload must paint the session mode, not a stale mode cache.
 *
 * The browser cache can still say Live after the session was restored as
 * Practice. The chip and the cache follow the session claim. A missing or
 * connected claim is Unavailable, never Example. Connected (read) is a
 * broker status, not a chip label and not a mode-menu item.
 */

import { expect, test, type Page } from "@playwright/test";

const UNAVAILABLE_ORDERS =
  "Orders are blocked because the session mode couldn't be confirmed. Sign in again or reload.";
const UNAVAILABLE_SCOPE =
  "Unavailable · Session mode couldn't be confirmed. Sign in again or reload. · Linking changes selections, never execution authority.";

function sessionToken(mode?: string): string {
  const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({
    sub: "synthetic-mode-chip-operator",
    ...(mode === undefined ? {} : { mode }),
    exp: 4_102_444_800,
  })).toString("base64url");
  return `${header}.${payload}.synthetic-e2e-signature`;
}

async function seedSession(page: Page, token: string, cachedMode = "live"): Promise<void> {
  await page.addInitScript(({ session, cached }) => {
    localStorage.setItem(
      "flinttrade:mode",
      JSON.stringify({ state: { mode: cached }, version: 2 }),
    );
    sessionStorage.setItem("flinttrade:auth-session", JSON.stringify({
      token: session,
      username: "synthetic-mode-chip-operator",
      expiresAt: "",
    }));
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  }, { session: token, cached: cachedMode });
}

async function expectUnavailableDesk(page: Page): Promise<void> {
  const chip = page.getByTestId("execution-mode");
  await expect(chip).toBeVisible({ timeout: 15_000 });
  await expect(chip).toHaveText("Unavailable");
  await expect(chip).not.toHaveText(/Example|Sample|Connected/);
  await expect(page.getByTestId("app-execution-scope")).toHaveText(UNAVAILABLE_SCOPE);

  const terminal = page.getByRole("region", { name: "Terminal app", exact: true });
  await terminal.getByRole("button", { name: "Add widget", exact: true }).click();
  await page.getByRole("textbox", { name: "Search widgets" }).fill("Scalper");
  await page.getByRole("button", { name: "Add Scalper", exact: true }).click();
  const blocked = page.getByText(UNAVAILABLE_ORDERS);
  await expect(blocked).toBeVisible({ timeout: 15_000 });
  await expect(blocked).not.toHaveText(/Example|Sample/);
}

test("the mode chip reads Practice after reload when the cache says live", async ({ page }) => {
  await seedSession(page, sessionToken("practice"));

  await page.goto("/trade");
  const chip = page.getByTestId("execution-mode");
  await expect(chip).toBeVisible({ timeout: 15_000 });
  await expect(chip).toHaveText("Practice");
  await expect.poll(() => page.evaluate(() => {
    const raw = localStorage.getItem("flinttrade:mode");
    return raw ? (JSON.parse(raw) as { state?: { mode?: string } }).state?.mode : null;
  })).toBe("practice");

  await page.reload();
  await expect(chip).toBeVisible({ timeout: 15_000 });
  await expect(chip).toHaveText("Practice");
  await expect(chip).not.toHaveText("Live");
});

test("a missing mode claim says Unavailable on the chip, the terminal line, and the Scalper", async ({ page }) => {
  await seedSession(page, sessionToken());
  await page.goto("/trade");
  await expectUnavailableDesk(page);
});

test("a connected claim says Unavailable and is not labelled Example", async ({ page }) => {
  await seedSession(page, sessionToken("connected"));
  await page.goto("/trade");
  await expectUnavailableDesk(page);
  await expect(page.getByTestId("execution-mode")).not.toHaveText("Connected (read)");
});

test("Practice with a broker connected keeps Practice on the chip and out of the mode menu", async ({ page }) => {
  await page.route("**/ft-api/api/v1/native/accounts", async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "success",
        data: {
          accounts: [{
            adapter_id: "dhan",
            account_id: "DH1",
            label: "Dhan read",
            is_primary: true,
            has_session: true,
            read_only: true,
            read_smoke_ok: true,
          }],
        },
      }),
    });
  });
  await seedSession(page, sessionToken("practice"), "practice");
  await page.goto("/trade");

  const chip = page.getByTestId("execution-mode");
  await expect(chip).toBeVisible({ timeout: 15_000 });
  await expect(chip).toHaveText("Practice");
  await expect(chip).toHaveAccessibleName("Practice mode. Open the mode menu.");

  await chip.click();
  await expect(page.getByRole("menuitem", { name: "Practice", exact: true })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: /Connected \(read\)/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(chip).toHaveText("Practice");
});
