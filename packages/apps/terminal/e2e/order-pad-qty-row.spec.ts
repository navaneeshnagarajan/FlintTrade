import fs from "node:fs/promises";
import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

const SHOT_DIR = "/workspace/ux-438-merge/fix";
const WIDTHS = [280, 320, 400] as const;
const NIFTY_SYMBOL = "NIFTY-OCT2026-FUT";
const NIFTY_CAP = "Lot 65 · Max 1,755 per order";
const LOT_MULTIPLE = "Quantity must be a multiple of the lot size (65).";
const FREEZE = "Max 1,755 per order for NIFTY. Place smaller orders.";
const UNKNOWN = "Not placed. The lot size for SENSEX isn't verified.";
const BSE_WARNING = "Max per order for SENSEX may be 1,000 qty. Split if the broker rejects.";
const SENSEX_WARN = "SENSEX26NOV2680000CE";
const SENSEX_UNKNOWN = "SENSEX26DEC85000CE";
const TOKEN = [
  Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
  Buffer.from(JSON.stringify({
    sub: "synthetic-order-pad-row",
    mode: "practice",
    live_mode_unlocked: true,
    exp: 4_102_444_800,
  })).toString("base64url"),
  "synthetic-e2e-signature",
].join(".");

async function mockApi(page: Page): Promise<void> {
  await page.route("**/ft-api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const symbol = url.searchParams.get("symbol") ?? url.searchParams.get("query") ?? "";

    if (path.endsWith("/api/v1/ping") || path.endsWith("/health")) {
      return route.fulfill({ json: { status: "ok", laya: "ready", laya_practice: "ready" } });
    }
    if (path.endsWith("/instrument-lots")) {
      return route.fulfill({ json: { rows: [] } });
    }
    if (path.endsWith("/native/accounts") && route.request().method() === "GET") {
      return route.fulfill({
        json: {
          accounts: [{
            adapter_id: "dhan",
            account_id: "D1",
            label: "Dhan",
            is_primary: true,
            has_session: true,
            read_only: false,
            needs_relogin: false,
            login_retryable: false,
          }],
        },
      });
    }
    if (path.endsWith("/search")) {
      if (symbol === SENSEX_UNKNOWN) {
        return route.fulfill({ json: { status: "success", data: [] } });
      }
      if (symbol === SENSEX_WARN) {
        return route.fulfill({
          json: {
            status: "success",
            data: [{
              symbol: SENSEX_WARN,
              name: "SENSEX",
              exchange: "BFO",
              instrumenttype: "OPTIDX",
              lotsize: 20,
              tick_size: 0.05,
            }],
          },
        });
      }
      if (symbol === NIFTY_SYMBOL || /NIFTY/.test(symbol)) {
        return route.fulfill({
          json: {
            status: "success",
            data: [{
              symbol: symbol || NIFTY_SYMBOL,
              name: "NIFTY",
              exchange: url.searchParams.get("exchange") || "NFO",
              instrumenttype: /FUT$/.test(symbol) ? "FUTIDX" : "OPTIDX",
              lotsize: 65,
              freezeQty: 1800,
              freeze_qty: 1800,
              tick_size: 0.05,
            }],
          },
        });
      }
      return route.fulfill({ json: { status: "success", data: [] } });
    }
    if (/\/native\/accounts\/dhan\/D1\/(quotes|ltp)$/.test(path)) {
      const ltp = /SENSEX/.test(symbol) ? 50 : 120;
      return route.fulfill({
        json: {
          status: "success",
          data: {
            symbol,
            exchange: url.searchParams.get("exchange"),
            ltp,
            bid: ltp - 0.5,
            ask: ltp + 0.5,
            prev_close: ltp,
            open: ltp,
            high: ltp,
            low: ltp,
            volume: 1000,
          },
        },
      });
    }
    if (path.endsWith("/expiry")) {
      return route.fulfill({ json: { status: "success", data: { expiry: ["24-NOV-2026"] } } });
    }
    if (path.endsWith("/optionchain")) {
      return route.fulfill({ json: { status: "success", data: { underlying_ltp: 24010, chain: [] } } });
    }
    if (path.endsWith("/sandbox/funds")) {
      return route.fulfill({
        json: {
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
        },
      });
    }
    if (path.endsWith("/sandbox/positions")) {
      return route.fulfill({ json: { status: "success", data: { positions: [] } } });
    }
    if (path.endsWith("/sandbox/orders") || path.endsWith("/sandbox/trades")) {
      return route.fulfill({ json: { status: "success", data: { orders: [], trades: [] } } });
    }
    if (path.endsWith("/auth/status")) {
      return route.fulfill({
        json: {
          status: "success",
          data: {
            is_setup: true,
            is_locked: false,
            has_pin: false,
            totp_enabled: false,
            vault_open: true,
            setup_finished: true,
            migration_blocked: null,
          },
        },
      });
    }
    if (path.includes("/broker/capabilities")) {
      return route.fulfill({
        json: {
          status: "success",
          data: {
            broker_name: "Practice",
            broker_type: "multi",
            supported_exchanges: ["NSE", "BSE", "NFO", "BFO", "MCX"],
            features: {},
          },
        },
      });
    }
    if (path.endsWith("/system/diagnostics")) {
      return route.fulfill({ json: { status: "success", data: {} } });
    }
    if (path.endsWith("/config/llm")) {
      return route.fulfill({ json: { status: "success", data: { provider: "", host: "", model: "", api_key_configured: false } } });
    }
    if (path.endsWith("/advisor/status")) {
      return route.fulfill({ json: { status: "success", data: { status: "ready" } } });
    }
    if (path.endsWith("/safety/config")) {
      return route.fulfill({
        json: { status: "success", data: { l1_order: {}, l2_position: {}, l3_portfolio: {}, l4_pnl: {}, l5_kill: {} } },
      });
    }
    return route.fulfill({ json: { status: "success", data: {} } });
  });
}

async function bootPad(page: Page, symbol: string, exchange: string): Promise<void> {
  await mockApi(page);
  await page.addInitScript(({ symbol, exchange }) => {
    localStorage.setItem(
      "flinttrade:app-layouts:v1:terminal",
      JSON.stringify({
        Current: {
          global: {
            tabEnableRename: false,
            tabSetEnableSingleTabStretch: true,
            tabSetMinWidth: 80,
            tabSetMinHeight: 80,
          },
          borders: [],
          layout: {
            type: "row",
            weight: 100,
            children: [{
              type: "tabset",
              weight: 100,
              children: [{
                type: "tab",
                id: "qty-row-order-pad",
                component: "orderpad",
                name: "Order Pad",
                config: { symbol, exchange },
              }],
            }],
          },
        },
      }),
    );
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
    localStorage.setItem("flinttrade:theme", "light");
  }, { symbol, exchange });
  await page.setViewportSize({ width: 1280, height: 1400 });
  await page.goto("/welcome", { waitUntil: "domcontentloaded" });
  await page.evaluate(async ({ token }) => {
    const importModule = new Function("path", "return import(path)") as (
      path: string,
    ) => Promise<Record<string, unknown>>;
    const theme = await importModule("/src/stores/themeStore.ts") as {
      useThemeStore: { getState: () => { setMode: (mode: string) => void } };
    };
    const auth = await importModule("/src/stores/authStore.ts") as {
      useAuthStore: { getState: () => { setLoggedIn: (jwt: string, username: string, expiresAt: string) => void } };
    };
    const mode = await importModule("/src/stores/modeStore.ts") as {
      useModeStore: { getState: () => { setMode: (mode: "practice") => void } };
    };
    theme.useThemeStore.getState().setMode("light");
    auth.useAuthStore.getState().setLoggedIn(token, "synthetic-order-pad-row", "");
    mode.useModeStore.getState().setMode("practice");
    window.history.pushState(null, "", "/terminal");
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, { token: TOKEN });
  await expect(page.getByRole("button", { name: "Practice Buy" })).toBeVisible({ timeout: 30_000 });
}

async function constrainPad(page: Page, width: number): Promise<void> {
  await page.evaluate((panelWidth) => {
    const pad = document.querySelector("[data-tour-target='order-pad']");
    const tab = (pad?.closest(".flexlayout__tab") ?? pad);
    if (!(tab instanceof HTMLElement)) return;
    tab.style.width = `${panelWidth}px`;
    tab.style.maxWidth = `${panelWidth}px`;
    tab.style.minWidth = `${panelWidth}px`;
    tab.style.flex = `0 0 ${panelWidth}px`;
    tab.style.boxSizing = "border-box";
    const parent = tab.parentElement;
    if (parent) {
      parent.style.display = "flex";
      parent.style.justifyContent = "flex-start";
    }
  }, width);
  await page.waitForTimeout(100);
}

async function buyY(page: Page): Promise<number> {
  const box = await page.getByRole("button", { name: "Practice Buy" }).boundingBox();
  expect(box).toBeTruthy();
  return Math.round(box!.y);
}

async function assertCapNotTruncated(page: Page, label: string): Promise<void> {
  const hint = page.locator("#orderpad-qty-hint");
  await expect(hint).toHaveText(label);
  const metrics = await hint.evaluate((el) => {
    const style = getComputedStyle(el);
    return {
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      overflow: style.textOverflow,
      whiteSpace: style.whiteSpace,
    };
  });
  expect(metrics.overflow).not.toBe("ellipsis");
  expect(metrics.whiteSpace).not.toBe("nowrap");
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth);
}

async function shot(page: Page, width: number, state: string): Promise<void> {
  await fs.mkdir(SHOT_DIR, { recursive: true });
  await page.locator("[data-tour-target='order-pad']").screenshot({
    path: `${SHOT_DIR}/pad-${width}-${state}.png`,
  });
}

test.describe("Order Pad reserved quantity row", () => {
  test("Buy stays put for refusals, an unknown lot, and the BSE warning", async ({ page }) => {
    test.setTimeout(120_000);
    const shifts: Array<{ width: number; state: string; shift: number }> = [];

    await bootPad(page, NIFTY_SYMBOL, "NFO");
    await expect(page.getByText(NIFTY_CAP, { exact: true })).toBeVisible();
    const quantity = page.getByRole("spinbutton", { name: "Quantity" });
    const buy = page.getByRole("button", { name: "Practice Buy" });

    for (const width of WIDTHS) {
      await constrainPad(page, width);
      await quantity.fill("65");
      await expect(page.getByText(LOT_MULTIPLE)).toHaveCount(0);
      await expect(page.getByText(FREEZE)).toHaveCount(0);
      await assertCapNotTruncated(page, NIFTY_CAP);
      const emptyY = await buyY(page);
      await shot(page, width, "empty");

      await quantity.fill("100");
      await buy.click();
      await expect(page.getByRole("alert")).toHaveText(LOT_MULTIPLE);
      shifts.push({ width, state: "lot-multiple", shift: await buyY(page) - emptyY });
      await assertCapNotTruncated(page, NIFTY_CAP);
      await shot(page, width, "lot");

      await quantity.fill("65");
      await expect(page.getByText(LOT_MULTIPLE)).toHaveCount(0);
      expect(await buyY(page)).toBe(emptyY);

      await quantity.fill("1820");
      await buy.click();
      await expect(page.getByRole("alert")).toHaveText(FREEZE);
      shifts.push({ width, state: "freeze", shift: await buyY(page) - emptyY });
      await assertCapNotTruncated(page, NIFTY_CAP);
      await shot(page, width, "freeze");

      await quantity.fill("65");
      await expect(page.getByText(FREEZE)).toHaveCount(0);
      expect(await buyY(page)).toBe(emptyY);
    }

    await bootPad(page, SENSEX_WARN, "BFO");
    await expect(page.getByText("Lot: 20", { exact: true })).toBeVisible();
    await page.getByRole("radio", { name: "LIMIT" }).click();
    await page.getByRole("spinbutton", { name: "Price" }).fill("200");
    const sensexQty = page.getByRole("spinbutton", { name: "Quantity" });
    for (const width of WIDTHS) {
      await constrainPad(page, width);
      await sensexQty.fill("20");
      await expect(page.getByText(BSE_WARNING)).toHaveCount(0);
      const emptyY = await buyY(page);
      await sensexQty.fill("1020");
      const row = page.locator("#orderpad-qty-error");
      await expect(row).toHaveText(BSE_WARNING);
      await expect(row).toHaveAttribute("role", "status");
      shifts.push({ width, state: "bse-warning", shift: await buyY(page) - emptyY });
      await expect(page.locator("#orderpad-qty-hint")).toHaveText("Lot: 20");
      await shot(page, width, "bse");
    }
    await page.getByRole("button", { name: "Practice Buy" }).click();
    await expect(page.getByRole("dialog", { name: "Review Practice order" })).toBeVisible();
    await page.keyboard.press("Escape");

    await bootPad(page, SENSEX_UNKNOWN, "BFO");
    const unknownBuy = page.getByRole("button", { name: "Practice Buy" });
    const unknownQty = page.getByRole("spinbutton", { name: "Quantity" });
    for (const width of WIDTHS) {
      await constrainPad(page, width);
      await unknownQty.fill("1");
      await expect(page.getByText(UNKNOWN)).toHaveCount(0);
      const emptyY = await buyY(page);
      await unknownBuy.click();
      await expect(page.getByRole("alert")).toHaveText(UNKNOWN);
      shifts.push({ width, state: "unknown-lot", shift: await buyY(page) - emptyY });
      await shot(page, width, "unknown");
      await unknownQty.fill("2");
      await expect(page.getByText(UNKNOWN)).toHaveCount(0);
      expect(await buyY(page)).toBe(emptyY);
    }

    expect(shifts.every((row) => row.shift === 0), JSON.stringify(shifts)).toBe(true);
    await fs.writeFile(
      `${SHOT_DIR}/metrics.json`,
      `${JSON.stringify({ shifts, passed: true }, null, 2)}
`,
    );
  });
});
