import { writeFile } from "node:fs/promises";
import type { Locator, Page, Request, TestInfo } from "@playwright/test";

import { expect, test, type SyntheticFixtureRegistry } from "./fixture-registry";
import { registerExampleDeskReads, registerPracticeOrderPadReads } from "./visual/desk-mocks";

// Synthetic authority only. The fail-closed registry intercepts every API call;
// this journey never starts a backend, broker connection or model request.
const TOKEN = [
  Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
  Buffer.from(JSON.stringify({
    sub: "synthetic-agent-operator", mode: "practice", exp: 4_102_444_800,
  })).toString("base64url"),
  "synthetic-e2e-signature",
].join(".");
const AGENT = "/ft-api/api/v1/ai/agent";
const RUN_ID = "synthetic-practice-run";
const EVENTS = `${AGENT}/practice/runs/${RUN_ID}/events?after=0&limit=100`;
const RESOLVE = `${AGENT}/practice/runs/${RUN_ID}/resolve`;
const READ_CALLS = { minimum: 1, maximum: 32 } as const;
const CREATED_AT = "2026-08-11T03:00:00Z";

// Keep the state badge and its action in one real desktop viewport. Element
// screenshots of the animated, internally scrolled overlay previously produced
// a 512x351 crop, including one capture of the Chat underneath it.
test.use({ viewport: { width: 1440, height: 1080 } });

interface AgentState {
  snapshot: Record<string, unknown>;
  runs: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
}

function idleState(): AgentState {
  return {
    snapshot: {
      enabled: true, running: false, mode: "practice", agent_status: "idle",
      actor_id: "autonomous-trader", started_at: "", params: {},
      active_positions: {}, position_details: {},
    },
    runs: [],
    events: [],
  };
}

function setRunState(state: AgentState, status: string, openPosition = false): void {
  const active = ["waiting", "running", "stopping"].includes(status);
  const params = state.snapshot.params as Record<string, unknown>;
  state.snapshot = {
    ...state.snapshot, mode: "practice", agent_status: status, running: active,
    run_id: RUN_ID, started_at: CREATED_AT, cycle_count: status === "waiting" ? 0 : 1,
    active_positions: openPosition ? { RELIANCE: 2 } : {},
    position_details: openPosition ? {
      RELIANCE: { action: "BUY", quantity: 2, entry_price: 100, stop_loss: 98, take_profit: 104 },
    } : {},
    model_usage: {
      model_call_limit: 12, model_output_limit: 256, model_calls_used: active ? 1 : 2,
      model_calls_remaining: active ? 11 : 10, status: "available",
    },
  };
  state.runs = [{
    run_id: RUN_ID, mode: "practice", status, config: params, snapshot: state.snapshot,
    error: null, created_at: CREATED_AT, updated_at: `2026-08-11T03:00:${String(state.events.length + 1).padStart(2, "0")}Z`,
  }];
  state.events = [...state.events, {
    seq: state.events.length + 1, run_id: RUN_ID, kind: status,
    data: { simulated: true }, created_at: CREATED_AT,
  }];
}

function expectPracticeAuthority(request: Request): void {
  expect(request.headers()["authorization"]).toBe(`Bearer ${TOKEN}`);
  expect(request.headers()["x-api-key"]).toBeUndefined();
}

function registerAgentReads(registry: SyntheticFixtureRegistry, state: AgentState): void {
  for (const [name, path, read] of [
    ["mode-scoped agent snapshot", `${AGENT}/status`, () => state.snapshot],
    ["durable Practice history", `${AGENT}/practice/runs`, () => state.runs],
    ["bounded Practice evidence", EVENTS, () => state.events],
  ] as const) {
    registry.register({
      name, method: "GET", path,
      // Evidence is absent until a run exists. All other reads must occur.
      expectedCalls: path === EVENTS ? { minimum: 0, maximum: 32 } : READ_CALLS,
      handler: (request) => {
        expectPracticeAuthority(request);
        expect(request.postData()).toBeNull();
        return { json: { status: "success", data: read() } };
      },
    });
  }
}

async function openPracticeAgent(page: Page, registry: SyntheticFixtureRegistry): Promise<Locator> {
  // Freeze dates, not timers: React, animations and network settlement remain
  // real browser behaviour. Only explicit refresh actions advance agent state.
  await page.clock.setFixedTime(new Date(CREATED_AT));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript((token) => {
    sessionStorage.setItem("flinttrade:auth-session", JSON.stringify({
      token, username: "synthetic-agent-operator", expiresAt: "",
    }));
    localStorage.setItem("flinttrade:mode", JSON.stringify({ state: { mode: "practice" }, version: 2 }));
    localStorage.setItem("flinttrade:skill", JSON.stringify({ state: { globalLevel: "advanced" }, version: 2 }));
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  }, TOKEN);
  registerExampleDeskReads(registry);
  registerPracticeOrderPadReads(registry);
  registry.register({
    name: "read-only AI signal stream", method: "GET", path: "/ft-api/api/v1/signals/stream",
    expectedCalls: READ_CALLS,
    handler: (request) => {
      expectPracticeAuthority(request);
      expect(request.postData()).toBeNull();
      return { contentType: "text/event-stream", body: ": synthetic heartbeat\n\n" };
    },
  });
  await page.goto("/ai");
  await expect(page).toHaveURL("http://localhost:5173/ai");
  await expect(page).toHaveTitle(/FlintTrade/);
  await expect(page.getByRole("heading", { level: 1, name: "AI Centre" })).toBeVisible();
  expect(registry.callCount("GET", `${AGENT}/status`)).toBe(0);
  await page.getByRole("button", { name: "Agent", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "Autonomous Agent" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/Practice · simulated money/)).toBeVisible();
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  return panel;
}

async function refresh(panel: Locator): Promise<void> {
  const button = panel.getByRole("button", { name: "Refresh", exact: true });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(button).toBeEnabled();
}

async function captureAgentEvidence(
  page: Page,
  panel: Locator,
  control: Locator,
  expectedStatus: string,
  testInfo: TestInfo,
  name: string,
): Promise<void> {
  const status = panel.getByRole("status");
  await page.evaluate(() => document.fonts.ready);
  await status.scrollIntoViewIfNeeded();
  await control.scrollIntoViewIfNeeded();
  await expect(status).toHaveText(expectedStatus);
  await expect(status).toBeInViewport({ ratio: 1 });
  await expect(control).toBeInViewport({ ratio: 1 });
  await expect(panel).toHaveCSS("opacity", "1");
  // Visibility assertions alone allow transparent/transformed elements. Wait
  // for the real animation and stable geometry; never force CSS or sleep a
  // guessed duration to make the evidence look settled.
  await expect.poll(() => panel.evaluate(async (element) => {
    const before = element.getBoundingClientRect();
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const after = element.getBoundingClientRect();
    const transform = getComputedStyle(element).transform;
    const atRest = transform === "none" || new DOMMatrixReadOnly(transform).isIdentity;
    return atRest && ["x", "y", "width", "height"].every((key) => {
      const dimension = key as "x" | "y" | "width" | "height";
      return Math.abs(before[dimension] - after[dimension]) < 0.5;
    });
  }), { message: "Agent overlay must finish its animation before evidence capture" }).toBe(true);
  for (const target of [status, control]) {
    await expect.poll(() => target.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const painted = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
      const dialog = element.closest('[role="dialog"][aria-label="Autonomous Agent"]');
      if (painted === null) return false;
      if (element.contains(painted)) return true;
      // Only a disabled pointer-events:none button may yield its hit-test to
      // an ancestor. A sibling in the same dialog must never hide a target.
      const disabled = element instanceof HTMLButtonElement && element.disabled
        && getComputedStyle(element).pointerEvents === "none";
      return disabled && painted.contains(element) && dialog?.contains(painted) === true;
    }), { message: "Agent state and action must own their visible screenshot region" }).toBe(true);
  }
  const geometry = await panel.evaluate((element) => ({
    rect: element.getBoundingClientRect().toJSON(),
    opacity: getComputedStyle(element).opacity,
    transform: getComputedStyle(element).transform,
    viewport: { width: innerWidth, height: innerHeight },
    status: element.querySelector('[role="status"]')?.textContent,
  }));
  const screenshot = testInfo.outputPath(`${name}.png`);
  // Capture the viewport directly so a later element-scroll/clip calculation
  // cannot select the underlying Chat instead of the settled overlay.
  await page.screenshot({ path: screenshot, fullPage: false });
  await expect(status).toHaveText(expectedStatus);
  await expect(status).toBeInViewport({ ratio: 1 });
  await expect(control).toBeInViewport({ ratio: 1 });
  await testInfo.attach(name, { path: screenshot, contentType: "image/png" });
  const geometryPath = testInfo.outputPath(`${name}-geometry.json`);
  await writeFile(geometryPath, `${JSON.stringify(geometry, null, 2)}\n`);
  await testInfo.attach(`${name}-geometry`, {
    path: geometryPath, contentType: "application/json",
  });
}

// Mode isolation is exercised through the same store boundary as the app's
// authenticated mode menu. This is synthetic state injection, not a Live unlock
// or a claim that the browser has authenticated with a real server.
async function setSyntheticMode(page: Page, mode: "explore" | "practice" | "live"): Promise<void> {
  await page.evaluate(async (nextMode) => {
    const importModule = new Function("path", "return import(path)") as (
      path: string,
    ) => Promise<{ useModeStore: { getState: () => { setMode: (mode: typeof nextMode) => void } } }>;
    const { useModeStore } = await importModule("/src/stores/modeStore.ts");
    useModeStore.getState().setMode(nextMode);
  }, mode);
}

test("Practice navigation validates model bounds and submits one explicit start through waiting, running and stopping", async ({ page, syntheticApi }, testInfo) => {
  const state = idleState();
  registerAgentReads(syntheticApi, state);
  syntheticApi.register({
    name: "explicit bounded Practice start", method: "POST", path: `${AGENT}/start`,
    expectedCalls: 1,
    handler: (request) => {
      expectPracticeAuthority(request);
      expect(request.headers()["content-type"]).toBe("application/json");
      const payload = {
        symbols: ["RELIANCE", "ICICIBANK"], exchange: "NSE", max_position_size: 2,
        stop_loss_pct: 1.5, take_profit_pct: 3,
        entry_rationale: "Wait for the opening range; keep simulated risk small.",
        model_call_limit: 12, model_output_limit: 256,
      };
      expect(request.postDataJSON()).toEqual(payload);
      state.snapshot.params = payload;
      setRunState(state, "waiting");
      return { status: 202, json: { status: "success", data: state.snapshot } };
    },
  });
  syntheticApi.register({
    name: "explicit Practice stop and square-off", method: "POST", path: `${AGENT}/stop`,
    expectedCalls: 1,
    handler: (request) => {
      expectPracticeAuthority(request);
      expect(request.postDataJSON()).toEqual({ square_off: true });
      setRunState(state, "stopping", true);
      return { status: 202, json: { status: "success", data: state.snapshot } };
    },
  });
  const panel = await openPracticeAgent(page, syntheticApi);
  const start = panel.getByRole("button", { name: "Start agent" });
  await expect(start).toBeEnabled();
  await expect(panel.getByRole("status")).toHaveText("Idle");
  await panel.getByLabel("Agent symbols").fill(" reliance, icicibank ");
  await panel.getByLabel("Agent exchange").fill(" nse ");
  await panel.getByLabel("Maximum position size in units").fill("2");
  await panel.getByLabel("Stop loss percent").fill("1.5");
  await panel.getByLabel("Take profit percent").fill("3");
  const rationale = panel.getByLabel("Operator entry rationale (optional)");
  await expect(rationale).toHaveAttribute("maxlength", "2000");
  await rationale.fill("  Wait for the opening range; keep simulated risk small.  ");
  for (const value of ["0", "10001"]) {
    await panel.getByLabel("Model call limit", { exact: true }).fill(value);
    await start.click();
    await expect(panel.getByRole("alert")).toHaveText("Model call limit must be a whole number from 1 to 10,000.");
    expect(syntheticApi.callCount("POST", `${AGENT}/start`)).toBe(0);
  }
  await panel.getByLabel("Model call limit", { exact: true }).fill("12");
  for (const value of ["15", "4097"]) {
    await panel.getByLabel("Output tokens per response", { exact: true }).fill(value);
    await start.click();
    await expect(panel.getByRole("alert")).toHaveText("Output tokens per response must be a whole number from 16 to 4,096.");
    expect(syntheticApi.callCount("POST", `${AGENT}/start`)).toBe(0);
  }
  await panel.getByLabel("Output tokens per response", { exact: true }).fill("256");
  await start.click();
  await expect(panel.getByRole("status")).toHaveText("Waiting for market session");
  await expect(start).toHaveCount(0);
  const stop = panel.getByRole("button", { name: "Stop & square off" });
  await expect(stop).toBeEnabled();
  await expect(panel.getByText("Wait for the opening range; keep simulated risk small.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("region", { name: "Practice model usage" })).toContainText("1 / 12 model calls used");

  setRunState(state, "running", true);
  await refresh(panel);
  await expect(panel.getByRole("status")).toHaveText("Running");
  await expect(panel.getByRole("table", { name: "Agent positions" })).toContainText("RELIANCE");
  await expect(panel.getByRole("list", { name: "Practice run events" })).toContainText("running");
  await stop.click();
  await expect(panel.getByRole("status")).toHaveText("Stopping");
  await expect(stop).toBeDisabled();
  await expect(start).toHaveCount(0);
  expect(syntheticApi.callCount("POST", `${AGENT}/start`)).toBe(1);
  expect(syntheticApi.callCount("POST", `${AGENT}/stop`)).toBe(1);
  await captureAgentEvidence(page, panel, stop, "Stopping", testInfo, "practice-agent-stopping");
});

test.describe("Practice reconciliation", () => {
  test.use({ benignConsoleErrors: [{
    text: "Failed to load resource: the server responded with a status of 409 (Conflict)",
    url: `http://localhost:5173${RESOLVE}`, expectedCalls: 1,
  }] });

  test("keeps an interrupted run blocked until an explicit resolution verifies a flat account", async ({ page, syntheticApi }, testInfo) => {
    const state = idleState();
    setRunState(state, "reconciliation_required", true);
    registerAgentReads(syntheticApi, state);
    let flat = false;
    syntheticApi.register({
      name: "resolve only after synthetic server flatness check", method: "POST", path: RESOLVE,
      expectedCalls: 2,
      handler: (request) => {
        expectPracticeAuthority(request);
        expect(request.postDataJSON()).toEqual({});
        if (!flat) return { status: 409, json: { status: "error", message: "Practice account still has open positions" } };
        setRunState(state, "stopped");
        return { json: { status: "success", data: state.snapshot } };
      },
    });
    const panel = await openPracticeAgent(page, syntheticApi);
    const start = panel.getByRole("button", { name: "Start agent" });
    const resolve = panel.getByRole("button", { name: "Resolve interrupted run" });
    await expect(panel.getByRole("status")).toHaveText("Interrupted · reconciliation required");
    await expect(start).toBeDisabled();
    await expect(resolve).toBeEnabled();
    await expect(panel.getByText(/There is no automatic replay/)).toBeVisible();
    expect(syntheticApi.callCount("POST", RESOLVE)).toBe(0);
    await resolve.click();
    await expect(panel.getByRole("alert")).toHaveText("Practice account still has open positions");
    await expect(start).toBeDisabled();

    flat = true;
    setRunState(state, "reconciliation_required");
    await refresh(panel);
    await expect(panel.getByText("No open agent positions reported.")).toBeVisible();
    await expect(start).toBeDisabled();
    expect(syntheticApi.callCount("POST", RESOLVE)).toBe(1);
    await resolve.click();
    await expect(panel.getByRole("status")).toHaveText("Stopped");
    await expect(start).toBeEnabled();
    await expect(resolve).toHaveCount(0);
    await expect(panel.getByRole("list", { name: "Practice run events" })).toContainText("stopped");
    // No start/stop/order/model handler is registered: any replay fails teardown.
    expect(syntheticApi.callCount("POST", RESOLVE)).toBe(2);
    await captureAgentEvidence(page, panel, start, "Stopped", testInfo, "practice-agent-resolved");
  });
});

test("rejects wrong-mode evidence and discards Practice controls across mode changes without Live activation", async ({ page, syntheticApi }) => {
  const state = idleState();
  state.snapshot.mode = "live";
  registerAgentReads(syntheticApi, state);
  const panel = await openPracticeAgent(page, syntheticApi);
  const start = panel.getByRole("button", { name: "Start agent" });
  await expect(panel.getByRole("status")).toHaveText("Mode mismatch");
  await expect(start).toBeDisabled();
  await expect(panel.getByRole("alert")).toContainText("server session mode differs from practice");
  state.snapshot.mode = "practice";
  await refresh(panel);
  await expect(start).toBeEnabled();
  await panel.getByLabel("Operator entry rationale (optional)").fill("Practice-only draft");

  for (const mode of ["live", "explore"] as const) {
    const practiceStatusReads = syntheticApi.callCount("GET", `${AGENT}/status`);
    const practiceHistoryReads = syntheticApi.callCount("GET", `${AGENT}/practice/runs`);
    await setSyntheticMode(page, mode);
    await expect(panel).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Agent", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Start agent" })).toHaveCount(0);
    await expect(page.getByText("Practice-only draft", { exact: true })).toHaveCount(0);
    expect(syntheticApi.callCount("GET", `${AGENT}/status`)).toBe(practiceStatusReads);
    expect(syntheticApi.callCount("GET", `${AGENT}/practice/runs`)).toBe(practiceHistoryReads);
  }
  await setSyntheticMode(page, "practice");
  await expect(panel).toBeVisible();
  await expect(panel.getByLabel("Operator entry rationale (optional)")).toHaveValue("");
  await expect(start).toBeEnabled();
  await panel.getByRole("button", { name: "Close panel" }).click();
  await expect(panel).toHaveCount(0);
  await page.getByRole("button", { name: "Agent", exact: true }).click();
  await expect(panel).toBeVisible();
  // No write handler exists in this journey. Any automatic start, stop,
  // resolve, Live unlock, broker order or model call fails the registry.
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
});
