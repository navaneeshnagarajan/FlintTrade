import fs from "node:fs/promises";
import type { Locator, Page, Request, TestInfo } from "@playwright/test";
import {
  expect,
  registerExploreAdvisorStatusProbe,
  registerOperatorStatusProbes,
  test as registryTest,
  type HttpMethod,
  type SyntheticFixtureRegistry,
  type SyntheticHandlerRegistration,
  type SyntheticResponse,
} from "./fixture-registry";

export const ACCOUNT_A = "SYNTHETIC-A";
export const ACCOUNT_B = "SYNTHETIC-B";
export const BROKER = "dhan";
export const FIXED_TIME = new Date("2026-08-11T00:00:00.000Z");
export const LIVE_TOKEN = [
  Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
  Buffer.from(JSON.stringify({
    sub: "synthetic-order-flow-operator", mode: "live", live_mode_unlocked: true, exp: 4_102_444_800,
  })).toString("base64url"),
  "synthetic-presentation-not-a-signature",
].join(".");

export const CANCEL_WARNING = "Cancel pending. This order may still fill.";
export const CHILD_CAVEAT = "Trigger status does not confirm the outcome of any spawned order. Check broker positions and orders.";
export const EXECUTION_WARNING = "This prioritises execution. The fill price may differ significantly, and execution isn't guaranteed.";
export const GTT_EMPTY = "No resting forever orders for this broker account.";
export const GTT_READ_FROZEN = "Native broker HTTP reads are unavailable until the read cutover";
export const GTT_REFUSAL = "Not placed. GTT orders aren't supported right now.";

export function foreverPath(account = ACCOUNT_A): string {
  return `/ft-api/api/v1/orders/forever?broker=${BROKER}&account_id=${account}`;
}

export function nativePath(kind: string, account = ACCOUNT_A, broker = BROKER): string {
  return `/ft-api/api/v1/native/accounts/${broker}/${account}/${kind}`;
}

export function triggerRow(account = ACCOUNT_A, status = "ACTIVE") {
  return {
    order_id: `SYNTHETIC-GTT-${account}`, broker: BROKER, account_id: account,
    symbol: "SYNTHETIC-FUTURE", exchange: "NFO", action: "SELL", product: "NRML",
    quantity: 75, trigger_price: 120, price: 119, status,
    order_flag: "SINGLE", pricetype: "LIMIT", validity: "DAY", disclosed_quantity: 0,
  };
}

export function positionRow(account = ACCOUNT_A) {
  return {
    symbol: account === ACCOUNT_A ? "SYNTHETIC-ALPHA" : "SYNTHETIC-BETA",
    exchange: "NSE", product: "CNC", quantity: 10, averagePrice: 100,
    ltp: 101, pnl: 10, pnlPercent: 1,
  };
}

export function exitRow(account = ACCOUNT_A, status = "CANCEL_PENDING") {
  return {
    orderId: `SYNTHETIC-EXIT-${account}`, symbol: positionRow(account).symbol,
    exchange: "NSE", action: "SELL", product: "CNC", quantity: 10,
    price: 0, orderType: "MARKET", status, strategy: "FlintPositions", timestamp: "",
  };
}

export function assertRequest(request: Request, method: HttpMethod, path: string): void {
  const url = new URL(request.url());
  expect(url.origin).toBe("http://localhost:5173");
  expect(`${url.pathname}${url.search}`).toBe(path);
  expect(request.method()).toBe(method);
  expect(request.headers()["authorization"]).toBe(`Bearer ${LIVE_TOKEN}`);
  expect(request.headers()["x-api-key"]).toBeUndefined();
  if (method === "GET" || method === "DELETE") expect(request.postData()).toBeNull();
  if (method !== "GET") expect(request.headers()["x-flinttrade-mode"]).toBe("live");
  if (method === "POST" || method === "PUT") {
    expect(request.headers()["content-type"]).toBe("application/json");
  }
}

export function registerRead(
  registry: SyntheticFixtureRegistry,
  path: string,
  response: SyntheticResponse | ((request: Request) => SyntheticResponse | Promise<SyntheticResponse>),
  expectedCalls: SyntheticHandlerRegistration["expectedCalls"] = 1,
  readPhase?: SyntheticHandlerRegistration["readPhase"],
): void {
  registry.register({
    name: `presentation read ${path}${readPhase ? ` [${readPhase}]` : ""}`, method: "GET", path, expectedCalls,
    readPhase,
    handler: (request) => {
      assertRequest(request, "GET", path);
      return typeof response === "function" ? response(request) : response;
    },
  });
}

/**
 * Real shell read contracts only. Connected readiness comes from the registered
 * native account response and production hydration; no readiness function,
 * query hook, transport client, or store selector is replaced.
 */
export function registerDeskReads(
  registry: SyntheticFixtureRegistry,
  accountSwitch = false,
  options: { broker?: string; accountIds?: string[]; hasSession?: boolean; readOnly?: boolean; nativeAccounts?: boolean; marketScopeVisits?: number } = {},
): void {
  const broker = options.broker ?? BROKER;
  const accounts = options.accountIds ?? [ACCOUNT_A, ACCOUNT_B];
  // A same-account Live -> Practice -> Live round trip re-arms the production
  // market hooks on each mode-scoped visit. Default journeys retain their old
  // two-call cap; the notification journey declares exactly three visits.
  const marketReads = { minimum: 0, maximum: options.marketScopeVisits ?? 2 };
  // Shell StrictMode, session-fenced discovery, four MCX expiry lookups and
  // six sequential index quote reads all use this exact catalogue endpoint.
  // The paused clock prevents recurring polls; excess discovery stays fatal.
  const mountReads = { minimum: 1, maximum: accountSwitch ? 56 : 28 };
  if (options.nativeAccounts !== false) registerRead(registry, "/ft-api/api/v1/native/accounts", {
    json: { accounts: accounts.map((account, index) => ({
      adapter_id: broker, account_id: account, label: account, is_primary: index === 0,
      has_session: options.hasSession ?? true, read_only: options.readOnly ?? false, needs_relogin: false, login_retryable: false,
    })) },
  }, mountReads);
  registry.register({
    name: "presentation auth status", method: "GET", path: "/ft-api/v1/auth/status",
    expectedCalls: { minimum: 1, maximum: 4 },
    handler: (request) => {
      expect(request.method()).toBe("GET");
      expect(request.postData()).toBeNull();
      const authorization = request.headers()["authorization"];
      if (authorization !== undefined) expect(authorization).toBe(`Bearer ${LIVE_TOKEN}`);
      return { json: { status: "success", data: {
        is_setup: true, is_locked: false, has_pin: false, totp_enabled: false,
      } } };
    },
  });
  registerRead(registry, "/ft-api/api/v1/safety/config", {
    json: { status: "success", data: { l1_order: {}, l2_position: {}, l3_portfolio: {}, l4_pnl: {}, l5_kill: {} } },
  }, 1);
  for (const account of accounts) {
    registerRead(registry, `${nativePath("timings", account, broker)}`, {
      json: { status: "success", data: [] },
    }, marketReads);
    for (const commodity of ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"]) {
      registerRead(registry, `${nativePath("expiry", account, broker)}?symbol=${commodity}&exchange=MCX`, {
        json: { status: "success", data: [] },
      }, marketReads);
    }
    for (const [symbol, exchange] of [
      ["NIFTY", "NSE_INDEX"], ["BANKNIFTY", "NSE_INDEX"], ["SENSEX", "BSE_INDEX"],
      ["INDIAVIX", "NSE_INDEX"], ["FINNIFTY", "NSE_INDEX"], ["NIFTYIT", "NSE_INDEX"],
      ["GOLD", "MCX"], ["SILVER", "MCX"], ["CRUDEOIL", "MCX"], ["NATURALGAS", "MCX"],
    ]) {
      registerRead(registry, `${nativePath("quotes", account, broker)}?symbol=${symbol}&exchange=${exchange}`, {
        json: { status: "success", data: { symbol, exchange, ltp: 100, prev_close: 100 } },
      }, marketReads);
    }
    const symbols = [
      "NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY", "BSE_INDEX:SENSEX", "NSE_INDEX:INDIAVIX",
      "NSE_INDEX:FINNIFTY", "NSE_INDEX:NIFTYIT", "MCX:GOLD", "MCX:SILVER", "MCX:CRUDEOIL", "MCX:NATURALGAS",
    ];
    const query = new URLSearchParams({ symbols: symbols.join(",") }).toString();
    registerRead(registry, `${nativePath("quotes", account, broker)}?${query}`, {
      json: { status: "success", data: symbols.map((key) => {
        const [exchange, symbol] = key.split(":");
        return { symbol, exchange, ltp: 100, prev_close: 100 };
      }) },
    }, marketReads);
  }
  registerExploreAdvisorStatusProbe(registry, { expectedCalls: { minimum: 2, maximum: 6 } });
  registerOperatorStatusProbes(registry, {
    expectedCalls: { minimum: 1, maximum: 4 }, laya: "ready",
  });
}

export function registerAccountBooks(
  registry: SyntheticFixtureRegistry,
  options: {
    account?: string;
    positions?: SyntheticResponse | ((request: Request) => SyntheticResponse | Promise<SyntheticResponse>);
    orders?: SyntheticResponse | ((request: Request) => SyntheticResponse | Promise<SyntheticResponse>);
    positionCalls?: SyntheticHandlerRegistration["expectedCalls"];
    orderCalls?: SyntheticHandlerRegistration["expectedCalls"];
    orderReadPhase?: SyntheticHandlerRegistration["readPhase"];
  } = {},
): void {
  const account = options.account ?? ACCOUNT_A;
  registerRead(registry, nativePath("positions", account), options.positions ?? {
    json: { status: "success", data: [positionRow(account)] },
  }, options.positionCalls ?? 1);
  registerRead(registry, nativePath("orders", account), options.orders ?? {
    json: { status: "success", data: [] },
  }, options.orderCalls ?? { minimum: 1, maximum: 2 }, options.orderReadPhase);
  registerRead(registry, nativePath("funds", account), {
    json: { status: "success", data: { available_balance: 100_000, used_margin: 0, total_balance: 100_000 } },
  }, { minimum: 0, maximum: 2 });
}

export function positionSurface(page: Page): Locator {
  // Radix dialogs aria-hide their background without removing its rendered
  // book. Keep that same presentation seam addressable while a B dialog is up;
  // toBeVisible still requires actual rendered geometry.
  return page.getByRole("tabpanel", { name: "Positions", exact: true, includeHidden: true }).first();
}

export function deferredResponse() {
  let release!: (response: SyntheticResponse) => void;
  const promise = new Promise<SyntheticResponse>((resolve) => { release = resolve; });
  return { promise, release };
}

export async function mountWidget(page: Page, component: "foreverorders" | "positions", narrowSibling = false): Promise<void> {
  await page.clock.install({ time: FIXED_TIME });
  await page.clock.pauseAt(FIXED_TIME);
  await page.addInitScript(({ widget, sibling }) => {
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
    localStorage.setItem("flinttrade:layouts", JSON.stringify({ state: {
      tabs: [{ id: "synthetic-order-flow", name: "Synthetic presentation only", serializedLayout: {
        global: { tabEnableRename: false, tabSetEnableSingleTabStretch: true, tabSetMinWidth: 100, tabSetMinHeight: 80 },
        borders: [], layout: { type: "row", weight: 100, children: [{
          type: "tabset", weight: sibling ? 60 : 100, children: [{
            type: "tab", id: "synthetic-order-flow-widget", component: widget,
            name: widget === "foreverorders" ? "Forever (GTT) Orders" : "Positions",
          }],
        }, ...(sibling ? [{
          type: "tabset", weight: 40, children: [{ type: "tab", id: "synthetic-narrow-sibling", component: widget, name: "Narrow Positions" }],
        }] : [])] },
      } }], activeTabId: "synthetic-order-flow",
    }, version: 0 }));
    const observedWindow = window as Window & { __presentationNotifications?: unknown[] };
    observedWindow.__presentationNotifications = [];
    window.addEventListener("flinttrade:notify", (event) => {
      observedWindow.__presentationNotifications?.push((event as CustomEvent<unknown>).detail);
    });
  }, { widget: component, sibling: narrowSibling });

  await page.goto("/welcome");
  await page.evaluate(async ({ token, account, widget }) => {
    // Constant import adapter: the function body never interpolates user data.
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const auth = await importModule("/src/stores/authStore.ts") as {
      useAuthStore: { getState: () => { setLoggedIn: (token: string, user: string, expiresAt: string) => void } };
    };
    const mode = await importModule("/src/stores/modeStore.ts") as {
      useModeStore: { getState: () => { setMode: (mode: "live") => void } };
    };
    const brokers = await importModule("/src/stores/brokerStore.ts") as {
      useBrokerStore: { getState: () => { setActiveAccount: (selector: string) => void } };
    };
    auth.useAuthStore.getState().setLoggedIn(token, "synthetic-order-flow-operator", "");
    mode.useModeStore.getState().setMode("live");
    // Selector is an explicit operator choice, not connected-state injection.
    // The existing poll must establish the synthetic session from its API body.
    brokers.useBrokerStore.getState().setActiveAccount(`native:dhan:${account}`);
    await Promise.all([
      importModule("/src/routes/TerminalRoute.tsx"),
      importModule(widget === "foreverorders"
        ? "/src/widgets/orders/ForeverOrdersWidget.tsx"
        : "/src/widgets/trading/Positions/PositionsWidget.tsx"),
    ]);
    window.history.pushState(null, "", "/trade");
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, { token: LIVE_TOKEN, account: ACCOUNT_A, widget: component });
  await expect(page).toHaveURL(/\/trade$/);
  await tickUntil(page, page.getByRole("button", {
    name: component === "foreverorders" ? "Refresh forever orders" : "Table", exact: true,
  }).first());
}

export async function tickUntil(page: Page, locator: Locator): Promise<void> {
  // Advance scheduled React/query notifications, not poll intervals. This stays
  // below the positions stale window and the earliest recurring account poll.
  let advanced = 0;
  await expect.poll(async () => {
    if (advanced < 2_000) {
      await page.clock.runFor(25);
      advanced += 25;
    }
    return locator.isVisible();
  }, { timeout: 15_000, intervals: [50] }).toBe(true);
}

export async function selectAccount(page: Page, account: string): Promise<void> {
  await page.evaluate(async (accountId) => {
    // Constant import adapter: the function body never interpolates user data.
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const module = await importModule("/src/stores/brokerStore.ts") as {
      useBrokerStore: { getState: () => { setActiveAccount: (id: string) => void } };
    };
    module.useBrokerStore.getState().setActiveAccount(`native:dhan:${accountId}`);
  }, account);
  await page.clock.runFor(50);
}

export async function notifications(page: Page): Promise<unknown[]> {
  return page.evaluate(() => (window as Window & { __presentationNotifications?: unknown[] }).__presentationNotifications ?? []);
}

export async function captureEvidence(page: Page, info: TestInfo, name: string): Promise<void> {
  const screenshot = info.outputPath(`${name}.png`);
  await page.screenshot({ path: screenshot, animations: "disabled" });
  await info.attach(name, { path: screenshot, contentType: "image/png" });
  const dom = info.outputPath(`${name}.html`);
  await fs.writeFile(dom, await page.content());
  await info.attach(`${name}-dom`, { path: dom, contentType: "text/html" });
  const accessibility = info.outputPath(`${name}.aria.yml`);
  await fs.writeFile(accessibility, await page.locator("body").ariaSnapshot());
  await info.attach(`${name}-accessibility`, { path: accessibility, contentType: "text/yaml" });
}

export async function captureNarrow(page: Page, info: TestInfo, name: string, phone = false): Promise<void> {
  // Below 768px the real Trade route deliberately replaces the saved workspace
  // with its five-panel compact surface (which has Positions but no GTT). Do
  // not bypass that policy; GTT stays mounted at the 800px narrow desk width.
  await page.setViewportSize({ width: phone ? 390 : 800, height: 844 });
  await page.clock.runFor(50);
  const continueButton = page.getByRole("button", { name: "Continue anyway", exact: true });
  if (await continueButton.isVisible()) await continueButton.click();
  await page.clock.runFor(50);
  await captureEvidence(page, info, name);
}

interface PresentationEvidence {
  assertWrites: (expected: Array<{ method: string; path: string; body: unknown }>) => void;
}

export const test = registryTest.extend<{ presentationEvidence: PresentationEvidence }>({
  presentationEvidence: [async ({ page, syntheticApi }, use, info) => {
    const requests: Array<{ method: string; path: string; body: unknown; headers: Record<string, string | null> }> = [];
    const responses: Array<{ method: string; path: string; status: number; body?: string; bodyReadError?: string }> = [];
    const bodyReads: Promise<void>[] = [];
    const consoleMessages: Array<{ type: string; text: string; url: string }> = [];
    const requestFailures: Array<{ method: string; path: string; error: string | null }> = [];
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (!url.pathname.startsWith("/ft-api") && !url.pathname.startsWith("/api")) return;
      let body: unknown = request.postData();
      if (body !== null) {
        try { body = request.postDataJSON() as unknown; } catch { /* Preserve raw malformed request evidence. */ }
      }
      requests.push({
        method: request.method(), path: `${url.pathname}${url.search}`, body,
        headers: Object.fromEntries(["authorization", "x-flinttrade-mode", "content-type", "x-api-key"].map(
          (header) => [header, request.headers()[header] ?? null],
        )),
      });
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.pathname.startsWith("/ft-api") || url.pathname.startsWith("/api")) {
        const entry: (typeof responses)[number] = {
          method: response.request().method(), path: `${url.pathname}${url.search}`, status: response.status(),
        };
        responses.push(entry);
        bodyReads.push(response.text().then(
          (body) => { entry.body = body; },
          (error: unknown) => { entry.bodyReadError = error instanceof Error ? error.message : String(error); },
        ));
      }
    });
    page.on("requestfailed", (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/ft-api") || url.pathname.startsWith("/api")) {
        requestFailures.push({ method: request.method(), path: `${url.pathname}${url.search}`, error: request.failure()?.errorText ?? null });
      }
    });
    page.on("console", (message) => {
      consoleMessages.push({ type: message.type(), text: message.text(), url: message.location().url });
    });
    info.annotations.push({ type: "boundary", description: "Synthetic API presentation; real stores/hooks/readiness guards. Not Python routing, native availability, funded acceptance or Stage D." });
    try {
      await use({ assertWrites: (expected) => {
        expect(requests.filter((request) => request.method !== "GET" && request.method !== "HEAD").map(
          ({ method, path, body }) => ({ method, path, body }),
        )).toEqual(expected);
      } });
    } finally {
      if (!page.isClosed()) {
        await Promise.all(bodyReads);
        const ledger = info.outputPath("presentation-ledger.json");
        await fs.writeFile(ledger, JSON.stringify({
          boundary: "synthetic presentation only", requests, responses, requestFailures, console: consoleMessages,
          notifications: await notifications(page),
        }, null, 2));
        await info.attach("presentation-ledger", { path: ledger, contentType: "application/json" });
        await captureEvidence(page, info, "final-render");
      }
      // The installed registry additionally asserts page errors, unhandled
      // rejections, exact benign-console allowances, and teardown requests.
      syntheticApi.assertSatisfied();
      expect(consoleMessages.filter((message) => message.type === "warning")).toEqual([]);
    }
  }, { auto: true }],
});

export { expect };
