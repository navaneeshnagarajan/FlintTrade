import type { Locator, Page } from "@playwright/test";
import fs from "node:fs/promises";
import { expect, type SyntheticFixtureRegistry, type SyntheticResponse } from "./fixture-registry";
import { ACCOUNT_A, ACCOUNT_B, FIXED_TIME, LIVE_TOKEN, nativePath, registerRead, test as presentationTest } from "./order-flow-fixtures";

export { ACCOUNT_A, ACCOUNT_B, nativePath, expect };
export const DISCOVERY = "/ft-api/api/v1/native/accounts";
export const JOURNAL = "/ft-api/api/v1/trades/journal?start_date=2026-08-05&end_date=2026-08-11&limit=1000";
export const ok = (data: unknown): SyntheticResponse => ({ json: { status: "success", data } });
export const funds = (value: number) => ok({ available_balance: value, used_margin: 0, total_balance: value });
export const position = (symbol: string, pnl: number, quantity = 10) => ({ symbol, exchange: "NSE", product: "CNC", quantity, averagePrice: 100, ltp: 100 + pnl / quantity, pnl, pnlPercent: pnl / quantity });
export const fills = (symbol = "SYNTHETIC-CLOSED", restored = false) => [
  { tradeId: `${symbol}-BUY`, orderId: `${symbol}-BUY`, symbol, exchange: "NSE", product: "CNC", action: "BUY", quantity: 10, price: 100, timestamp: "2026-08-11T09:15:00+05:30", strategy: restored ? "Restored from backup" : "Synthetic" },
  { tradeId: `${symbol}-SELL`, orderId: `${symbol}-SELL`, symbol, exchange: "NSE", product: "CNC", action: "SELL", quantity: 10, price: 130, timestamp: "2026-08-11T09:25:00+05:30", strategy: restored ? "Restored from backup" : "Synthetic" },
];

export function hold() {
  let release!: (value: SyntheticResponse) => void;
  let entered!: () => void;
  const started = new Promise<void>((resolve) => { entered = resolve; });
  const response = new Promise<SyntheticResponse>((resolve) => { release = resolve; });
  return { started, release, handler: () => { entered(); return response; } };
}

export function discovery(api: SyntheticFixtureRegistry, completedReads: number, disconnectedB = false, disconnectedA = false, phase: "startup" | "required" = "startup") {
  registerRead(api, DISCOVERY, { json: { accounts: [ACCOUNT_A, ACCOUNT_B].map((account, index) => ({
    adapter_id: "dhan", account_id: account, label: account, is_primary: index === 0,
    has_session: !(disconnectedB && index === 1) && !(disconnectedA && index === 0), read_only: false, needs_relogin: false, login_retryable: false,
  })) } }, completedReads, phase);
}

export function book(api: SyntheticFixtureRegistry, kind: string, response: SyntheticResponse | (() => Promise<SyntheticResponse>), account = ACCOUNT_A, calls = 1) {
  // Session's newly mounted StrictMode observers may abort one startup GET.
  // Still require exactly the completed bodies, never a loose total range.
  registerRead(api, nativePath(kind, account), response, calls, kind === "trades" || kind === "orders" ? "startup" : undefined);
}
export function aggregateBooks(api: SyntheticFixtureRegistry, value = 1200, pnl = 75, quantity = 10) {
  book(api, "funds", funds(value));
  book(api, "positions", ok(pnl === 0 ? [] : [position("SYNTHETIC-ALPHA", pnl, quantity)]));
}
export const SAFETY = "/ft-api/api/v1/safety/config";
export function safety(active = false, halted = false) {
  return ok({
    l1_order: { price_deviation_pct: 5, check_market_hours: true, qty_limits: { NSE: 1800 } },
    l2_position: { max_positions: 10, max_margin_pct: 80 },
    l3_portfolio: { max_net_delta: 1000, max_net_vega: 500 },
    l4_pnl: { pause_pct: 2, kill_pct: 5, is_paused: halted, is_killed: halted },
    l5_kill: { is_active: active, reason: active ? "Synthetic independent halt" : "", flatten_complete: false, emergency_result: null },
  });
}
export function riskReads(api: SyntheticFixtureRegistry, response = safety()) {
  registerRead(api, SAFETY, response);
  book(api, "orders", ok([]));
}
export function recoveryReads(api: SyntheticFixtureRegistry) {
  registerRead(api, `${nativePath("holidays")}?year=2026`, ok([]));
}

export async function mountUnavailableRisk(page: Page, api: SyntheticFixtureRegistry) {
  const positions = hold();
  book(api, "funds", funds(0)); book(api, "positions", positions.handler);
  try {
    await mount(page, "wired-risk");
    // Let the real lazy PositionsWidget subscribe before resolving the failed
    // book, avoiding a timing-dependent retry-on-mount of an already failed read.
    await pump(page, () => page.getByRole("region", { name: "Positions book" }).isVisible());
    await positions.started; positions.release(ok(null));
    await pump(page, async () => (await snapshot(page))["positionsStatus"] === "unavailable");
  } finally { positions.release(ok(null)); }
}
export async function browserNetwork(page: Page) {
  return page.evaluate(() => {
    const observed = window as Window & { __foundationNetworkObservation?: () => { navigatorOnline: boolean; queryOnline: boolean } };
    if (!observed.__foundationNetworkObservation) throw new Error("Foundation observation is not mounted");
    return observed.__foundationNetworkObservation();
  });
}

export async function deliverOfflineEvent(page: Page) {
  // Chromium in a loopback-only namespace starts navigator.onLine=false.
  // context.setOffline(true) therefore cannot produce an online->offline edge.
  // Deliver the declared synthetic browser event to the real TanStack listener;
  // never call onlineManager.setOnline or replace a derived availability field.
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await page.clock.runFor(50);
  expect(await browserNetwork(page)).toEqual({ navigatorOnline: false, queryOnline: false });
}

export function sessionBooks(api: SyntheticFixtureRegistry, trades: unknown[] = [], orders: unknown[] = [], mode: "live" | "practice" = "live") {
  if (mode === "live") {
    aggregateBooks(api);
    book(api, "trades", ok(trades));
    book(api, "orders", ok(orders));
  } else {
    for (const [kind, data] of Object.entries({ funds: { funds: { available_balance: 0, used_margin: 0, current_balance: 0 } }, positions: { positions: [] }, trades: { trades }, orders: { orders } })) {
      registerRead(api, `/ft-api/v1/sandbox/${kind}`, ok(data), 1, "startup");
    }
  }
  journal(api, mode);
}
export function journal(api: SyntheticFixtureRegistry, mode: "live" | "practice" = "live") {
  // The production Log child shares the parent's key and starts the ranged
  // 200-row fetch; Practice disables that child so the parent owns 1000.
  registerRead(api, mode === "live" ? JOURNAL.replace("limit=1000", "limit=200") : JOURNAL, ok({ trades: [], total: 0 }), 1);
  if (mode === "live") registerRead(api, "/ft-api/api/v1/journal/screenshots", ok([]));
}

export async function pump(page: Page, predicate: () => Promise<boolean>) {
  let advanced = 0;
  await expect.poll(async () => {
    if (advanced < 3000) { await page.clock.runFor(25); advanced += 25; }
    return predicate();
  }, { timeout: 10000, intervals: [25] }).toBe(true);
}
export async function mount(page: Page, view: "aggregate" | "session" | "wired-risk" | "dormant-recovery", mode: "live" | "practice" = "live", beforeSession?: () => Promise<void>) {
  await page.clock.install({ time: FIXED_TIME });
  await page.clock.pauseAt(FIXED_TIME);
  await page.addInitScript(() => {
    const observed = window as Window & { __presentationNotifications?: unknown[] };
    observed.__presentationNotifications = [];
    window.addEventListener("flinttrade:notify", (event) => {
      observed.__presentationNotifications?.push((event as CustomEvent<unknown>).detail);
    });
  });
  await page.goto(`/e2e/foundation-truth.fixture.html?view=${view}`);
  await expect(page.getByText("Awaiting synthetic authentication")).toBeVisible();
  await page.evaluate(async ({ token, selectedMode, account, selectedView }) => {
    // Constant body, no interpolation; module paths below are fixed literals.
    const load = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const auth = await load("/src/stores/authStore.ts") as { useAuthStore: { getState: () => { setLoggedIn: (token: string, user: string, expiry: string) => void } } };
    const modes = await load("/src/stores/modeStore.ts") as { useModeStore: { getState: () => { setMode: (mode: "live" | "practice") => void } } };
    const brokers = await load("/src/stores/brokerStore.ts") as { useBrokerStore: { getState: () => { setActiveAccount: (account: string) => void } } };
    if (selectedView === "wired-risk") {
      // Use the normal saved-layout/public settings seams to bound unrelated
      // widgets, never a fake TerminalRoute or a readiness/state override.
      const layout = await load("/src/stores/layoutStore.ts") as { useLayoutStore: { getState: () => { activeTabId: string; saveTabLayout: (id: string, json: Record<string, unknown>) => void } } };
      const adapter = await load("/src/layout/flexLayoutAdapter.tsx") as { emptyWorkspaceJson: () => Record<string, unknown> };
      const settings = await load("/src/stores/settingsStore.ts") as { useSettingsStore: { getState: () => { setExperience: (value: "pro") => void } } };
      layout.useLayoutStore.getState().saveTabLayout(layout.useLayoutStore.getState().activeTabId, adapter.emptyWorkspaceJson());
      settings.useSettingsStore.getState().setExperience("pro");
    }
    if (selectedView === "dormant-recovery") localStorage.setItem("flinttrade:sessionActive", "true");
    modes.useModeStore.getState().setMode(selectedMode);
    brokers.useBrokerStore.getState().setActiveAccount(`native:dhan:${account}`);
    auth.useAuthStore.getState().setLoggedIn(token, "synthetic-foundation-operator", "");
  }, { token: LIVE_TOKEN, selectedMode: mode, account: ACCOUNT_A, selectedView: view });
  await pump(page, () => page.getByRole("heading", { name: /Foundation truth/ }).isVisible());
  if (view === "session") {
    await beforeSession?.();
    await page.getByRole("tab", { name: "Session", exact: true }).click();
    await pump(page, () => page.getByRole("tabpanel", { name: "Session", exact: true }).isVisible());
  }
}
export async function choose(page: Page, account: string) {
  await page.getByRole("combobox", { name: "Synthetic account selection" }).selectOption(`native:dhan:${account}`);
  await page.clock.runFor(50);
}
export async function snapshot(page: Page): Promise<Record<string, unknown>> {
  return page.evaluate(async () => {
    // Constant body, no interpolation; read-only production store observation.
    const load = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const store = await load("/src/stores/tradingStore.ts") as { useTradingStore: { getState: () => Record<string, unknown> } };
    return Object.fromEntries(Object.entries(store.useTradingStore.getState()).filter(([, value]) => typeof value !== "function"));
  });
}
export function counts(api: SyntheticFixtureRegistry, paths: string[]) { return Object.fromEntries(paths.map((path) => [path, api.callCount("GET", path)])); }
export function session(page: Page) { return page.getByRole("tabpanel", { name: "Session", exact: true }); }

export async function literalPaint(locator: Locator) {
  return locator.evaluate((element) => {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const glyphs = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      for (let index = 0; index < (node.textContent?.length ?? 0); index++) {
        const text = node.textContent?.[index] ?? "";
        if (!text.trim()) continue;
        const range = document.createRange(); range.setStart(node, index); range.setEnd(node, index + 1);
        const box = range.getBoundingClientRect();
        const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
        glyphs.push({ text, left: box.left, right: box.right, top: box.top, bottom: box.bottom,
          inViewport: box.top >= 0 && box.bottom <= innerHeight && box.left >= 0 && box.right <= innerWidth,
          painted: hit !== null && element.contains(hit), hit: hit?.tagName, hitText: hit?.textContent?.slice(0, 120) });
      }
    }
    return { text: element.textContent, glyphs };
  });
}

export async function queryObservations(page: Page) {
  return page.evaluate(async () => {
    // Constant body with a literal module path; observe, never replace queries.
    const load = new Function("path", "return import(path)") as (path: string) => Promise<Record<string, unknown>>;
    const module = await load("/src/providers/QueryProvider.tsx") as {
      queryClient: { getQueryCache: () => { getAll: () => Array<{ queryKey: unknown[]; state: { status: string; fetchStatus: string; fetchFailureCount: number; data?: unknown; error?: unknown } }> } };
    };
    return module.queryClient.getQueryCache().getAll().map(({ queryKey, state }) => ({
      queryKey, ...state, error: state.error instanceof Error ? state.error.message : state.error,
    }));
  });
}

export async function finishTradeRetries(page: Page) {
  await finishRetries(page, "tradebook");
}

export async function finishRetries(page: Page, key: string) {
  // Wait for the real QueryCache failure before advancing each production retry.
  // A single large clock jump can precede body decoding and strand the final
  // React notification at the pump boundary even after all HTTP bodies finish.
  for (const [failures, delay] of [[1, 1000], [2, 2000]]) {
    await pump(page, async () => (await queryObservations(page)).some((query) => query.queryKey[0] === key && query.fetchFailureCount === failures));
    await page.clock.runFor(delay);
  }
  await pump(page, async () => (await queryObservations(page)).some((query) => query.queryKey[0] === key && query.status === "error" && query.fetchStatus === "idle"));
}

export const test = presentationTest.extend<{ foundationEvidence: void; foundationWrites: Array<{ method: string; path: string; body: unknown }> }>({
  foundationWrites: [[], { option: true }],
  foundationEvidence: [async ({ page, syntheticApi }, use, info) => {
    const reads = new Set<string>();
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (request.method() === "GET" && url.pathname.startsWith("/ft-api/")) reads.add(`${url.pathname}${url.search}`);
    });
    try { await use(); } finally {
      if (!page.isClosed()) {
        const path = info.outputPath("foundation-state.json");
        await fs.writeFile(path, JSON.stringify({ aggregate: await snapshot(page), queries: await queryObservations(page) }, null, 2));
        await info.attach("foundation-state", { path, contentType: "application/json" });
        await expect.poll(() => [...reads].every((read) => syntheticApi.readCounts(read).pending === 0)).toBe(true);
        const countsPath = info.outputPath("foundation-read-counts.json");
        await fs.writeFile(countsPath, JSON.stringify(Object.fromEntries([...reads].sort().map((read) => [read, syntheticApi.readCounts(read)])), null, 2));
        await info.attach("foundation-read-counts", { path: countsPath, contentType: "application/json" });
      }
    }
  }, { auto: true }],
});
