import { test, expect } from "@playwright/test";
import { seedExploreDemoSession } from "./helpers";

function geometry(page: import("@playwright/test").Page) {
  return page.evaluate(() => {
    const topbar = document.querySelector("[data-testid='topbar-v2']")!.getBoundingClientRect();
    const bar = document.querySelector(".ft-product-bar")!.getBoundingClientRect();
    const nav = document.querySelector("nav[aria-label='Apps']")!.getBoundingClientRect();
    const layout = document.querySelector("[data-testid='app-layout']")!.getBoundingClientRect();
    return {
      topbarH: Math.round(topbar.height),
      topbarY: Math.round(topbar.y),
      barH: Math.round(bar.height),
      navY: Math.round(nav.y),
      layoutH: Math.round(layout.height),
    };
  });
}

test.describe("product bar geometry", () => {
  test("keeps a 44px top-bar row at 1280x720 and a single row at 2560", async ({ page }) => {
    await seedExploreDemoSession(page);
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/trade");
    await expect(page.getByRole("main", { name: "Terminal", exact: true })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("topbar-v2")).toBeVisible();
    await expect(page.getByTestId("app-layout")).toBeVisible();

    const at1280 = await geometry(page);
    expect(at1280.topbarH).toBeGreaterThanOrEqual(40);
    expect(at1280.topbarH).toBeLessThanOrEqual(52);
    expect(at1280.navY).toBeGreaterThanOrEqual(at1280.topbarY + at1280.topbarH - 2);
    expect(at1280.layoutH).toBeGreaterThanOrEqual(470);

    await page.setViewportSize({ width: 2560, height: 1440 });
    const at2560 = await geometry(page);
    expect(at2560.topbarH).toBeGreaterThanOrEqual(40);
    expect(at2560.topbarH).toBeLessThanOrEqual(52);
    expect(at2560.barH).toBeLessThanOrEqual(56);
    expect(Math.abs(at2560.navY - at2560.topbarY)).toBeLessThanOrEqual(8);
  });
});
