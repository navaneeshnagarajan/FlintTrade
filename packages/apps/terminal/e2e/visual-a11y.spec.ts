import type { Page } from "@playwright/test";

import { expect, test } from "./fixture-registry";
import { seedExploreDemoSession } from "./helpers";
import { registerAuthStatus, registerExampleDeskReads, registerPracticeOrderPadReads } from "./visual/desk-mocks";
import {
  GREETED_TODAY,
  RENDERED_LAYA_LABELS,
  VIEWPORTS,
  installDeterminism,
  reviewScreen,
  settle,
  type Viewport,
} from "./visual/support";

const LIVE_AUTHORITY_PAYLOAD = {
  sub: "synthetic-order-pad-operator",
  mode: "live",
  live_mode_unlocked: true,
  exp: 4_102_444_800,
};

const LIVE_AUTHORITY_TOKEN = [
  Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
  Buffer.from(JSON.stringify(LIVE_AUTHORITY_PAYLOAD)).toString("base64url"),
  "synthetic-e2e-signature",
].join(".");

const WORKSPACE_GLOBAL = {
  tabEnableRename: false,
  tabSetEnableSingleTabStretch: true,
  tabSetMinWidth: 100,
  tabSetMinHeight: 80,
};

function persistLayout(name: string, id: string, layout: Record<string, unknown>): string {
  return JSON.stringify({
    state: {
      tabs: [{ id, name, serializedLayout: layout }],
      activeTabId: id,
    },
    version: 0,
  });
}

function orderPadLayout(): Record<string, unknown> {
  return {
    global: WORKSPACE_GLOBAL,
    borders: [],
    layout: {
      type: "row",
      weight: 100,
      children: [
        {
          type: "tabset",
          weight: 100,
          children: [
            { type: "tab", id: "visual-order-pad", component: "orderpad", name: "Order Pad" },
          ],
        },
      ],
    },
  };
}

function tradingDeskLayout(): Record<string, unknown> {
  return {
    global: WORKSPACE_GLOBAL,
    borders: [],
    layout: {
      type: "row",
      weight: 100,
      children: [
        {
          type: "row",
          weight: 100,
          children: [
            {
              type: "tabset",
              weight: 20,
              children: [
                { type: "tab", id: "visual-indices", component: "indexstrip", name: "Indices" },
              ],
            },
            {
              type: "row",
              weight: 52,
              children: [
                {
                  type: "tabset",
                  weight: 65,
                  children: [
                    { type: "tab", id: "visual-positions", component: "positions", name: "Positions" },
                  ],
                },
                {
                  type: "tabset",
                  weight: 35,
                  children: [
                    { type: "tab", id: "visual-risk", component: "riskdashboard", name: "Risk" },
                  ],
                },
              ],
            },
            {
              type: "tabset",
              weight: 28,
              children: [
                { type: "tab", id: "visual-orders", component: "orders", name: "Orders" },
              ],
            },
          ],
        },
      ],
    },
  };
}

async function seedLayout(page: Page, storage: string): Promise<void> {
  await page.addInitScript((raw) => {
    localStorage.setItem("flinttrade:layouts", raw);
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  }, storage);
}

async function expectLaya(page: Page, status: keyof typeof RENDERED_LAYA_LABELS): Promise<void> {
  const chip = page.getByTestId("laya-surface");
  await settle(page, async () => {
    const text = await chip.innerText().catch(() => "");
    return text.replace(/\s+/g, " ").includes(RENDERED_LAYA_LABELS[status]);
  });
  await expect(chip).toHaveText(RENDERED_LAYA_LABELS[status]);
}

function screenKey(name: string, viewport: Viewport): string {
  return `${name}@${viewport.width}`;
}

for (const viewport of VIEWPORTS) {
  test.describe(`visual ${viewport.width}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test("home", async ({ page, syntheticApi }) => {
      await installDeterminism(page);
      await seedExploreDemoSession(page);
      registerExampleDeskReads(syntheticApi);
      await page.goto("/home");
      await settle(page, () => page.getByTestId("orders-card").getByText("BANKNIFTY").isVisible());
      await reviewScreen(page, screenKey("home", viewport), `home-${viewport.width}`);
    });

    test("dashboard", async ({ page, syntheticApi }) => {
      await installDeterminism(page);
      await seedExploreDemoSession(page);
      await seedLayout(
        page,
        persistLayout("Trading Desk", "visual-dashboard", tradingDeskLayout()),
      );
      registerExampleDeskReads(syntheticApi);
      await page.goto("/trade");
      await settle(page, async () => {
        const positions = await page.getByText("Positions", { exact: true }).first().isVisible();
        const risk = await page.getByText("Risk", { exact: true }).first().isVisible();
        return positions && risk;
      });
      await reviewScreen(page, screenKey("dashboard", viewport), `dashboard-${viewport.width}`);
    });

    test("status menu", async ({ page, syntheticApi }) => {
      await installDeterminism(page);
      await seedExploreDemoSession(page);
      registerExampleDeskReads(syntheticApi);
      await page.goto("/home");
      await settle(page, () => page.getByTestId("system-status-btn").isVisible());
      await page.getByTestId("system-status-btn").click();
      await settle(page, () => page.getByTestId("system-status-panel").isVisible());
      await reviewScreen(page, screenKey("status-menu", viewport), `status-menu-${viewport.width}`);
    });

    for (const status of ["ready", "down", "degraded"] as const) {
      test(`laya ${status}`, async ({ page, syntheticApi }) => {
        await installDeterminism(page);
        await seedExploreDemoSession(page);
        registerExampleDeskReads(syntheticApi, { laya: status });
        await page.goto("/home");
        await settle(page, () => page.getByTestId("system-status-btn").isVisible());
        await page.getByTestId("system-status-btn").click();
        await settle(page, () => page.getByTestId("system-status-panel").isVisible());
        await expectLaya(page, status);
        await reviewScreen(
          page,
          screenKey(`laya-${status}`, viewport),
          `laya-${status}-${viewport.width}`,
        );
      });
    }
  });
}

async function openPracticeOrderPad(page: Page): Promise<void> {
  await page.goto("/welcome");
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
        getState: () => { setMode: (mode: "practice") => void };
      };
    };
    authModule.useAuthStore.getState().setLoggedIn(token, "synthetic-order-pad-operator", "");
    modeModule.useModeStore.getState().setMode("practice");
    window.history.pushState(null, "", "/trade");
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, LIVE_AUTHORITY_TOKEN);
  const limitOrderType = page.getByRole("radio", { name: "LIMIT" });
  await settle(page, () => limitOrderType.isVisible());
  await limitOrderType.click();
  await page.getByRole("spinbutton", { name: "Price", exact: true }).fill("123.45");
}

test.describe("order pad before a refusal", () => {
  for (const viewport of VIEWPORTS) {
    test(`order pad before ${viewport.width}`, async ({ page, syntheticApi }) => {
      await installDeterminism(page);
      await seedLayout(page, persistLayout("Practice Order Pad", "visual-order-pad", orderPadLayout()));
      registerExampleDeskReads(syntheticApi);
      registerPracticeOrderPadReads(syntheticApi);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await openPracticeOrderPad(page);
      await reviewScreen(
        page,
        screenKey("order-pad-before", viewport),
        `order-pad-before-${viewport.width}`,
      );
    });
  }
});

test.describe("order pad after a refusal", () => {
  test.use({
    benignConsoleErrors: [
      {
        text: "Failed to load resource: the server responded with a status of 403 (Forbidden)",
        url: "http://localhost:5173/ft-api/api/v1/orders/place",
        expectedCalls: 1,
      },
    ],
  });

  for (const viewport of VIEWPORTS) {
    test(`order pad after ${viewport.width}`, async ({ page, syntheticApi }) => {
      await installDeterminism(page);
      await seedLayout(page, persistLayout("Practice Order Pad", "visual-order-pad", orderPadLayout()));
      registerExampleDeskReads(syntheticApi);
      registerPracticeOrderPadReads(syntheticApi);
      syntheticApi.register({
        name: "reject Practice placement under Live JWT authority",
        method: "POST",
        path: "/ft-api/api/v1/orders/place",
        expectedCalls: 1,
        handler: (request) => {
          expect(request.headers()["authorization"]).toBe(`Bearer ${LIVE_AUTHORITY_TOKEN}`);
          expect(request.headers()["x-flinttrade-mode"]).toBe("practice");
          return {
            status: 403,
            json: {
              status: "error",
              message: "X-FlintTrade-Mode does not match the authenticated mode",
            },
          };
        },
      });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await openPracticeOrderPad(page);
      await page.getByRole("button", { name: "Practice Buy" }).click();
      const review = page.getByRole("dialog", { name: "Review Practice order" });
      await expect(review).toBeVisible();
      await review.getByRole("button", { name: "Confirm simulated Practice order" }).click();
      await expect(page.getByRole("alert").filter({
        hasText: "X-FlintTrade-Mode does not match the authenticated mode",
      })).toBeVisible();
      await reviewScreen(
        page,
        screenKey("order-pad-after", viewport),
        `order-pad-after-${viewport.width}`,
      );
    });
  }
});

test.describe("signed-out screens", () => {
  for (const viewport of VIEWPORTS) {
    test(`sign-in ${viewport.width}`, async ({ page, syntheticApi }) => {
      await installDeterminism(page);
      await page.addInitScript((today) => {
        sessionStorage.setItem("flinttrade:greeted-today", today);
      }, GREETED_TODAY);
      registerAuthStatus(syntheticApi, {
        is_setup: true,
        is_locked: false,
        has_pin: false,
        totp_enabled: false,
        migration_blocked: null,
      });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/welcome");
      await settle(page, () => page.getByRole("heading", { name: "Welcome Back" }).isVisible());
      await reviewScreen(page, screenKey("sign-in", viewport), `sign-in-${viewport.width}`);
    });

    test(`setup ${viewport.width}`, async ({ page, syntheticApi }) => {
      await installDeterminism(page);
      registerAuthStatus(syntheticApi, {
        is_setup: false,
        is_locked: false,
        has_pin: false,
        totp_enabled: false,
        vault_open: false,
        setup_finished: false,
        migration_blocked: null,
      });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/setup");
      await settle(page, () => page.getByRole("heading", { name: "Set up FlintTrade" }).isVisible());
      await reviewScreen(page, screenKey("setup", viewport), `setup-${viewport.width}`);
    });

    test(`two-operator ${viewport.width}`, async ({ page, syntheticApi }) => {
      await installDeterminism(page);
      await page.addInitScript(() => {
        sessionStorage.setItem("flinttrade:auth-session", JSON.stringify({
          token: "visual-session-token",
          username: "Example Operator",
          expiresAt: "2099-01-01T00:00:00.000Z",
        }));
      });
      registerAuthStatus(syntheticApi, {
        is_setup: true,
        is_locked: false,
        has_pin: false,
        totp_enabled: false,
        migration_blocked: "two_operators",
      });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto("/welcome");
      await settle(page, () => page.getByRole("heading", {
        name: "FlintTrade couldn't finish updating",
      }).isVisible());
      await reviewScreen(page, screenKey("two-operator", viewport), `two-operator-${viewport.width}`);
    });
  }
});
