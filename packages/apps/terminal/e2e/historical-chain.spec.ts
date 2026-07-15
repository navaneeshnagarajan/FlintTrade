import { expect, test } from "@playwright/test";

import { seedExploreDemoSession } from "./helpers";

test("Historical Chain captures and renders the latest snapshot in a narrow panel", async ({ page }) => {
  let captured = false;
  let captureBody: unknown = null;

  await page.route("**/ft-api/api/v1/historical/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (request.method() === "POST" && pathname.endsWith("/capture")) {
      captured = true;
      captureBody = request.postDataJSON();
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          status: "success",
          data: {
            symbol: "NIFTY",
            expiry: "2026-03-26",
            exchange: "NFO",
            rows_inserted: 2,
            captured: true,
          },
        }),
      });
      return;
    }

    if (pathname.includes("/historical/expiries/")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          status: "success",
          data: {
            symbol: "NIFTY",
            exchange: "NFO",
            expiries: captured ? ["2026-03-26"] : [],
          },
        }),
      });
      return;
    }

    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        status: "success",
        data: {
          symbol: "NIFTY",
          exchange: "NFO",
          expiry: "2026-03-26",
          chain: [
            {
              captured_at: "2026-03-25T15:30:00",
              symbol: "NIFTY",
              exchange: "NFO",
              expiry_date: "2026-03-26",
              strike: 24000,
              option_type: "CE",
              oi: 110,
              volume: 60,
              ltp: 155,
              iv: 12.5,
            },
            {
              captured_at: "2026-03-25T15:30:00",
              symbol: "NIFTY",
              exchange: "NFO",
              expiry_date: "2026-03-26",
              strike: 24000,
              option_type: "PE",
              oi: 90,
              volume: 45,
              ltp: 125,
              iv: 13.5,
            },
          ],
        },
      }),
    });
  });

  await seedExploreDemoSession(page);
  await page.goto("/trade");
  await page.getByRole("main", { name: /Trading Workspace/i }).waitFor({ timeout: 15_000 });

  await page.evaluate(() => {
    window.dispatchEvent(
      new CustomEvent("flinttrade:addWidget", {
        detail: { widgetId: "historicalchain", title: "Historical Chain" },
      }),
    );
  });

  const widget = page.getByLabel("Historical Option Chain widget");
  await expect(widget).toBeVisible();
  await widget.evaluate((element) => {
    element.style.width = "320px";
    element.style.height = "520px";
  });

  const captureRow = widget.locator("#hist-capture-expiry").locator("..");
  const dimensions = await captureRow.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);

  await widget.getByLabel("Expiry to capture").fill("2026-03-26");
  await widget.getByRole("button", { name: "Capture" }).click();

  await expect(widget.getByRole("status")).toContainText("Captured 2 rows for 2026-03-26");
  await expect(widget.getByRole("cell", { name: "24000" })).toBeVisible();
  expect(captureBody).toEqual({ exchange: "NFO" });
});
