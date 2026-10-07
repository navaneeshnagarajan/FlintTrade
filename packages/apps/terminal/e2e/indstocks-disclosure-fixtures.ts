import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page, TestInfo } from "@playwright/test";
import type { SyntheticFixtureRegistry } from "./fixture-registry";
import {
  FIXED_TIME, LIVE_TOKEN, expect, nativePath, registerDeskReads, registerRead, tickUntil,
} from "./order-flow-fixtures";

export const IND_BROKER = "indmoney";
export const IND_A = "IND-OFFLINE";
export const IND_B = "IND-OFFLINE-B";
export const IND_WRITE = "/ft-api/api/v1/orders/indmoney/place";
export const MARKET_NOTICE = "INDstocks documents MARKET requests converting to LIMIT orders at the broker’s live price. The effective limit price is unknown until the broker reports it. Execution is not guaranteed.";
export const GTT_NOTICE = "GTT creation is unavailable in this Order Pad. INDstocks currently ignores trailing-stop fields; active trailing requests are refused, not treated as protection.";
export const ACTIVATION_REFUSAL = "INDstocks activation is unavailable. No order was sent.";
// Matches adapter.py's held catalogue blockers. These HTTP fixtures never grant
// native activation, and a successful ACK below proves presentation only.
export const CONNECT_BLOCKERS = [
  "Authoritative smart-parent cancellation discriminator",
  "Broker-native atomic reduce-only close primitive",
  "Live order-safety proof",
];
export const IND_BODY = {
  symbol: "RELIANCE", exchange: "NSE", action: "BUY", product: "MIS", orderType: "MARKET",
  quantity: 1, price: 0, triggerPrice: 0, strategy: "FlintOrderPad", rationale: "",
  order_type: "MARKET", trigger_price: 0, broker: IND_BROKER, account_id: IND_A,
};

export function indPath(kind: string, account = IND_A): string {
  return nativePath(kind, account, IND_BROKER);
}

export function acknowledgement(id = "SYNTHETIC-IND-ACK") {
  // Normal gated HTTP shape pinned by test_indmoney_http_evidence.py. The
  // first-ID data stays scalar; evidence is additive at the response root.
  return { status: "success", orderid: id, data: id,
    order_ids: [id], child_order_id: null,
    execution_effects: { requested_type: "MARKET", effective_type: "LIMIT", effective_limit_price: null, trailing_active: false, limitations: ["MARKET_TO_LIMIT"] },
    broker_response: { order_id: id, order_status: "INITIATED", extra_info: { observations: ["accepted", null] } },
  };
}

export function registerIndstocksReads(
  registry: SyntheticFixtureRegistry,
  options: { accountSwitch?: boolean; hasSession?: boolean; readOnly?: boolean; openPosition?: boolean; mode?: "practice" | "explore"; marketScopeVisits?: number } = {},
): void {
  registerDeskReads(registry, options.accountSwitch, {
    broker: IND_BROKER, accountIds: [IND_A, IND_B], hasSession: options.hasSession, readOnly: options.readOnly,
    // Explore deliberately never hydrates protected account collections. Keep
    // this endpoint unregistered rather than expecting a read the source forbids.
    nativeAccounts: options.mode !== "explore",
    marketScopeVisits: options.marketScopeVisits,
  });
  const optional = { minimum: 0, maximum: 2 };
  for (const account of [IND_A, IND_B]) {
    const liveBookMinimum = account === IND_A && options.hasSession !== false && !options.mode ? 1 : 0;
    registerRead(registry, indPath("positions", account), { json: { status: "success", data: options.openPosition ? [{
      symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 100, ltp: 101, pnl: 10, pnlPercent: 1,
    }] : [] } }, { minimum: liveBookMinimum, maximum: 4 });
    registerRead(registry, indPath("orders", account), { json: { status: "success", data: [] } }, { minimum: liveBookMinimum, maximum: 5 });
    registerRead(registry, indPath("funds", account), { json: { status: "success", data: { available_balance: 100_000, used_margin: 0, total_balance: 100_000 } } }, optional);
    registerRead(registry, `${indPath("search", account)}?query=RELIANCE&exchange=NSE`, { json: { status: "success", data: [{ symbol: "RELIANCE", exchange: "NSE", lotsize: 1, tick_size: 0.05 }] } }, optional);
    registerRead(registry, `${indPath("margin", account)}?symbol=RELIANCE&exchange=NSE&qty=1&product=MIS&action=BUY&pricetype=MARKET`, { json: { status: "success", data: { total_margin: 100, span_margin: 100, exposure_margin: 0 } } }, optional);
    registerRead(registry, `${indPath("margin", account)}?symbol=RELIANCE&exchange=NSE&qty=1&product=MIS&action=BUY&pricetype=LIMIT&price=73.55`, { json: { status: "success", data: { total_margin: 100, span_margin: 100, exposure_margin: 0 } } }, optional);
  }
  registerRead(registry, "/ft-api/api/v1/broker/capabilities?broker=indmoney", { json: { status: "success", data: {
    broker: IND_BROKER, connectable: false, native_connect_blockers: CONNECT_BLOCKERS,
    capabilities: { broker_name: "INDstocks", broker_type: "equity", supported_exchanges: ["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"] },
  } } }, optional);
  registerRead(registry, "/ft-api/api/v1/broker/capabilities", { json: { status: "success", data: {
    capabilities: { broker_name: "Unconfigured", broker_type: "equity", supported_exchanges: ["NSE"] },
  } } }, optional);
  registerRead(registry, "/ft-api/v1/sandbox/positions", { json: { status: "success", data: { positions: [] } } }, { minimum: 0, maximum: 4 });
  registerRead(registry, "/ft-api/v1/sandbox/orders", { json: { status: "success", data: { orders: [] } } }, { minimum: 0, maximum: 5 });
  registerRead(registry, "/ft-api/v1/sandbox/funds", { json: { status: "success", data: { funds: { starting_capital: 100_000, available_balance: 100_000, used_margin: 0, realized_pnl: 0, current_balance: 100_000 } } } }, optional);
}

export function orderPad(page: Page): Locator {
  return page.locator('[data-tour-target="order-pad"]').first();
}

export async function mountIndstocksPad(
  page: Page, options: { mode?: "live" | "practice" | "explore"; narrowPanel?: boolean } = {},
): Promise<void> {
  await page.clock.install({ time: FIXED_TIME });
  await page.clock.pauseAt(FIXED_TIME);
  await page.addInitScript(({ narrow }) => {
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
    localStorage.setItem("flinttrade:layouts", JSON.stringify({ state: {
      tabs: [{ id: "indstocks-disclosure", name: "Synthetic disclosure only", serializedLayout: {
        global: { tabEnableRename: false, tabSetEnableSingleTabStretch: true, tabSetMinWidth: 100, tabSetMinHeight: 80 },
        borders: [], layout: { type: "row", weight: 100, children: [{
          type: "tabset", weight: narrow ? 45 : 100, children: [{
            type: "tab", id: "indstocks-order-pad", component: "orderpad", name: "Order Pad", config: { symbol: "RELIANCE", exchange: "NSE" },
          }],
        }, ...(narrow ? [{ type: "tabset", weight: 55, children: [{ type: "tab", id: "indstocks-sibling-positions", component: "positions", name: "Positions" }] }] : [])] },
      } }], activeTabId: "indstocks-disclosure",
    }, version: 0 }));
    const observed = window as Window & { __presentationNotifications?: unknown[] };
    observed.__presentationNotifications = [];
    window.addEventListener("flinttrade:notify", (event) => observed.__presentationNotifications?.push((event as CustomEvent<unknown>).detail));
  }, { narrow: options.narrowPanel ?? false });
  await page.goto("/welcome");
  await page.evaluate(async ({ token, account, mode }) => {
    // Fixed import adapter: no data is interpolated into the function body.
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const auth = await importModule("/src/stores/authStore.ts") as { useAuthStore: { getState: () => { setLoggedIn: (token: string, user: string, expiry: string) => void } } };
    const modes = await importModule("/src/stores/modeStore.ts") as { useModeStore: { getState: () => { setMode: (mode: "live" | "practice" | "explore") => void } } };
    const brokers = await importModule("/src/stores/brokerStore.ts") as { useBrokerStore: { getState: () => { setActiveAccount: (selector: string) => void } } };
    auth.useAuthStore.getState().setLoggedIn(token, "synthetic-order-flow-operator", "");
    modes.useModeStore.getState().setMode(mode);
    brokers.useBrokerStore.getState().setActiveAccount(`native:indmoney:${account}`);
    await Promise.all([importModule("/src/routes/TerminalRoute.tsx"), importModule("/src/widgets/trading/OrderPad/OrderPadWidget.tsx")]);
    window.history.pushState(null, "", "/trade");
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, { token: LIVE_TOKEN, account: IND_A, mode: options.mode ?? "live" });
  await expect(page).toHaveURL(/\/trade$/);
  await tickUntil(page, orderPad(page).getByRole("radio", { name: "MARKET", exact: true }));
  // A prefilled saved widget uses its real FlexLayout config, not a private
  // form mutation. Pin the rendered instrument before testing native bodies.
  await expect(orderPad(page).getByRole("textbox", { name: "Symbol", exact: true })).toHaveValue("RELIANCE");
}

export async function selectIndstocksScope(page: Page, selection: string | null, mode?: "practice" | "live"): Promise<void> {
  await page.evaluate(async ({ selector, nextMode }) => {
    // Fixed import adapter: no data is interpolated into the function body.
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const brokers = await importModule("/src/stores/brokerStore.ts") as { useBrokerStore: { getState: () => { setActiveAccount: (selector: string | null) => void } } };
    brokers.useBrokerStore.getState().setActiveAccount(selector);
    if (nextMode) {
      const modes = await importModule("/src/stores/modeStore.ts") as { useModeStore: { getState: () => { setMode: (mode: "practice" | "live") => void } } };
      modes.useModeStore.getState().setMode(nextMode);
    }
  }, { selector: selection, nextMode: mode });
  await page.clock.runFor(50);
}

/** Observe the real hydrated store and production authority/readiness selectors. */
export async function accountSnapshot(page: Page) {
  return page.evaluate(async () => {
    // Fixed import adapter: no data is interpolated into the function body.
    const importModule = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const brokers = await importModule("/src/stores/brokerStore.ts") as { useBrokerStore: { getState: () => { accounts: Array<{ source: string; broker: string; account_id: string; status: string; read_only?: boolean }>; activeAccountId: string | null } } };
    const modes = await importModule("/src/stores/modeStore.ts") as { useModeStore: { getState: () => { mode: "live" | "practice" | "explore" } } };
    const connection = await importModule("/src/stores/connectionStore.ts") as { useConnectionStore: { getState: () => { apiKey: string; status: string } } };
    const scopes = await importModule("/src/hooks/useDataScope.ts") as { resolveAccountAuthorityIdentity: (input: unknown) => { scopeKey: string; mode: string; accountId: string; brokerType: string } };
    const reads = await importModule("/src/hooks/useAccountReadsEnabled.ts") as { accountIdentityReadsEnabled: (identity: unknown, status: unknown, accounts: unknown) => boolean };
    const targets = await importModule("/src/services/brokerTargets.ts") as { pickNativeWriteTarget: (mode: "live" | "practice" | "explore", apiKey: string) => { broker: string; accountId: string } | undefined };
    const { accounts, activeAccountId } = brokers.useBrokerStore.getState();
    const { mode } = modes.useModeStore.getState();
    const { status, apiKey } = connection.useConnectionStore.getState();
    const identity = scopes.resolveAccountAuthorityIdentity({ accounts, activeAccountId, mode });
    return {
      mode, activeAccountId, scopeKey: identity.scopeKey,
      readsEnabled: reads.accountIdentityReadsEnabled(identity, status, accounts),
      writeTarget: targets.pickNativeWriteTarget(mode, apiKey) ?? null,
      accounts: accounts.map(({ source, broker, account_id, status, read_only }) => ({ source, broker, account_id, status, read_only: read_only ?? false })),
    };
  });
}

/** Automated WCAG checks scoped to the new disclosures; no rule suppressions. */
export async function assertDisclosureA11y(page: Page, info: TestInfo, name: string, selectors: string[]): Promise<void> {
  for (const selector of selectors) await expect(page.locator(selector).first()).toBeVisible();
  // The repository's existing Axe integration requires live timers. Resume
  // only for this analysis, then freeze again below the recurring poll window.
  await page.clock.resume();
  let analysis: Awaited<ReturnType<AxeBuilder["analyze"]>>;
  try {
    let builder = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]);
    for (const selector of selectors) builder = builder.include(selector);
    analysis = await builder.analyze();
  } finally {
    const now = await page.evaluate(() => Date.now());
    await page.clock.pauseAt(now + 25);
  }
  // Preserve raw passes/incomplete findings alongside violations: zero detected
  // violations is not a claim of exhaustive accessibility conformance.
  await info.attach(`${name}-axe`, { body: JSON.stringify({ selectors, analysis }, null, 2), contentType: "application/json" });
  expect(analysis.violations).toEqual([]);
}
