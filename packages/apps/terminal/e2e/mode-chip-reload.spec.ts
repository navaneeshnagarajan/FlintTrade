/**
 * A reload must paint the session mode, not a stale mode cache.
 *
 * The browser cache can still say Live after the session was restored as
 * Practice. The chip and the cache follow the session claim.
 */

import { expect, test } from "@playwright/test";

function sessionToken(mode: "practice"): string {
  const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({
    sub: "synthetic-mode-chip-operator",
    mode,
    exp: 4_102_444_800,
  })).toString("base64url");
  return `${header}.${payload}.synthetic-e2e-signature`;
}

test("the mode chip reads Practice after reload when the cache says live", async ({ page }) => {
  const token = sessionToken("practice");
  await page.addInitScript((session) => {
    localStorage.setItem(
      "flinttrade:mode",
      JSON.stringify({ state: { mode: "live" }, version: 2 }),
    );
    sessionStorage.setItem("flinttrade:auth-session", JSON.stringify({
      token: session,
      username: "synthetic-mode-chip-operator",
      expiresAt: "",
    }));
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  }, token);

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
