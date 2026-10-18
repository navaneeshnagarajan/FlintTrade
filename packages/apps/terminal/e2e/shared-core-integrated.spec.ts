import fs from "node:fs/promises";
import { createWriteStream } from "node:fs";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { createHash } from "node:crypto";
import { request as ownedRequest, type Locator, type Page, type Request, type TestInfo } from "@playwright/test";
import { z } from "zod";
import { test as guardedTest, expect, type HttpMethod, type SyntheticPhasedFixtureRegistry } from "./fixture-registry";
import { EDGE_PROBE_URLS, PUBLIC_INTERNET_PROBE_URL } from "../src/lib/operatorProbeUrls";

// This journey requires an owned, OS-isolated normal-factory core. It does not
// supply application API responses or claim provider/native qualification.
const statePath = process.env["FLINTTRADE_E2E_CORE_STATE"];
if (!statePath) throw new Error("An isolated normal-factory controller must supply FLINTTRADE_E2E_CORE_STATE");
const Bootstrap = z.object({ session: z.object({ token: z.string(), username: z.string(), expiresAt: z.string() }), connection_id: z.string(), snapshot_id: z.string(), baseURL: z.string() });
const prefix = process.env["R24_STAGE"] === "reticle" ? "/ft-api" : "";
// The exact native refusal is expected product behaviour, not readiness.
// CSP/page errors remain fatal and are never waived.
// R38 event-held qualification: shell's three shared retry attempts, then
// Terminal's overlapping Watchlist/interval/quote group and fresh history.
const nativeShellReads = 3;
const nativeTerminalReads = 2;
const nativeReadBudget = (title: string) => nativeShellReads + (title.startsWith("nine actual") ? 2 * nativeTerminalReads : 0);
const test = guardedTest.extend<{ coreLifetime: void }>({
  coreLifetime: [async ({ syntheticApi, context }, use, info) => {
    const port = process.env["R24_CORE_PORT"];
    if (!port || !["5100", "5173"].includes(port)) throw new Error("Missing owned core port");
    const caseKey = sha(info.testId);
    await fs.rm(statePath!, { force: true });
    const child = spawn(process.env["FLINTTRADE_E2E_PYTHON"] ?? "python", [process.env["FLINTTRADE_E2E_CORE_SERVER"] ?? new URL("../../../../tools/reticle/harness/core-server.py", import.meta.url).pathname, "--port", port, "--case-key", caseKey, "--output", info.outputPath("normal-core")], { stdio: ["pipe", "pipe", "pipe"] });
    const log = createWriteStream(info.outputPath("normal-core.log"));
    child.stdout.pipe(log, { end: false }); child.stderr.pipe(log, { end: false });
    const lines = createInterface({ input: child.stdout });
    const exited = new Promise<{ code: number | null; signal: string | null }>((resolve, reject) => {
      child.once("error", reject);
      child.once("close", (code, signal) => { log.end(); resolve({ code, signal }); });
    });
    const ready = new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Owned normal factory did not become ready")), 30000);
      lines.on("line", line => { if (line === "R24_CORE_READY") { clearTimeout(timer); resolve(); } });
      void exited.then(result => { clearTimeout(timer); reject(new Error("Core exited before readiness: " + JSON.stringify(result))); }, reject);
    });
    try {
      await ready;
      await use();
    } finally {
      // Close the guarded page/drain all relay handlers while their owner is
      // still alive. Only then stop this exact process, not a port holder.
      try { await syntheticApi.dispose(); }
      finally {
        await relayClosers.get(info.testId)?.();
        relayClosers.delete(info.testId);
        // Installed static assets use the browser's own HTTP pool, separate
        // from the relay context. Retire both before joining Waitress.
        await context.close();
        child.stdin.end("STOP\n");
        let timer: ReturnType<typeof setTimeout> | undefined;
        try {
          const result = await Promise.race([exited, new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error("Owned core shutdown timed out")), 30000);
          })]);
          expect(result).toEqual({ code: 0, signal: null });
          const shutdown = z.object({ admission_drained: z.literal(true), listener_stopped: z.literal(true), listener_closed_probe: z.literal(true), remaining_threads: z.array(z.string()).length(0), owners: z.record(z.string(), z.object({ closed: z.literal(true) })) }).parse(JSON.parse(await fs.readFile(info.outputPath("normal-core/shutdown.json"), "utf8")));
          expect(Object.keys(shutdown.owners).length).toBeGreaterThanOrEqual(3);
        } finally {
          clearTimeout(timer); lines.close();
          if (child.exitCode === null && child.signalCode === null) { child.kill("SIGKILL"); await exited; }
        }
      }
    }
  }, { auto: true, scope: "test", timeout: 60000 }],
  benignConsoleErrors: async ({}, use, info) => {
  const allowances = [{ text: "Failed to load resource: the server responded with a status of 503 (Service Unavailable)", url: "http://127.0.0.1:5173" + prefix + "/api/v1/native/accounts", expectedCalls: nativeReadBudget(info.title) }];
  if (info.title.startsWith("learning and training")) {
    allowances.push({ text: "Failed to load resource: the server responded with a status of 400 (Bad Request)", url: "http://127.0.0.1:5173" + prefix + "/v1/learning/permissions/preview", expectedCalls: 1 });
    allowances.push({ text: "Failed to load resource: the server responded with a status of 403 (Forbidden)", url: "http://127.0.0.1:5173" + prefix + "/api/v1/backtest/training/jobs", expectedCalls: 1 });
  }
  await use(allowances);
} });
const sha = (value: string) => createHash("sha256").update(value).digest("hex");
interface CaptureWitness {
  startWitness(page: Page, info: TestInfo): void;
  finishWitness(client: unknown, verdict: unknown, info: TestInfo, name: string, predicate: unknown): Promise<{ accepted: boolean }>;
}
async function captureWitness(): Promise<CaptureWitness> {
  const path = process.env["FLINTTRADE_E2E_RETICLE_WITNESS"];
  if (!path) throw new Error("Hash-qualified complete-capture witness required for Reticle stage");
  return import(path);
}
test.beforeEach(async ({ page }, info) => {
  if (prefix) (await captureWitness()).startWitness(page, info);
});
const diagnosticClosers = new Map<string, () => Promise<void>>();
const relayClosers = new Map<string, () => Promise<void>>();
interface QueryObservation { key: unknown; status: string; fetchStatus: string; failures: number; observers: number; error: string }
interface DiscoveryObservation {
  events: { id: number; borrowersBefore: number; stopped: boolean; aborted: boolean; stack: string }[];
  locations: unknown[]; errors: string[];
  flights(): Promise<{ id: number; borrowers: number; stopped: boolean; aborted: boolean }[]>;
  queries(): Promise<QueryObservation[]>;
}
const discoveryProbes = new WeakMap<Page, DiscoveryObservation>();
async function querySnapshot(page: Page): Promise<QueryObservation[]> {
  if (page.isClosed()) return [];
  if (!prefix) return discoveryProbes.get(page)?.queries() ?? [];
  return page.evaluate(async () => {
    // Observe the already-mounted provider; never re-import the entry or
    // change the cache, its query options, or application state.
    const path = "/src/providers/QueryProvider.tsx";
    const module: { queryClient: { getQueryCache(): { getAll(): { queryKey: unknown; state: { status: string; fetchStatus: string; fetchFailureCount: number; error: unknown }; getObserversCount(): number }[] } } } = await import(/* @vite-ignore */ path);
    return module.queryClient.getQueryCache().getAll().map(query => ({ key: query.queryKey, status: query.state.status, fetchStatus: query.state.fetchStatus, failures: query.state.fetchFailureCount, observers: query.getObserversCount(), error: String(query.state.error) }));
  });
}
test.afterEach(async ({}, info) => {
  const close = diagnosticClosers.get(info.testId);
  try { await close?.(); } finally { diagnosticClosers.delete(info.testId); }
});
interface Row { method: string; path: string; body: unknown; status: number; response: unknown; etag: string | undefined; bodySha256: string; responseSha256: string; trial: string | undefined; experiment: string | undefined }
function safe(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safe);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, /^(?:credential|authorization|token|password|api_key)$/i.test(key) ? "<redacted-synthetic>" : safe(child)]));
  return value;
}
async function setup(page: Page, registry: SyntheticPhasedFixtureRegistry, info: TestInfo) {
  const bootstrap = Bootstrap.parse(JSON.parse(await fs.readFile(statePath!, "utf8")));
  const transport = await ownedRequest.newContext();
  relayClosers.set(info.testId, () => transport.dispose());
  const rows: Row[] = [];
  let writing = Promise.resolve();
  const consoleRows: unknown[] = [];
  const initiators: unknown[] = [];
  const browserBodies: unknown[] = [];
  const bodyReads: Promise<void>[] = [];
  const registered: { method: HttpMethod; path: string; expected: unknown }[] = [];
  page.on("response", response => {
    const url = new URL(response.url());
    if (url.origin !== "http://127.0.0.1:5173" || !/^\/(?:ft-api|api|v1|health)(?:\/|$)/.test(url.pathname)) return;
    bodyReads.push((async () => {
      const request = response.request();
      const common = { method: request.method(), path: url.pathname + url.search, status: response.status(), bodySha256: sha(request.postData() ?? "") };
      try {
        const error = await response.finished();
        if (error) throw error;
        const body = await response.body();
        browserBodies.push({ ...common, completed: true, responseSha256: createHash("sha256").update(body).digest("hex") });
      } catch (error) { browserBodies.push({ ...common, completed: false, error: String(error) }); }
    })());
  });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Debugger.enable");
  await cdp.send("Debugger.setAsyncCallStackDepth", { maxDepth: 32 });
  const probePath = process.env["FLINTTRADE_E2E_DISCOVERY_PROBE"];
  if (!probePath) throw new Error("Owned R38 read-only discovery observer required");
  const probeModule: { installDiscoveryProbe(page: Page, cdp: unknown): Promise<DiscoveryObservation> } = await import(probePath);
  const discovery = await probeModule.installDiscoveryProbe(page, cdp);
  discoveryProbes.set(page, discovery);
  const heldDiscoveries: unknown[] = [];
  cdp.on("Network.requestWillBeSent", event => {
    if (event.request.url.includes("/api/v1/native/accounts")) initiators.push({ event: "request", id: event.requestId, url: event.request.url, method: event.request.method, timestamp: event.timestamp, initiator: event.initiator });
  });
  cdp.on("Network.loadingFailed", event => { initiators.push({ event: "failed", ...event }); });
  diagnosticClosers.set(info.testId, async () => {
    await writing;
    await Promise.all(bodyReads);
    await fs.writeFile(info.outputPath("browser-completed-bodies.json"), JSON.stringify(browserBodies, null, 2));
    await fs.writeFile(info.outputPath("registry-counts.json"), JSON.stringify(registered.map(row => ({ ...row, calls: registry.callCount(row.method, row.path), ...(row.method === "GET" ? { reads: registry.readCounts(row.path) } : {}) })), null, 2));
    await fs.writeFile(info.outputPath("browser-console.json"), JSON.stringify(consoleRows, null, 2));
    await fs.writeFile(info.outputPath("read-initiators.json"), JSON.stringify(initiators, null, 2));
    await fs.writeFile(info.outputPath("query-cache-final.json"), JSON.stringify(await querySnapshot(page), null, 2));
    await fs.writeFile(info.outputPath("discovery-observation.json"), JSON.stringify({ events: discovery.events, locations: discovery.locations, errors: discovery.errors, held: heldDiscoveries, flights: page.isClosed() ? [] : await discovery.flights() }, null, 2));
    expect.soft(discovery.errors).toEqual([]);
    const clientPath = process.env["FLINTTRADE_E2E_RETICLE_CLIENT"];
    if (clientPath && info.title.startsWith("learning and training")) {
      const module: { connectReticle(path: string): Promise<{ call(name: string, args: Record<string, unknown>): Promise<unknown>; close(): void }> } = await import(clientPath);
      const client = await module.connectReticle(info.outputPath("refusal-diagnostic-transcript.json"));
      try {
        const events = await client.call("reticle_observe", { action: "events", since: 0, filters: ["net", "signal"], max_events: 2000 });
        await fs.writeFile(info.outputPath("refusal-diagnostic-events.json"), JSON.stringify(events, null, 2));
      } finally { client.close(); }
    }
    await cdp.detach();
  });
  page.on("console", message => { consoleRows.push({ type: message.type(), text: message.text(), location: message.location() }); });
  page.on("requestfailed", request => { consoleRows.push({ method: request.method(), url: request.url(), failure: request.failure() }); });
  async function relay(request: Request): Promise<{ status: number; headers: Record<string, string>; body: string; row: Row }> {
    const url = new URL(request.url());
    expect(url.origin).toBe("http://127.0.0.1:5173");
    const auth = request.headers()["authorization"];
    if (auth !== undefined) expect(auth).toBe("Bearer " + bootstrap.session.token);
    const data = request.postData() ?? "";
    if (request.method() === "GET") expect(data).toBe("");
    const response = await transport.fetch(bootstrap.baseURL + url.pathname + url.search, {
      method: request.method(), headers: request.headers(), ...(data ? { data } : {}), maxRedirects: 0, failOnStatusCode: false,
    });
    const text = await response.text();
    let parsed: unknown = text;
    try { parsed = JSON.parse(text); } catch { /* Retain exact non-JSON evidence. */ }
    const row: Row = { method: request.method(), path: url.pathname + url.search, body: safe(data ? JSON.parse(data) : null), status: response.status(), response: safe(parsed), etag: response.headers()["etag"], bodySha256: sha(data), responseSha256: sha(text), trial: response.headers()["x-trial-id"], experiment: response.headers()["x-experiment-id"] };
    rows.push(row);
    writing = writing.then(async () => {
      await fs.writeFile(info.outputPath("core-relay-ledger.json"), JSON.stringify(rows, null, 2));
      await fs.writeFile(info.outputPath("browser-console.json"), JSON.stringify(consoleRows, null, 2));
    });
    await writing;
    return { status: response.status(), headers: response.headers(), body: text, row };
  }
  function register(method: HttpMethod, path: string, calls: number | { minimum: number; maximum: number } = 1, validate?: (request: Request) => void, observed?: (row: Row) => void) {
    registered.push({ method, path: prefix + path, expected: calls });
    registry.register({ name: `${method} ${path}`, method, path: prefix + path, expectedCalls: calls, handler: async request => { validate?.(request); const response = await relay(request); observed?.(response.row); return response; } });
  }
  function registerRead(path: string, calls: number, expectedNotFound?: true) {
    registered.push({ method: "GET", path: prefix + path, expected: { calls, phase: "required", expectedNotFound } });
    registry.register({ name: `required GET ${path}`, method: "GET", path: prefix + path, expectedCalls: calls, readPhase: "required", expectedNotFound, handler: relay });
  }
  for (const path of ["/v1/auth/status", "/health", "/api/v1/ping", "/api/v1/advisor/status", "/api/v1/instrument-lots", "/api/v1/system/diagnostics", "/v1/config/llm", "/v1/sandbox/funds", "/v1/sandbox/positions", "/v1/sandbox/status"]) {
    register("GET", path, { minimum: 0, maximum: 8 });
  }
  const nativePath = prefix + "/api/v1/native/accounts";
  let nativeBaseline = 0;
  const nativePhases: unknown[] = [];
  const releasedFlights = new Set<number>();
  function shellQueries(queries: QueryObservation[]) {
    return queries.filter(query => JSON.stringify(query.key) === '["broker","accounts"]' || JSON.stringify(query.key) === '["timings"]');
  }
  function nativePhase(name: string, completed: number) {
    const terminalPhase = name !== "initial shell discovery";
    registered.push({ method: "GET", path: nativePath, expected: { completed, phase: "startup", name } });
    registry.register({ name, method: "GET", path: nativePath, expectedCalls: completed, readPhase: "startup", handler: async request => {
      const response = await relay(request); // actual owned reply; bytes never replaced
      const target = terminalPhase ? (registry.readCounts(nativePath).completed === nativeBaseline ? 3 : 1) : 2;
      let flight: { id: number; borrowers: number; stopped: boolean; aborted: boolean } | undefined;
      // A real route holds the actual body until all declared borrowers join.
      // Cancellation is checked independently from browser requestfailed; a JS
      // retirement is never counted as an HTTP cancellation.
      await expect.poll(async () => {
        if (request.failure()) {
          expect(request.failure()?.errorText).toBe("net::ERR_ABORTED");
          return true;
        }
        flight = (await discovery.flights()).find(item => !releasedFlights.has(item.id) && !item.stopped && !item.aborted && item.borrowers === target);
        return flight !== undefined;
      }, { message: name + " awaits " + target + " actual overlapping borrowers" }).toBe(true);
      const queries = await querySnapshot(page);
      if (!request.failure()) {
        expect(flight).toBeDefined();
        if (!terminalPhase) expect(shellQueries(queries).map(query => [query.status, query.fetchStatus, query.failures]))
          .toEqual(Array.from({ length: 2 }, () => ["pending", "fetching", releasedFlights.size]));
        releasedFlights.add(flight!.id);
      }
      heldDiscoveries.push({ phase: name, target, flight, browserFailureBeforeRelease: request.failure(), queries, responseSha256: response.row.responseSha256 });
      return response;
    } });
  }
  async function retireNative(completed: number) {
    await expect.poll(() => registry.readCounts(nativePath).completed).toBe(nativeBaseline + completed);
    await expect.poll(async () => shellQueries(await querySnapshot(page))
      .map(query => [query.status, query.fetchStatus, query.failures, query.error])).toEqual([
      ["error", "idle", 3, "FtApiError: Credential store unavailable."],
      ["error", "idle", 3, "FtApiError: Credential store unavailable."],
    ]);
    const counts = await registry.retireRead(nativePath);
    nativeBaseline += completed;
    nativePhases.push({ completedObligation: completed, counts, queries: await querySnapshot(page) });
    await fs.writeFile(info.outputPath("discovery-phases.json"), JSON.stringify(nativePhases, null, 2));
    return counts;
  }
  nativePhase("initial shell discovery", nativeShellReads);
  const probes = [...EDGE_PROBE_URLS, PUBLIC_INTERNET_PROBE_URL];
  for (const path of new Set(probes.map(value => new URL(value).pathname))) {
    registry.register({ name: "inert external availability transport " + path, method: "GET", path, expectedCalls: { minimum: 0, maximum: 8 }, handler: request => {
      expect(probes).toContain(request.url()); expect(request.postData()).toBeNull(); expect(request.headers()["authorization"]).toBeUndefined();
      return { status: 204, body: "" };
    } });
  }
  await page.addInitScript(session => {
    sessionStorage.setItem("flinttrade:auth-session", JSON.stringify(session));
    localStorage.setItem("flinttrade:mode", JSON.stringify({ state: { mode: "practice" }, version: 2 }));
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  }, bootstrap.session);
  async function finish() {
    if (nativeBaseline === 0) await retireNative(nativeShellReads);
    expect(discovery.errors).toEqual([]);
    expect(discovery.locations).toHaveLength(1);
    await expect.poll(() => registry.readCounts(prefix + "/api/v1/native/accounts").completed).toBe(nativeReadBudget(info.title));
    expect(rows.filter(row => row.path === prefix + "/api/v1/native/accounts").every(row => row.status === 503)).toBe(true);
  }
  return { bootstrap, register, registerRead, rows, finish, nativePhase, retireNative };
}
async function declaredReticle(info: TestInfo, predicates: Record<string, unknown>[], name = "reticle") {
  const clientPath = process.env["FLINTTRADE_E2E_RETICLE_CLIENT"];
  if (!clientPath) { if (prefix) throw new Error("Reticle stage requires the owned client"); return; }
  interface Client { call(name: string, args: Record<string, unknown>): Promise<Record<string, unknown>>; close(): void }
  const module: { connectReticle(path: string): Promise<Client> } = await import(clientPath);
  const client = await module.connectReticle(info.outputPath(name + "-transcript.json"));
  try {
    await client.call("reticle_session", { action: "list" });
    await client.call("reticle_look", { action: "state" });
    // Public, unfiltered-by-outcome timeline: retain IDs, ordering and actual
    // hydration signal semantics without changing the assertion's full window.
    const events = await client.call("reticle_observe", { action: "events", since: 0, filters: ["net", "signal"], max_events: 2000 });
    await fs.writeFile(info.outputPath(name + "-events.json"), JSON.stringify(events, null, 2));
    const predicate = { kind: "allOf", predicates: [
      { kind: "net", method: "GET", urlContains: "/api/v1/native/accounts", status: 503, count: nativeReadBudget(info.title) }, ...predicates,
    ] };
    const verdict = await client.call("reticle_assert", { predicate, since: 0, timeout_ms: 2000 });
    await fs.writeFile(info.outputPath(name + "-verdict.json"), JSON.stringify({ predicate, verdict }, null, 2));
    const fullWindow = await (await captureWitness()).finishWitness(client, verdict, info, name, predicate);
    expect.soft(fullWindow.accepted, JSON.stringify(fullWindow)).toBe(true);
    // A rejected verdict still fails the case; soft checks only preserve later
    // independent evidence (e.g. actual immutable backtest after lease proof).
    expect.soft(verdict["verified"]).toBe("yes"); expect.soft(verdict["pass"]).toBe(true);
  } finally { client.close(); }
}
async function checkpoint(page: Page, info: TestInfo, name: string) {
  const presenter = page.getByRole("region", { name: "Reticle session", exact: true });
  const minimise = presenter.getByRole("button", { name: "Minimise chat", exact: true });
  if (await minimise.isVisible()) {
    // Keep the obscured evidence, then use Reticle's own supported UI. Never
    // remove an overlay node, change CSS or hide product safety information.
    await page.screenshot({ path: info.outputPath(name + ".presenter-obscured.png") });
    await fs.writeFile(info.outputPath(name + ".presenter-obscured.ax.txt"), await page.locator("body").ariaSnapshot());
    await minimise.click();
    await expect(minimise).not.toBeVisible();
  }
  await fs.writeFile(info.outputPath(name + ".queries.json"), JSON.stringify(await querySnapshot(page), null, 2));
  const geometry = await page.evaluate(() => {
    const selectors = ['[aria-label="Complete procedure body"]', '[aria-label="Declared portfolio records"] > li', '[aria-label="Task receipt"]', '[aria-label="Service connection setup"] [role="status"]', '[aria-label="Exact immutable manifest"]', '[aria-label="Exact core evidence"]', '[data-testid="system-status-bar"]', '[role="alert"]'];
    const box = (rect: DOMRect) => ({ left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height });
    return selectors.flatMap(selector => [...document.querySelectorAll<HTMLElement>(selector)].map(element => {
      const rect = element.getBoundingClientRect();
      const range = document.createRange(); range.selectNodeContents(element);
      const ranges = [...range.getClientRects()].map(box);
      const literalRanges = [];
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.textContent?.trim()) continue;
        const literal = document.createRange(); literal.selectNodeContents(node);
        literalRanges.push({ text: node.textContent, ranges: [...literal.getClientRects()].map(box) });
      }
      const clipping = [];
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        const css = getComputedStyle(parent);
        if (/(hidden|clip|auto|scroll)/.test(css.overflowX + css.overflowY)) clipping.push({ tag: parent.tagName, class: parent.className, label: parent.getAttribute("aria-label"), overflowX: css.overflowX, overflowY: css.overflowY, clientHeight: parent.clientHeight, scrollHeight: parent.scrollHeight, scrollTop: parent.scrollTop, flex: css.flex, minHeight: css.minHeight, box: box(parent.getBoundingClientRect()) });
      }
      const centre = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return { selector, text: element.textContent, box: box(rect), ranges, literalRanges, clipping, viewport: { width: innerWidth, height: innerHeight }, centreHit: centre !== null && (element.contains(centre) || centre.contains(element)), fullyInViewport: rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight };
    }));
  });
  await fs.writeFile(info.outputPath(name + ".geometry.json"), JSON.stringify(geometry, null, 2));
  await fs.writeFile(info.outputPath(name + ".browser.json"), JSON.stringify({ browser: page.context().browser()?.version(), viewport: page.viewportSize() }));
  await page.screenshot({ path: info.outputPath(name + ".png") });
  await fs.writeFile(info.outputPath(name + ".html"), await page.content());
  await fs.writeFile(info.outputPath(name + ".ax.txt"), await page.locator("body").ariaSnapshot());
}
async function scrollKeyAndSettle(page: Page, scroller: Locator, key: "ArrowDown" | "PageDown") {
  const before = await scroller.evaluate(element => element.scrollTop);
  // Native key scrolling animates. Its first moved pixel is not settlement;
  // await the browser's actual scrollend rather than queueing more key pulses.
  await Promise.all([
    scroller.evaluate(element => new Promise<void>(resolve => element.addEventListener("scrollend", () => resolve(), { once: true }))),
    page.keyboard.press(key),
  ]);
  expect(await scroller.evaluate(element => element.scrollTop)).toBeGreaterThan(before);
}
async function scrollWheelAndSettle(page: Page, scroller: Locator, delta: number) {
  const box = await scroller.boundingBox();
  if (!box) throw new Error("Missing real portfolio scroll owner");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await Promise.all([
    scroller.evaluate(element => new Promise<void>(resolve => element.addEventListener("scrollend", () => resolve(), { once: true }))),
    page.mouse.wheel(0, delta),
  ]);
}
async function clearReticleTextOverlap(page: Page, row: Locator, info: TestInfo, name: string) {
  if (!prefix) return;
  const presenterPath = process.env["FLINTTRADE_E2E_RETICLE_PRESENTER"];
  if (!presenterPath) throw new Error("Qualified Reticle presenter helper required");
  const module: { ensureReticleChatMinimised(page: Page, info: TestInfo, name: string): Promise<{ x: number; y: number; width: number; height: number }> } = await import(presenterPath);
  const presenter = await module.ensureReticleChatMinimised(page, info, name);
  const content = await row.evaluate(element => {
    const range = document.createRange(); range.selectNodeContents(element);
    const rects = [...range.getClientRects()];
    return { bottom: Math.max(...rects.map(rect => rect.bottom)), right: Math.max(...rects.map(rect => rect.right)) };
  });
  if (content.right > presenter.x && content.bottom > presenter.y) {
    // Keep the real obscured capture. Move the user's scroll owner, never the
    // presenter or instrumentation. Row-centre hit alone missed this hash edge.
    await page.screenshot({ path: info.outputPath(name + ".text-overlay-obscured.png") });
    await scrollWheelAndSettle(page, page.getByRole("region", { name: "Investment views and evidence", exact: true }), content.bottom - presenter.y + 16);
    await expect.poll(() => readableRow(row)).toEqual({ complete: true, painted: true });
  }
}
async function readableRow(row: Locator) {
  return row.evaluate(element => {
    const range = document.createRange(); range.selectNodeContents(element);
    const rect = element.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    const ranges = [...range.getClientRects()];
    let complete = ranges.every(r => r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight);
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      const css = getComputedStyle(parent), clip = parent.getBoundingClientRect();
      if (/(hidden|clip|auto|scroll)/.test(css.overflowY)) complete = complete && ranges.every(r => r.top >= clip.top && r.bottom <= clip.bottom);
      if (/(hidden|clip|auto|scroll)/.test(css.overflowX)) complete = complete && ranges.every(r => r.left >= clip.left && r.right <= clip.right);
    }
    return { complete, painted: !!hit && (element.contains(hit) || hit.contains(element)) };
  });
}
async function addWidget(page: Page, name: string) {
  const route = new URL(page.url()).pathname.split("/").filter(Boolean).at(-1) ?? "terminal";
  const app = route.charAt(0).toUpperCase() + route.slice(1);
  const region = page.getByRole("region", { name: app + " app", exact: true });
  await expect(region).toBeVisible();
  await region.getByRole("button", { name: "Add widget", exact: true }).click();
  await page.getByRole("button", { name: "Add " + name, exact: true }).click();
}

test("installed knowledge reads the normal-factory full catalogue", async ({ page, syntheticApi }, info) => {
  const core = await setup(page, syntheticApi, info);
  core.register("GET", "/v1/knowledge/skills", 4);
  core.register("GET", "/v1/knowledge/skills/risk_management", 2);
  core.register("GET", "/v1/services/connections");
  let requestId = "";
  core.register("POST", "/v1/services/connections/tasks", 1, request => {
    const body = z.object({ request_id: z.string().uuid(), selection: z.object({ connection_revision: z.string() }) }).passthrough().parse(request.postDataJSON());
    requestId = body.request_id;
    expect(request.postDataJSON()).toEqual({ request_id: requestId, mode: "fixed", selection: { connection_id: core.bootstrap.connection_id, connection_revision: body.selection.connection_revision, model: "test-model-v1", effort: "balanced" }, prompt: "Read the selected procedure; no trading.", classification: "public", context_refs: ["skill:risk_management"], purpose: "assistant", deadline_ms: 2000, max_output_tokens: 256, required_hard_controls: ["output_tokens"] });
    core.register("GET", "/v1/services/connections/tasks/" + requestId, 2);
  });
  await page.goto("/learn");
  await expect(page.getByRole("navigation", { name: "Apps", exact: true })).toBeVisible();
  await addWidget(page, "Shared knowledge");
  await page.getByRole("button", { name: "Read procedure risk_management", exact: true }).click();
  await expect(page.getByLabel("Complete procedure body")).toBeVisible();
  const response = z.object({ scope: z.null(), body: z.string(), reference: z.literal("skill:risk_management"), version: z.string().min(1) }).parse(core.rows.find(row => row.path.endsWith("/skills/risk_management"))?.response);
  await expect(page.getByLabel("Complete procedure body")).toHaveText(response.body);
  for (const row of core.rows.filter(item => item.path.endsWith("/knowledge/skills"))) {
    const catalogue = z.object({ scope: z.null(), skills: z.array(z.object({ name: z.string(), version_id: z.string(), package_hash: z.string().regex(/^[a-f0-9]{64}$/), enabled: z.boolean() })) }).parse(row.response);
    expect(catalogue.skills.find(item => item.name === "risk_management" && item.enabled)?.version_id).toBe(response.version);
  }
  await page.getByRole("button", { name: "Select this procedure", exact: true }).click();
  await expect(page.getByText("Explicit task selection: skill:risk_management", { exact: true })).toBeVisible();
  await checkpoint(page, info, "knowledge-wide");
  await page.setViewportSize({ width: 600, height: 760 });
  await page.getByLabel("Complete procedure body").scrollIntoViewIfNeeded();
  await checkpoint(page, info, "knowledge-compact");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("navigation", { name: "Apps", exact: true }).getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("region", { name: "Settings app", exact: true })).toBeVisible();
  await addWidget(page, "Model connections and tasks");
  await page.getByLabel("Task connection").selectOption(core.bootstrap.connection_id);
  await page.getByLabel("Task effort").fill("balanced");
  await page.getByLabel("Task deadline").fill("2000");
  await page.getByLabel("Task output limit").fill("256");
  await page.getByLabel("Advisory task").fill("Read the selected procedure; no trading.");
  await page.getByRole("button", { name: "Send advisory task", exact: true }).click();
  const receipt = page.getByRole("region", { name: "Task receipt", exact: true });
  await expect(receipt).toContainText("completed");
  await expect.soft(receipt).toContainText("Synthetic external transport: procedure received; no model ran.");
  await page.getByRole("button", { name: "Read durable receipt", exact: true }).click();
  await expect.poll(() => core.rows.filter(row => row.path.endsWith("/tasks/" + requestId)).length).toBe(2);
  const posted = core.rows.find(row => row.method === "POST" && row.path.endsWith("/tasks"));
  const readback = core.rows.find(row => row.method === "GET" && row.path.endsWith("/tasks/" + requestId));
  const initial = z.record(z.string(), z.unknown()).parse(posted?.response);
  const { output, ...durable } = initial;
  expect(output).toBe("Synthetic external transport: procedure received; no model ran.");
  expect(readback?.response).toEqual(durable);
  expect(durable["output_digest"]).toBe(sha(JSON.stringify(output)));
  await receipt.scrollIntoViewIfNeeded();
  await checkpoint(page, info, "task-durable-receipt");
  await core.finish();
  await declaredReticle(info, [ { kind: "text", scope: '[aria-label="Task receipt"]', contains: "completed", visible: true }, { kind: "net", method: "POST", urlContains: "/v1/services/connections/tasks", count: 1 } ]);
});

test("manual and CSV Portfolio evidence roundtrips with incomplete provenance", async ({ page, syntheticApi }, info) => {
  const core = await setup(page, syntheticApi, info);
  const path = "/api/v1/data/portfolio/evidence";
  core.register("GET", "/v1/sandbox/holdings", { minimum: 0, maximum: 2 });
  core.register("GET", path, 3);
  let writes = 0;
  const record = { record_id: "manual-synthetic", kind: "holding", instrument_id: "synthetic-declared-fund", venue: "manual", currency: "INR", quantity_unit: "units", quantity: "2.125", observed_at: "2026-01-05T15:00:00+00:00", cash_amount: null };
  // An explicitly separate private replay challenges the accepted 256-character
  // identity. The unfiltered six-case invocation retains its original payload.
  if (process.env["R35_LONG_IDENTITY"] === "1") record.instrument_id = "Opaque-" + "X".repeat(249);
  const csv = "record_id,kind,instrument_id,venue,currency,quantity_unit,quantity,observed_at,cash_amount\ncsv-synthetic,transaction,synthetic-declared-equity,manual,INR,shares,1.5,2026-01-05T15:00:00+00:00,123.45\n";
  core.register("POST", path, 2, request => {
    expect(request.headers()["authorization"]).toBe("Bearer " + core.bootstrap.session.token);
    expect(request.postDataJSON()).toEqual(++writes === 1 ? { origin: "manual", source_id: "synthetic-notes", records: [record] } : { origin: "statement_csv", source_id: "synthetic-statement", csv });
  });
  await page.goto("/portfolio");
  const panel = page.getByRole("region", { name: "Canonical portfolio evidence", exact: true });
  await expect(panel.getByText("No declared evidence available. This does not establish an empty or flat account.")).toBeVisible();
  await panel.getByLabel("Evidence source ID").fill("synthetic-notes");
  for (const [key, value] of Object.entries(record)) if (key !== "kind" && value !== null) await panel.getByLabel(key, { exact: true }).fill(value);
  await panel.getByRole("button", { name: "Submit declared evidence", exact: true }).click();
  await expect(panel.getByRole("status").filter({ hasText: "Receipt and declared-fact readback matched" })).toBeVisible();
  await panel.getByRole("button", { name: "Statement CSV", exact: true }).click();
  await panel.getByLabel("Evidence source ID").fill("synthetic-statement");
  await panel.getByLabel("Statement CSV content").fill(csv);
  await panel.getByRole("button", { name: "Submit declared evidence", exact: true }).click();
  await expect(panel.getByRole("list", { name: "Declared portfolio records" }).getByRole("listitem")).toHaveCount(2);
  const readback = z.object({ data: z.object({ status: z.literal("partial"), execution_authority: z.literal(false), records: z.array(z.object({ record_id: z.string(), origin: z.string(), quantity: z.string(), cash_amount: z.string().nullable() })) }) }).parse(core.rows.filter(row => row.method === "GET" && row.path === prefix + path).at(-1)?.response);
  expect(readback.data.records.map(row => [row.record_id, row.origin, row.quantity, row.cash_amount])).toEqual([["csv-synthetic", "statement_csv", "1.5", "123.45"], ["manual-synthetic", "manual", "2.125", null]]);
  await panel.getByRole("list", { name: "Declared portfolio records" }).scrollIntoViewIfNeeded();
  await checkpoint(page, info, "portfolio-wide");
  await page.setViewportSize({ width: 600, height: 760 });
  await panel.getByRole("list", { name: "Declared portfolio records" }).scrollIntoViewIfNeeded();
  await checkpoint(page, info, "portfolio-compact");
  const records = panel.getByRole("list", { name: "Declared portfolio records" }).getByRole("listitem");
  await expect(records.nth(1).locator("strong")).toHaveText(record.instrument_id);
  for (let index = 0; index < 2; index++) {
    const row = records.nth(index);
    await row.evaluate(element => element.scrollIntoView({ block: "center", inline: "nearest" }));
    await clearReticleTextOverlap(page, row, info, `portfolio-compact-record-${index}`);
    await checkpoint(page, info, `portfolio-compact-record-${index}`);
    const readable = await row.evaluate(element => {
      const range = document.createRange(); range.selectNodeContents(element);
      const rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      const ranges = [...range.getClientRects()];
      let complete = ranges.every(r => r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight);
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        const css = getComputedStyle(parent), clip = parent.getBoundingClientRect();
        if (/(hidden|clip|auto|scroll)/.test(css.overflowY)) complete = complete && ranges.every(r => r.top >= clip.top && r.bottom <= clip.bottom);
        if (/(hidden|clip|auto|scroll)/.test(css.overflowX)) complete = complete && ranges.every(r => r.left >= clip.left && r.right <= clip.right);
      }
      return { complete, painted: !!hit && (element.contains(hit) || hit.contains(element)) };
    });
    expect.soft(readable, "Complete literal portfolio record must paint inside its real clipping ancestors").toEqual({ complete: true, painted: true });
  }
  const scroller = page.getByRole("region", { name: "Investment views and evidence", exact: true });
  await expect(scroller).toHaveAttribute("tabindex", "0");
  await scroller.focus();
  await expect(scroller).toBeFocused();
  await page.keyboard.press("Home");
  await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBe(0);
  await checkpoint(page, info, "portfolio-keyboard-home");
  const target = records.nth(1);
  const wheel = await target.evaluate(element => {
    const owner = element.closest('[aria-label="Investment views and evidence"]')!;
    const a = owner.getBoundingClientRect(), b = element.getBoundingClientRect();
    return { x: a.left + a.width / 2, y: a.top + a.height / 2, delta: b.top + b.height / 2 - (a.top + a.height / 2) };
  });
  await scrollWheelAndSettle(page, scroller, wheel.delta);
  await expect.poll(() => readableRow(target)).toEqual({ complete: true, painted: true });
  await clearReticleTextOverlap(page, target, info, "portfolio-wheel-last-record");
  await checkpoint(page, info, "portfolio-wheel-last-record");
  await scroller.focus();
  await page.keyboard.press("Home");
  await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBe(0);
  // Ordinary keyboard input only. No scrollTop assignment or synthetic event;
  // a bounded loop stops on the unchanged complete-row paint oracle.
  for (let step = 0; step < 10 && await target.evaluate(element =>
    element.getBoundingClientRect().top > element.closest('[aria-label="Investment views and evidence"]')!.getBoundingClientRect().bottom
  ); step++) await scrollKeyAndSettle(page, scroller, "PageDown");
  for (let step = 0; step < 60 && !(await readableRow(target)).complete; step++) {
    await scrollKeyAndSettle(page, scroller, "ArrowDown");
  }
  // Continue with ordinary keys to centre the load-bearing row, rather than
  // stopping with its final line under the persistent local-help control.
  for (let step = 0; step < 10 && await target.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const owner = element.closest('[aria-label="Investment views and evidence"]')!.getBoundingClientRect();
    return rect.top + rect.height / 2 > owner.top + owner.height / 2;
  }); step++) {
    await scrollKeyAndSettle(page, scroller, "ArrowDown");
  }
  await expect.poll(() => readableRow(target)).toEqual({ complete: true, painted: true });
  await clearReticleTextOverlap(page, target, info, "portfolio-keyboard-last-record");
  await checkpoint(page, info, "portfolio-keyboard-last-record");
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect.poll(async () => (await scroller.boundingBox())?.width ?? 0).toBeGreaterThan(600);
  await checkpoint(page, info, "portfolio-resize-wide");
  await page.setViewportSize({ width: 600, height: 760 });
  await expect.poll(async () => (await scroller.boundingBox())?.width ?? 0).toBeLessThanOrEqual(600);
  await checkpoint(page, info, "portfolio-resize-compact-before-input");
  await scroller.focus();
  await expect(scroller).toBeFocused();
  await scroller.press("Home");
  await expect.poll(() => scroller.evaluate(element => element.scrollTop)).toBe(0);
  const returnedWheel = await target.evaluate(element => {
    const owner = element.closest('[aria-label="Investment views and evidence"]')!.getBoundingClientRect();
    const rect = element.getBoundingClientRect();
    return rect.top + rect.height / 2 - (owner.top + owner.height / 2);
  });
  await scrollWheelAndSettle(page, scroller, returnedWheel);
  await expect.poll(() => readableRow(target)).toEqual({ complete: true, painted: true });
  await clearReticleTextOverlap(page, target, info, "portfolio-resize-return");
  await checkpoint(page, info, "portfolio-resize-return");
  // Legacy investment views still exist alongside the canonical evidence.
  await expect(scroller.getByRole("tabpanel", { name: "Dashboard", exact: true })).toBeAttached();
  expect(writes).toBe(2);
  await core.finish();
  await declaredReticle(info, [{ kind: "net", method: "POST", urlContains: "/api/v1/data/portfolio/evidence", count: 2 }, { kind: "text", scope: '[aria-label="Declared portfolio records"]', contains: "synthetic-declared-equity", visible: true }]);
});

test("connection CRUD verifies exact item and collection revisions", async ({ page, syntheticApi }, info) => {
  const core = await setup(page, syntheticApi, info);
  const path = "/v1/services/connections";
  core.register("GET", "/v1/knowledge/skills", { minimum: 1, maximum: 2 });
  core.register("GET", path, 4);
  const credential = createHash("sha256").update(crypto.randomUUID()).digest("hex");
  let current = "";
  const ifMatch: string[] = [];
  function headers(request: Request) { expect(request.headers()["authorization"]).toBe("Bearer " + core.bootstrap.session.token); expect(request.headers()["idempotency-key"]).toMatch(/^[a-f0-9-]{36}$/); ifMatch.push(request.headers()["if-match"]); }
  core.register("POST", path, 1, request => { headers(request); expect(request.postDataJSON()).toEqual({ provider_id: "llm:openrouter", label: "Synthetic CRUD", model: "synthetic-not-a-model", auth_mode: "api_key", credential }); }, row => {
    const created = z.object({ connection_id: z.string(), credential_configured: z.literal(true) }).parse(row.response);
    current = created.connection_id;
    core.register("GET", path + "/" + current, 2);
    core.register("PATCH", path + "/" + current, 1, request => { headers(request); expect(request.postDataJSON()).toEqual({ label: "Synthetic CRUD revised", model: "synthetic-not-a-model", auth_mode: "api_key" }); });
    core.register("DELETE", path + "/" + current, 1, request => { headers(request); expect(request.postDataJSON()).toEqual({}); });
  });
  await page.goto("/settings");
  await addWidget(page, "Model connections and tasks");
  const panel = page.getByRole("region", { name: "Service connection setup", exact: true });
  await panel.getByRole("button", { name: "Add service connection", exact: true }).click();
  await panel.getByLabel("Connection provider").selectOption("llm:openrouter");
  await panel.getByLabel("Connection label").fill("Synthetic CRUD");
  await panel.getByLabel("Connection model").fill("synthetic-not-a-model");
  await panel.getByLabel("Connection authentication").selectOption("api_key");
  await panel.getByLabel("Credential action").selectOption("replace");
  await panel.getByLabel("Connection credential").fill(credential);
  await panel.getByRole("button", { name: "Create configuration", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Configuration saved and read back");
  expect(await page.content()).not.toContain(credential);
  await panel.getByRole("button", { name: "Edit Synthetic CRUD", exact: true }).click();
  await panel.getByLabel("Connection label").fill("Synthetic CRUD revised");
  await panel.getByRole("button", { name: "Review connection update", exact: true }).click();
  await panel.getByRole("button", { name: "Confirm update", exact: true }).click();
  await expect(panel.getByRole("button", { name: "Edit Synthetic CRUD revised", exact: true })).toBeVisible();
  await checkpoint(page, info, "connection-readback");
  await panel.getByRole("button", { name: "Delete Synthetic CRUD revised", exact: true }).click();
  await panel.getByRole("button", { name: "Confirm delete", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Local configuration deleted and absence verified");
  const collection = z.object({ connections: z.array(z.object({ connection_id: z.string() })) }).parse(core.rows.filter(row => row.method === "GET" && row.path === prefix + path).at(-1)?.response);
  expect(collection.connections.some(row => row.connection_id === current)).toBe(false);
  expect(new Set(ifMatch).size).toBe(3);
  expect(core.rows.filter(row => ["POST", "PATCH", "DELETE"].includes(row.method)).map(row => row.method)).toEqual(["POST", "PATCH", "DELETE"]);
  await panel.getByRole("status").scrollIntoViewIfNeeded();
  await expect(panel.getByRole("status")).toBeInViewport({ ratio: 1 });
  await checkpoint(page, info, "connection-deleted");
  await core.finish();
  await declaredReticle(info, [{ kind: "net", method: "POST", urlContains: "/v1/services/connections", count: 1 }, { kind: "net", method: "PATCH", count: 1 }, { kind: "net", method: "DELETE", count: 1 }, { kind: "text", scope: '[aria-label="Service connection setup"]', contains: "Local configuration deleted and absence verified", visible: true }]);
});

test("published history leases reach mounted backtest and immutable evidence", async ({ page, syntheticApi }, info) => {
  const core = await setup(page, syntheticApi, info);
  const { snapshot_id } = core.bootstrap;
  let dataset = "", lease = "", trial = "", experiment = "";
  const leases: string[] = [];
  // One initial catalogue and exactly one fresh Activity-return catalogue.
  core.register("GET", "/api/v1/data/datasets", 2, undefined, row => {
    const catalogue = z.object({ data: z.object({ datasets: z.array(z.object({ dataset_id: z.string(), source_kind: z.string(), snapshot_id: z.string().optional(), status: z.string() })) }) }).parse(row.response);
    dataset = catalogue.data.datasets.find(item => item.snapshot_id === snapshot_id)!.dataset_id;
    expect(catalogue.data.datasets.filter(item => item.source_kind === "native").every(item => item.status === "unavailable")).toBe(true);
  });
  core.register("GET", (prefix ? "" : "/ft-api") + "/v1/historify/watchlist", { minimum: 0, maximum: 2 });
  core.register("GET", "/v1/historify/snapshots/" + snapshot_id);
  core.register("POST", "/api/v1/data/leases", 2, request => { expect(request.postDataJSON()).toEqual({ dataset_id: dataset }); }, row => {
    expect(row.status).toBe(201);
    lease = z.object({ data: z.object({ lease_id: z.string() }) }).parse(row.response).data.lease_id;
    expect(leases).not.toContain(lease); leases.push(lease);
    core.registerRead("/api/v1/data/leases/" + lease, 2);
    core.register("DELETE", "/api/v1/data/leases/" + lease, 1, request => { expect(request.postData()).toBeNull(); });
  });
  core.register("GET", "/api/v1/backtest/strategies", { minimum: 0, maximum: 2 });
  core.register("POST", "/api/v1/backtest/run", 1, request => {
    expect(request.postDataJSON()).toEqual({ data_manifest_id: snapshot_id, symbol: "test-equity", exchange: "XNAS", interval: "1m", strategy: "EMACrossover", initial_capital: 100000, position_size_pct: 10, start_date: "", end_date: "" });
  }, row => {
    // The returned identities must come from response headers, not UI state.
    expect(row.status).toBe(200);
    trial = row.trial ?? ""; experiment = row.experiment ?? "";
    expect.soft(trial).toBeTruthy(); expect.soft(experiment).toBeTruthy();
    if (trial && experiment) {
      core.register("GET", "/api/v1/backtest/trials/" + trial);
      core.register("GET", "/api/v1/backtest/experiments/" + experiment);
    }
  });
  await page.goto("/settings#dataPaths");
  const controls = page.getByRole("region", { name: "Canonical datasets and leases", exact: true });
  await expect(controls.getByRole("button", { name: /^Acquire history:/ })).toBeEnabled();
  await controls.getByLabel("Immutable history snapshot ID").fill(snapshot_id);
  await controls.getByRole("button", { name: "Inspect exact manifest", exact: true }).click();
  await expect(controls.getByLabel("Exact immutable manifest")).toContainText(snapshot_id);
  await controls.getByRole("button", { name: "Acquire " + dataset, exact: true }).click();
  await expect(controls.getByRole("button", { name: "Read full snapshot", exact: true })).toBeVisible();
  await controls.getByRole("button", { name: "Read full snapshot", exact: true }).click();
  await expect.poll(() => core.rows.filter(row => row.method === "GET" && row.path.endsWith("/leases/" + lease)).length).toBe(2);
  await checkpoint(page, info, "history-lease");
  await syntheticApi.retireRead(prefix + "/api/v1/data/leases/" + lease);
  core.registerRead("/api/v1/data/leases/" + lease, 1, true);
  await controls.getByRole("button", { name: "Release exact lease", exact: true }).click();
  await expect(controls.getByRole("status")).toHaveText("Release confirmed by exact readback.");
  const finalLeaseRead = core.rows.filter(row => row.method === "GET" && row.path.endsWith("/leases/" + lease)).at(-1);
  expect(finalLeaseRead?.status).toBe(404);
  expect(finalLeaseRead?.response).toMatchObject({ code: "dataset_or_lease_retired" });
  const settings = page.getByRole("region", { name: "Settings app", exact: true });
  const retainedControls = await controls.elementHandle();
  expect(retainedControls).not.toBeNull();
  const draft = "unsubmitted-snapshot-draft";
  await controls.getByLabel("Immutable history snapshot ID").fill(draft);
  const retainedInput = await controls.getByLabel("Immutable history snapshot ID").elementHandle();
  expect(retainedInput).not.toBeNull();
  // Read-only actual fibers and client props, including production-minified
  // components. IDs normalise alternate pairs; no hooks, stores, refs or app
  // functions are replaced. The JSHandle owns only the observation bookkeeping.
  const lifetime = await page.evaluateHandle(() => {
    interface Client { current(): boolean; viewRevision(): number; pendingLeaseIds(): string[]; fence: unknown }
    interface Fiber { type: unknown; return: Fiber | null; alternate: Fiber | null; memoizedProps: { client?: Client; generation?: number } | null }
    const ids = new WeakMap<object, number>();
    const clients: Client[] = [];
    let nextId = 0;
    function lineage(element: Element | null) {
      const key = element && Object.keys(element).find(name => name.startsWith("__reactFiber$"));
      let fiber = key ? (element as unknown as Record<string, Fiber>)[key] : null;
      const result: { instance: number; name: string; clientGeneration: number | null }[] = [];
      while (fiber) {
        if (typeof fiber.type === "function") {
          let id = ids.get(fiber) ?? (fiber.alternate ? ids.get(fiber.alternate) : undefined);
          if (id === undefined) id = ++nextId;
          ids.set(fiber, id);
          if (fiber.alternate) ids.set(fiber.alternate, id);
          for (const version of [fiber, fiber.alternate]) {
            const client = version?.memoizedProps?.client;
            if (client && typeof client.current === "function" && !clients.includes(client)) clients.push(client);
          }
          result.push({ instance: id, name: fiber.type.name, clientGeneration: fiber.memoizedProps?.generation ?? null });
        }
        fiber = fiber.return;
      }
      return result;
    }
    return { observe() {
      const controls = document.querySelector('[aria-label="Canonical datasets and leases"]');
      const input = controls?.querySelector("input") ?? null;
      const controlsLineage = lineage(controls);
      const inputLineage = lineage(input);
      return {
        url: location.pathname + location.hash,
        section: document.querySelector('section[aria-label="Settings"] [role="tabpanel"]')?.id ?? null,
        controlsLineage, inputLineage, draft: input?.value ?? null,
        clients: clients.map((client, index) => ({ instance: index + 1, current: client.current(), revision: client.viewRevision(), leases: client.pendingLeaseIds(), scope: client.fence })),
      };
    } };
  });
  const beforeLifetime = await lifetime.evaluate(observer => observer.observe());
  const firstClient = beforeLifetime.clients.find(client => client.current);
  expect(firstClient).toBeDefined();
  expect(beforeLifetime.section).toBe("settings-tabpanel-dataPaths");
  expect(beforeLifetime.inputLineage.length).toBeGreaterThan(beforeLifetime.controlsLineage.length);
  await settings.getByLabel("Layout name", { exact: true }).fill("Activity retained Settings draft");
  const apps = page.getByRole("navigation", { name: "Apps", exact: true });
  await apps.getByRole("link", { name: "Learn", exact: true }).click();
  await expect(settings).not.toBeVisible();
  expect(await retainedControls!.evaluate(element => element.isConnected)).toBe(true);
  const hiddenLifetime = await lifetime.evaluate(observer => observer.observe());
  expect(hiddenLifetime.clients.every(client => !client.current)).toBe(true);
  expect(await retainedInput!.evaluate(element => element.isConnected)).toBe(true);
  // Restore the exact URL without restoring a layout/preset (which would mask
  // docking loss). Generic /settings retention is independently exercised by
  // the actual BrowserRouter regression, not treated as section replacement.
  await page.goBack();
  await expect(page).toHaveURL(/\/settings#dataPaths$/);
  await expect(settings).toBeVisible();
  await expect(settings.getByLabel("Layout name", { exact: true })).toHaveValue("Activity retained Settings draft");
  const retainedSettingsNode = await controls.evaluate((element, previous) => element === previous, retainedControls);
  expect.soft(retainedSettingsNode, "Actual Activity return must not remount canonical controls").toBe(true);
  await expect.poll(() => core.rows.filter(row => row.method === "GET" && row.path === prefix + "/api/v1/data/datasets").length).toBe(2);
  await expect(controls.getByRole("button", { name: "Acquire " + dataset, exact: true })).toBeEnabled();
  const returnedLifetime = await lifetime.evaluate(observer => observer.observe());
  const retainedInnerNode = await controls.getByLabel("Immutable history snapshot ID").evaluate((element, previous) => element === previous, retainedInput);
  expect.soft(retainedInnerNode, "The actual DataView input must survive transport retirement").toBe(true);
  await expect(controls.getByLabel("Immutable history snapshot ID")).toHaveValue(draft);
  const instances = (rows: typeof beforeLifetime.inputLineage) => rows.map(row => row.instance);
  expect.soft(instances(returnedLifetime.controlsLineage)).toEqual(instances(beforeLifetime.controlsLineage));
  expect.soft(instances(returnedLifetime.inputLineage)).toEqual(instances(beforeLifetime.inputLineage));
  expect.soft(instances(hiddenLifetime.inputLineage)).toEqual(instances(beforeLifetime.inputLineage));
  expect(returnedLifetime.section).toBe(beforeLifetime.section);
  expect(returnedLifetime.clients.find(client => client.instance === firstClient!.instance)).toMatchObject({ current: false });
  const freshClient = returnedLifetime.clients.find(client => client.current);
  expect(freshClient).toBeDefined();
  expect(freshClient!.instance).not.toBe(firstClient!.instance);
  expect(freshClient!.scope).toEqual(firstClient!.scope);
  expect(freshClient!.leases).toEqual([]);
  expect(firstClient!.leases).toEqual([]);
  await expect(controls.getByText(/^Lease: /)).toHaveCount(0);
  await expect(controls.getByLabel("Exact immutable manifest")).toHaveCount(0);
  await expect(controls.getByText("Release confirmed by exact readback.", { exact: true })).toHaveCount(0);
  await fs.writeFile(info.outputPath("activity-component-lifetime.json"), JSON.stringify({ before: beforeLifetime, hidden: hiddenLifetime, returned: returnedLifetime, retainedSettingsNode, retainedInnerNode }, null, 2));
  await controls.getByLabel("Immutable history snapshot ID").evaluate(element => element.scrollIntoView({ block: "center" }));
  await expect(controls.getByLabel("Immutable history snapshot ID")).toBeInViewport({ ratio: 1 });
  await checkpoint(page, info, "history-activity-retained-inner-draft");
  expect(leases).toHaveLength(1); // returning never silently reacquires
  await controls.getByRole("button", { name: "Acquire " + dataset, exact: true }).click();
  await expect(controls.getByRole("button", { name: "Read full snapshot", exact: true })).toBeVisible();
  await controls.getByRole("button", { name: "Read full snapshot", exact: true }).click();
  await expect.poll(() => core.rows.filter(row => row.method === "GET" && row.path.endsWith("/leases/" + lease)).length).toBe(2);
  await checkpoint(page, info, "history-activity-fresh-lease");
  await syntheticApi.retireRead(prefix + "/api/v1/data/leases/" + lease);
  core.registerRead("/api/v1/data/leases/" + lease, 1, true);
  await controls.getByRole("button", { name: "Release exact lease", exact: true }).click();
  await expect(controls.getByRole("status")).toHaveText("Release confirmed by exact readback.");
  for (const id of leases) {
    const exact = core.rows.filter(row => row.path === prefix + "/api/v1/data/leases/" + id);
    expect(exact.map(row => [row.method, row.status])).toEqual([["GET", 200], ["GET", 200], ["DELETE", 200], ["GET", 404]]);
    expect(exact.at(-1)?.response).toMatchObject({ code: "dataset_or_lease_retired" });
  }
  await fs.writeFile(info.outputPath("activity-lease-identities.json"), JSON.stringify({ leases, retainedSettingsNode, retainedInnerNode, retainedDraft: await controls.getByLabel("Immutable history snapshot ID").inputValue(), catalogueReads: 2 }, null, 2));
  const afterSecondLifetime = await lifetime.evaluate(observer => observer.observe());
  expect(afterSecondLifetime.clients.find(client => client.instance === firstClient!.instance)).toMatchObject({ current: false, leases: [] });
  await fs.writeFile(info.outputPath("activity-after-second-release.json"), JSON.stringify(afterSecondLifetime, null, 2));
  await lifetime.dispose();
  await retainedInput!.dispose();
  await controls.getByRole("status").evaluate(element => element.scrollIntoView({ block: "center" }));
  await checkpoint(page, info, "history-activity-release-readback");
  const leasePredicates = [
    { kind: "net", method: "GET", urlContains: "/api/v1/data/datasets", status: 200, count: 2 },
    { kind: "net", method: "POST", urlContains: "/api/v1/data/leases", status: 201, count: 2 },
    ...leases.flatMap(id => [
      { kind: "net", method: "GET", urlContains: "/api/v1/data/leases/" + id, status: 200, count: 2 },
      { kind: "net", method: "DELETE", urlContains: "/api/v1/data/leases/" + id, status: 200, count: 1 },
      { kind: "net", method: "GET", urlContains: "/api/v1/data/leases/" + id, status: 404, count: 1 },
    ]),
    { kind: "state", store: "mode", path: "mode", equals: "practice" },
  ];
  await declaredReticle(info, [...leasePredicates, { kind: "text", scope: '[aria-label="Canonical datasets and leases"]', contains: "Release confirmed by exact readback.", visible: true }], "history-lease-reticle");
  await page.getByRole("navigation", { name: "Apps", exact: true }).getByRole("link", { name: "Testing", exact: true }).click();
  await page.getByRole("tab", { name: "Experiment evidence", exact: true }).click();
  for (const [label, value] of Object.entries({ "History manifest ID": snapshot_id, "History instrument": "test-equity", "History venue": "XNAS", "History interval": "1m", "Backtest strategy": "EMACrossover" })) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Run immutable backtest", exact: true }).click();
  await expect(page.getByLabel("Exact core evidence")).toContainText('"completed"');
  await page.getByRole("button", { name: "Read experiment " + experiment, exact: true }).click();
  await expect(page.getByLabel("Exact core evidence")).toContainText(snapshot_id);
  await page.getByLabel("Exact core evidence").scrollIntoViewIfNeeded();
  await checkpoint(page, info, "backtest-immutable-evidence");
  await core.finish();
  await declaredReticle(info, [...leasePredicates,
    { kind: "net", method: "POST", urlContains: "/api/v1/backtest/run", status: 200, count: 1 },
    { kind: "text", scope: '[aria-label="Exact core evidence"]', contains: snapshot_id, visible: true },
  ]);
});

test("nine actual app mounts retain layout and context with honest System and local help", async ({ page, syntheticApi }, info) => {
  const core = await setup(page, syntheticApi, info);
  for (const path of ["/v1/sandbox/holdings", "/v1/sandbox/orders", "/v1/sandbox/trades", "/api/v1/data/portfolio/evidence", "/api/v1/backtest/strategies", "/api/v1/backtest/strategies/running", "/api/v1/backtest/strategies/uploaded", "/api/v1/cron/jobs", "/api/v1/safety/config", "/api/v1/native/brokers", "/api/v1/broker-mcp/catalogue"]) core.register("GET", path, { minimum: 0, maximum: 4 });
  // Mount the common shell independently of the lazy chart. Each actual
  // mount/Activity return owns its completed reads and bounded abort, never
  // one cancellation allowance shared across unrelated lifetimes.
  await page.goto("/learn");
  await core.retireNative(nativeShellReads);
  core.nativePhase("first Terminal chart mount", nativeTerminalReads);
  await page.getByRole("navigation", { name: "Apps", exact: true }).getByRole("link", { name: "Terminal", exact: true }).click();
  const terminal = page.getByRole("region", { name: "Terminal app", exact: true });
  await expect(terminal).toBeVisible();
  await terminal.getByLabel("Layout name", { exact: true }).fill("Synthetic retained layout");
  await terminal.getByRole("button", { name: "Save layout", exact: true }).click();
  await expect(terminal.getByRole("status").filter({ hasText: "Saved Synthetic retained layout" })).toBeVisible();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("flinttrade:app-layouts:v1:terminal")!)["Synthetic retained layout"]);
  await terminal.getByLabel("Layout name", { exact: true }).fill("Unsubmitted retained draft");
  await terminal.getByTestId("instrument-links").locator("summary").click();
  await terminal.getByLabel("Instrument link channel").selectOption("fdc3.channel.red");
  await terminal.getByLabel("Linked symbol").fill("SYNTHETIC");
  await terminal.getByLabel("Linked venue").fill("XNAS");
  await terminal.getByRole("button", { name: "Broadcast selection", exact: true }).click();
  await expect(terminal.getByTestId("instrument-links")).toContainText("Selection broadcast; execution unchanged");
  await terminal.getByTestId("instrument-links").locator("summary").click();
  const mode = await page.evaluate(() => localStorage.getItem("flinttrade:mode"));
  const apps = page.getByRole("navigation", { name: "Apps", exact: true });
  await core.retireNative(nativeTerminalReads);
  for (const name of ["Testing", "Portfolio", "Automation", "Reports", "Learn", "Brokers", "Settings", "System"]) {
    await apps.getByRole("link", { name, exact: true }).click();
    await expect(page).toHaveURL(new RegExp("/" + name.toLowerCase() + "$"));
    await expect(page.getByRole("region", { name: name + " app", exact: true })).toBeVisible();
    if (name === "System") await expect(page.getByRole("region", { name: "Resources", exact: true })).toBeVisible();
    await checkpoint(page, info, "app-" + name.toLowerCase());
  }
  await expect(page.getByTestId("system-status-bar")).toContainText("GPU: Unavailable");
  await expect(page.getByTestId("system-status-bar")).toContainText("Browser RTT: Unmeasured");
  await page.getByRole("button", { name: "Ask AI", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Local help · not an AI response");
  await checkpoint(page, info, "local-no-model-help");
  await page.keyboard.press("Escape");
  core.nativePhase("Terminal Activity return", nativeTerminalReads);
  await apps.getByRole("link", { name: "Terminal", exact: true }).click();
  await expect(terminal).toBeVisible();
  await expect(terminal.getByLabel("Layout name", { exact: true })).toHaveValue("Unsubmitted retained draft");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("flinttrade:app-layouts:v1:terminal")!)["Synthetic retained layout"])).toEqual(saved);
  expect(await page.evaluate(() => localStorage.getItem("flinttrade:mode"))).toBe(mode);
  await checkpoint(page, info, "terminal-return-wide");
  await page.setViewportSize({ width: 600, height: 760 });
  await checkpoint(page, info, "terminal-return-compact");
  await core.retireNative(nativeTerminalReads);
  expect(core.rows.filter(row => row.method !== "GET")).toEqual([]);
  await core.finish();
  await declaredReticle(info, [{ kind: "net", method: "POST", count: 0 }, { kind: "state", store: "mode", path: "mode", equals: "practice" }, { kind: "text", scope: '[data-testid="system-status-bar"]', contains: "GPU: Unavailable", visible: true }]);
});

test("learning and training actions refuse without fabricated authority", async ({ page, syntheticApi }, info) => {
  const core = await setup(page, syntheticApi, info);
  core.register("POST", "/v1/learning/permissions/preview", 1, request => { expect(request.postDataJSON()).toEqual({}); });
  core.register("GET", "/api/v1/backtest/strategies", { minimum: 0, maximum: 2 });
  const training = { request_id: "synthetic-refused-training", payload: { model_name: "synthetic-not-a-model", training_type: "sft", format_type: "chatml", hf_dataset: "synthetic/dataset" }, lineage: { dataset: "a".repeat(64), run_id: "synthetic-unowned-run" } };
  core.register("POST", "/api/v1/backtest/training/jobs", 1, request => { expect(request.postDataJSON()).toEqual(training); });
  await page.goto("/settings");
  await addWidget(page, "Learning permissions");
  await page.getByLabel("Complete learning proposal JSON").fill("{}");
  await page.getByRole("button", { name: "Preview exact permission", exact: true }).click();
  await expect(page.getByRole("region", { name: "Learning permissions", exact: true }).getByRole("alert")).toContainText("invalid_request");
  const learning = core.rows.find(row => row.path.endsWith("/permissions/preview"));
  expect(learning?.status).toBe(400); expect(learning?.response).toEqual({ error: "invalid_request" });
  await checkpoint(page, info, "learning-refused");
  await page.getByRole("navigation", { name: "Apps", exact: true }).getByRole("link", { name: "Testing", exact: true }).click();
  await expect(page).toHaveURL(/\/testing$/);
  await page.getByRole("region", { name: "Testing app", exact: true }).getByRole("tab", { name: "Experiment evidence", exact: true }).click();
  for (const [label, value] of Object.entries({ "Training request ID": training.request_id, "Training model": training.payload.model_name, "Training method": training.payload.training_type, "Training format": training.payload.format_type, "Registered remote dataset": training.payload.hf_dataset, "Immutable batch ID": training.lineage.dataset, "Training run ID": training.lineage.run_id })) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Submit prepared training", exact: true }).click();
  await page.getByRole("button", { name: "Confirm action", exact: true }).click();
  await expect(page.getByRole("region", { name: "Testing app", exact: true }).getByRole("alert")).toBeVisible();
  const refused = core.rows.find(row => row.path.endsWith("/training/jobs"));
  expect(refused?.status).toBe(403); expect(refused?.response).toMatchObject({ code: "run_not_owned" });
  await checkpoint(page, info, "training-refused");
  expect(core.rows.filter(row => row.method === "POST")).toHaveLength(2);
  await core.finish();
  await declaredReticle(info, [{ kind: "net", method: "POST", urlContains: "/permissions/preview", status: 400, count: 1 }, { kind: "net", method: "POST", urlContains: "/training/jobs", status: 403, count: 1 }, { kind: "text", scope: '[aria-label="Testing app"]', contains: "run_not_owned", visible: true }]);
});
