import type { Page, Request } from "@playwright/test";

import { expect, test } from "./fixture-registry";

const LIVE_AUTHORITY_PAYLOAD = {
  sub: "synthetic-order-pad-operator",
  mode: "live",
  live_mode_unlocked: true,
  exp: 4_102_444_800,
};
// This deterministic browser token proves the UI/transport authority mismatch.
// Production signature verification and no-dispatch behaviour remain covered by
// the signed-token Python regression; this journey deliberately has no backend.
const LIVE_AUTHORITY_TOKEN = [
  Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
  Buffer.from(JSON.stringify(LIVE_AUTHORITY_PAYLOAD)).toString("base64url"),
  "synthetic-e2e-signature",
].join(".");

test.use({
  // Chromium logs an exact resource error for the deliberate backend-equivalent
  // 403. The UI error is asserted below; every other console error stays fatal.
  benignConsoleErrors: [
    {
      text: "Failed to load resource: the server responded with a status of 403 (Forbidden)",
      url: "http://localhost:5173/ft-api/api/v1/orders/place",
      expectedCalls: 1,
    },
  ],
});

async function seedOrderPadWorkspace(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem(
      "flinttrade:layouts",
      JSON.stringify({
        state: {
          tabs: [
            {
              id: "practice-order-pad-workspace",
              name: "Practice Order Pad",
              serializedLayout: {
                global: {
                  tabEnableRename: false,
                  tabSetEnableSingleTabStretch: true,
                  tabSetMinWidth: 100,
                  tabSetMinHeight: 80,
                },
                borders: [],
                layout: {
                  type: "row",
                  weight: 100,
                  children: [
                    {
                      type: "tabset",
                      weight: 100,
                      children: [
                        {
                          type: "tab",
                          id: "practice-order-pad-widget",
                          component: "orderpad",
                          name: "Order Pad",
                        },
                      ],
                    },
                  ],
                },
              },
            },
          ],
          activeTabId: "practice-order-pad-workspace",
        },
        version: 0,
      }),
    );
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  });
}

async function installMismatchedPracticeAuthority(page: Page): Promise<void> {
  await page.evaluate(async (token) => {
    const importModule = new Function("path", "return import(path)") as (
      path: string,
    ) => Promise<Record<string, unknown>>;
    const authModule = await importModule("/src/stores/authStore.ts") as {
      useAuthStore: {
        getState: () => {
          setLoggedIn: (jwt: string, username: string, expiresAt: string) => void;
        };
      };
    };
    const modeModule = await importModule("/src/stores/modeStore.ts") as {
      useModeStore: {
        getState: () => {
          setMode: (mode: "practice") => void;
        };
      };
    };

    authModule.useAuthStore
      .getState()
      .setLoggedIn(token, "synthetic-order-pad-operator", "");
    modeModule.useModeStore.getState().setMode("practice");
    window.history.pushState(null, "", "/trade");
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, LIVE_AUTHORITY_TOKEN);
}

function expectAuthenticatedGet(request: Request): void {
  expect(request.headers()["authorization"]).toBe(`Bearer ${LIVE_AUTHORITY_TOKEN}`);
  expect(request.postData()).toBeNull();
}

test("a Practice Order Pad confirmation fails closed against Live JWT authority", async ({
  page,
  syntheticApi,
}) => {
  // Freeze application timers before mounting the product route. Terminal polls
  // safety state and accounts; wall-clock refetches must not change exact counts.
  const controlledTime = new Date("2026-08-11T00:00:00.000Z");
  await page.clock.install({ time: controlledTime });
  await page.clock.pauseAt(controlledTime);
  await seedOrderPadWorkspace(page);
  syntheticApi.register({
    name: "list gateway accounts for the Practice workspace",
    method: "GET",
    path: "/ft-api/v1/accounts",
    expectedCalls: 1,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return { json: { accounts: [] } };
    },
  });
  syntheticApi.register({
    name: "list native accounts for Practice market-data resolution",
    method: "GET",
    path: "/ft-api/api/v1/native/accounts",
    // Auth/mode activation and the lazy Order Pad observer can settle in either
    // order, producing five or six legitimate mount-time reads. The bounded
    // range still aborts any seventh request and authenticates every allowed one.
    expectedCalls: { minimum: 5, maximum: 6 },
    handler: (request) => {
      expectAuthenticatedGet(request);
      return { json: { accounts: [] } };
    },
  });
  syntheticApi.register({
    name: "hydrate blank OpenAlgo configuration",
    method: "GET",
    path: "/ft-api/v1/config/openalgo",
    expectedCalls: 2,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return {
        json: {
          status: "success",
          data: {
            api_key_configured: false,
            host: "",
            port: "",
            ws_port: "",
          },
        },
      };
    },
  });
  syntheticApi.register({
    name: "read Practice sandbox capital",
    method: "GET",
    path: "/ft-api/v1/sandbox/capital",
    expectedCalls: 2,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return {
        json: {
          status: "success",
          data: {
            capital: {
              initial: 100_000,
              current: 100_000,
              available: 100_000,
              used_margin: 0,
              realised_pnl: 0,
              unrealised_pnl: 0,
            },
          },
        },
      };
    },
  });
  syntheticApi.register({
    name: "read empty Practice sandbox positions",
    method: "GET",
    path: "/ft-api/v1/sandbox/positions",
    expectedCalls: 2,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return { json: { status: "success", data: { positions: [] } } };
    },
  });
  syntheticApi.register({
    name: "read unconfigured advisor status",
    method: "GET",
    path: "/ft-api/api/v1/advisor/status",
    expectedCalls: 2,
    handler: (request) => {
      expect(request.headers()["authorization"]).toBeUndefined();
      expect(request.postData()).toBeNull();
      return {
        json: {
          status: "success",
          data: { configured: false, provider: "none", model: "none" },
        },
      };
    },
  });
  syntheticApi.register({
    name: "read inactive safety configuration",
    method: "GET",
    path: "/ft-api/api/v1/safety/config",
    expectedCalls: 1,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return {
        json: {
          status: "success",
          data: {
            l1_order: {},
            l2_position: {},
            l3_portfolio: {},
            l4_pnl: {},
            l5_kill: {},
          },
        },
      };
    },
  });
  syntheticApi.register({
    name: "read broker capabilities without a connected account",
    method: "GET",
    path: "/ft-api/api/v1/broker/capabilities",
    expectedCalls: 1,
    handler: (request) => {
      expectAuthenticatedGet(request);
      return {
        json: {
          status: "success",
          data: {
            broker_name: "Practice",
            broker_type: "multi",
            supported_exchanges: ["NSE", "BSE", "NFO", "BFO", "MCX"],
            features: {},
          },
        },
      };
    },
  });
  syntheticApi.register({
    name: "reject Practice placement under Live JWT authority",
    method: "POST",
    path: "/ft-api/api/v1/orders/place",
    expectedCalls: 1,
    handler: (request) => {
      const authorization = request.headers()["authorization"];
      expect(authorization).toBe(`Bearer ${LIVE_AUTHORITY_TOKEN}`);
      expect(request.headers()["x-flinttrade-mode"]).toBe("practice");
      expect(request.headers()["x-api-key"]).toBeUndefined();
      expect(request.headers()["content-type"]).toBe("application/json");

      const presentedToken = authorization?.replace(/^Bearer /, "") ?? "";
      const tokenPayload = presentedToken.split(".")[1];
      expect(JSON.parse(Buffer.from(tokenPayload, "base64url").toString("utf8"))).toEqual(
        LIVE_AUTHORITY_PAYLOAD,
      );
      expect(request.postDataJSON()).toEqual({
        symbol: "NIFTY",
        exchange: "NSE",
        action: "BUY",
        product: "MIS",
        orderType: "LIMIT",
        quantity: 1,
        price: 123.45,
        triggerPrice: 0,
        strategy: "FlintOrderPad",
        order_type: "LIMIT",
        trigger_price: 0,
      });
      return {
        status: 403,
        json: {
          status: "error",
          message: "X-FlintTrade-Mode does not match the authenticated mode",
        },
      };
    },
  });

  await page.goto("/welcome");
  await installMismatchedPracticeAuthority(page);

  await expect(page).toHaveURL(/\/trade$/);
  const limitOrderType = page.getByRole("radio", { name: "LIMIT" });
  // Lazy widget imports can schedule immediate work after their network module
  // resolves. Advance in bounded increments, never reaching the first poll.
  for (let advanced = 0; advanced < 4_000 && !(await limitOrderType.isVisible()); advanced += 100) {
    await page.clock.runFor(100);
  }
  await expect(page.getByText("Order Pad", { exact: true }).first()).toBeVisible();
  await expect(limitOrderType).toBeVisible();
  await expect.poll(
    () => syntheticApi.callCount("GET", "/ft-api/api/v1/native/accounts"),
  ).toBeGreaterThanOrEqual(5);
  expect(syntheticApi.callCount("GET", "/ft-api/api/v1/native/accounts")).toBeLessThanOrEqual(6);
  await limitOrderType.click();
  await page.getByRole("spinbutton", { name: "Price", exact: true }).fill("123.45");
  await page.getByRole("button", { name: "Practice Buy" }).click();

  const review = page.getByRole("dialog", { name: "Review Practice order" });
  await expect(review).toBeVisible();
  await expect(review.getByText("NIFTY · NSE", { exact: true })).toBeVisible();
  await expect(review.getByText("₹123.45", { exact: true })).toHaveCount(2);
  await expect(review.getByText("₹123.45", { exact: true }).first()).toBeVisible();
  await review.getByRole("button", { name: "Confirm simulated Practice order" }).click();

  await expect(
    page.getByRole("alert").filter({
      hasText: "X-FlintTrade-Mode does not match the authenticated mode",
    }),
  ).toBeVisible();
  await expect(review).toBeVisible();
  await expect(page.getByText(/Order placed(?: · ID:)?/i)).toHaveCount(0);
});
