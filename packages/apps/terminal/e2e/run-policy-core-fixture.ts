import { fileURLToPath } from "node:url";
import fs from "node:fs/promises";
import { createWriteStream } from "node:fs";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { createHash } from "node:crypto";
import { request as ownedRequest, type Page, type Request, type TestInfo } from "@playwright/test";
import { z } from "zod";
import { test as guardedTest, expect, type HttpMethod, type SyntheticPhasedFixtureRegistry } from "./fixture-registry";
import { EDGE_PROBE_URLS, PUBLIC_INTERNET_PROBE_URL } from "../src/lib/operatorProbeUrls";
import { exactAcknowledgementCorruption } from "./run-policy-negative-seams";

// This journey requires an owned, OS-isolated normal-factory core. It does not
// supply application API responses or claim provider/native qualification.
const statePath = process.env["FLINTTRADE_E2E_CORE_STATE"];
if (!statePath) throw new Error("An isolated normal-factory controller must supply FLINTTRADE_E2E_CORE_STATE");
const Bootstrap = z.object({ runs: z.array(z.object({run_id:z.string(), actor:z.string(), account:z.string(), environment:z.literal("paper")})), values: z.record(z.string(), z.record(z.string(), z.unknown())), times:z.object({now:z.string(),end:z.string(),valid_until:z.number()}), selection:z.record(z.string(),z.string()), session: z.object({ token: z.string(), username: z.string(), expiresAt: z.string() }), connection_id: z.string(), snapshot_id: z.string(), baseURL: z.string(), replacement_session: z.object({ token: z.string(), username: z.string(), expiresAt: z.string() }).optional(), preview_session: z.object({ token: z.string(), username: z.string(), expiresAt: z.string() }).optional() });
export const prefix = process.env["R24_STAGE"] === "reticle" ? "/ft-api" : "";
// The real backend lease creates an empty local catalogue, NOT a ready Native
// account. Cutover mutations remain frozen. Broker accounts succeeds on the
// first held flight; timing alone owns its remaining ordinary retry attempts.
const nativeShellReads = 3;
const nativeReadBudget = (_title: string) => nativeShellReads;
const backendReplacements = new Map<string, () => Promise<void>>();
export const test = guardedTest.extend<{ coreLifetime: void }>({
  coreLifetime: [async ({ syntheticApi, context }, use, info) => {
    const port = process.env["R24_CORE_PORT"];
    if (!port || !["5100", "5173"].includes(port)) throw new Error("Missing owned core port");
    const caseKey = sha(info.testId);
    await fs.rm(statePath!, { force: true });
    const server = fileURLToPath(new URL(info.title.includes("genuine backend replacement") ? "../../../../tools/acceptance/policy/replace-server.py" : "../../../../tools/acceptance/policy/core-server.py", import.meta.url));
    const python = process.env["FLINTTRADE_E2E_PYTHON"];
    if (!python) throw new Error("Maintained acceptance controller must select an explicit Python interpreter");
    const child = spawn(python, [server, "--port", port, "--case-key", caseKey, "--output", info.outputPath("normal-core")], { stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, R46_SCENARIO: info.title } });
    const log = createWriteStream(info.outputPath("normal-core.log"));
    child.stdout.pipe(log, { end: false }); child.stderr.pipe(log, { end: false });
    const lines = createInterface({ input: child.stdout });
    backendReplacements.set(info.testId, async () => {
      if (!info.title.includes("genuine backend replacement")) throw new Error("Backend replacement not declared for this case");
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("Real backend replacement timed out")), 60000);
        const onLine = (line: string) => { if (line === "R62_REPLACEMENT_READY") { clearTimeout(timer); lines.off("line", onLine); resolve(); } };
        lines.on("line", onLine);
        child.stdin.write("REPLACE\n");
      });
    });
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
      try {
        // A hook registered while importing a helper belongs only to that
        // collecting spec file. The test-scoped owner must drain observations
        // for every borrowing file, before retiring its page and HTTP pools.
        const failures: unknown[] = [];
        try { await diagnosticClosers.get(info.testId)?.(); } catch (error) { failures.push(error); }
        finally { diagnosticClosers.delete(info.testId); }
        try { await syntheticApi.dispose(); } catch (error) { failures.push(error); }
        try { await networkFinalizers.get(info.testId)?.(); } catch (error) { failures.push(error); }
        finally { networkFinalizers.delete(info.testId); }
        if (failures.length) throw new AggregateError(failures, "Owned diagnostics or registry failed");
      }
      finally {
        await relayClosers.get(info.testId)?.();
        relayClosers.delete(info.testId);
        backendReplacements.delete(info.testId);
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
  const allowances: {text: string; url: string; expectedCalls: number}[] = [];
  if(info.title.includes("preview-auth scoped backtest")) {
    for (const [path, expectedCalls] of [["/api/v1/backtest/run",1],["/api/v1/native/accounts",1],["/api/v1/advisor/status",1],["/api/v1/system/diagnostics",1],["/v1/sandbox/funds",1],["/v1/config/llm",1],["/v1/sandbox/positions",1]] as const) {
      allowances.push({text:"Failed to load resource: the server responded with a status of 401 (Unauthorized)",url:"http://127.0.0.1:5173"+prefix+path,expectedCalls});
    }
  }
  if(info.title.includes("protection requires canonical owned entry")) allowances.push({text:"Failed to load resource: the server responded with a status of 403 (Forbidden)",url:"http://127.0.0.1:5173"+prefix+"/api/v1/protection/grants",expectedCalls:1});
  if(info.title.includes("custody unavailable")) allowances.push({text:"Failed to load resource: the server responded with a status of 503 (Service Unavailable)",url:"http://127.0.0.1:5173"+prefix+"/api/v1/protection/grants/r46-paper-a",expectedCalls:1});
  if(info.title.includes("mismatched reviewed") || info.title.includes("binding refusal")) allowances.push({text:"Failed to load resource: the server responded with a status of 400 (Bad Request)",url:"http://127.0.0.1:5173"+prefix+"/v1/model-runs/r46-paper-a/configuration/preview",expectedCalls:1});
  if (info.title.startsWith("learning and training")) {
    allowances.push({ text: "Failed to load resource: the server responded with a status of 400 (Bad Request)", url: "http://127.0.0.1:5173" + prefix + "/v1/learning/permissions/preview", expectedCalls: 1 });
    allowances.push({ text: "Failed to load resource: the server responded with a status of 403 (Forbidden)", url: "http://127.0.0.1:5173" + prefix + "/api/v1/backtest/training/jobs", expectedCalls: 1 });
  }
  await use(allowances);
} });
export const sha = (value: string) => createHash("sha256").update(value).digest("hex");
const diagnosticClosers = new Map<string, () => Promise<void>>();
const networkFinalizers = new Map<string, () => Promise<void>>();
const relayClosers = new Map<string, () => Promise<void>>();
interface QueryObservation { key: unknown; status: string; fetchStatus: string; failures: number; observers: number; error: string }
interface DiscoveryObservation {
  events: { id: number; borrowersBefore: number; stopped: boolean; aborted: boolean; stack: string }[];
  locations: unknown[]; errors: string[];
  flights(): Promise<{ id: number; borrowers: number; stopped: boolean; aborted: boolean }[]>;
  queries(): Promise<QueryObservation[]>;
}
const discoveryProbes = new WeakMap<Page, DiscoveryObservation>();
const timingObservers = new WeakMap<Page, (label: string) => Promise<void>>();
export async function observePolicyTiming(page: Page, label: string) {
  await timingObservers.get(page)?.(label);
}
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

interface Row { method: string; path: string; body: unknown; status: number; response: unknown; etag: string | undefined; bodySha256: string; responseSha256: string; trial: string | undefined; experiment: string | undefined }
function safe(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safe);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, /^(?:credential|authorization|token|password|api_key)$/i.test(key) ? "<redacted-synthetic>" : safe(child)]));
  return value;
}
export async function setup(page: Page, registry: SyntheticPhasedFixtureRegistry, info: TestInfo, mode: "live" | "practice" = "practice") {
  const bootstrap = Bootstrap.parse(JSON.parse(await fs.readFile(statePath!, "utf8")));
  let activeToken = bootstrap.session.token;
  const transport = await ownedRequest.newContext();
  relayClosers.set(info.testId, () => transport.dispose());
  const rows: Row[] = [];
  let writing = Promise.resolve();
  const consoleRows: unknown[] = [];
  const initiators: unknown[] = [];
  const browserBodies: { method: string; path: string; status: number; bodySha256: string; completed: boolean; responseSha256?: string; error?: string }[] = [];
  const bodyReads: Promise<void>[] = [];
  const registered: { method: HttpMethod; path: string; expected: unknown }[] = [];
  const faults: ReturnType<typeof exactAcknowledgementCorruption>[] = [];
  const loadedScripts = new Set<string>();
  const timing: unknown[] = [];
  timingObservers.set(page, async label => {
    timing.push({ label, hostTime: Date.now(), browser: await page.evaluate(() => ({ time: Date.now(), performance: performance.now() })), queries: await querySnapshot(page) });
    await fs.writeFile(info.outputPath("policy-timing.json"), JSON.stringify(timing, null, 2));
  });
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
  cdp.on("Debugger.scriptParsed", event => loadedScripts.add(event.url));
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
    if (/\/api\/v1\/(native\/accounts|safety\/config)/.test(event.request.url)) initiators.push({ event: "request", id: event.requestId, url: event.request.url, method: event.request.method, timestamp: event.timestamp, wallTime: event.wallTime, hostTime: Date.now(), initiator: event.initiator });
  });
  cdp.on("Network.loadingFailed", event => { initiators.push({ event: "failed", ...event }); });
  diagnosticClosers.set(info.testId, async () => {
    await fs.writeFile(info.outputPath("registry-counts.json"), JSON.stringify(registered.map(row => ({ ...row, calls: registry.callCount(row.method, row.path), ...(row.method === "GET" ? { reads: registry.readCounts(row.path) } : {}) })), null, 2));
    await fs.writeFile(info.outputPath("query-cache-final.json"), JSON.stringify(await querySnapshot(page), null, 2));
    await fs.writeFile(info.outputPath("discovery-observation.json"), JSON.stringify({ events: discovery.events, locations: discovery.locations, errors: discovery.errors, held: heldDiscoveries, flights: page.isClosed() ? [] : await discovery.flights() }, null, 2));
    expect.soft(discovery.errors).toEqual([]);
    for (const fault of faults) fault.assertUsed();
    const clientPath = process.env["FLINTTRADE_E2E_RETICLE_CLIENT"];
    if (clientPath && info.title.startsWith("learning and training")) {
      const module: { connectReticle(path: string): Promise<{ call(name: string, args: Record<string, unknown>): Promise<unknown>; close(): void }> } = await import(clientPath);
      const client = await module.connectReticle(info.outputPath("refusal-diagnostic-transcript.json"));
      try {
        const events = await client.call("reticle_observe", { action: "events", since: 0, filters: ["net", "signal"], max_events: 2000 });
        await fs.writeFile(info.outputPath("refusal-diagnostic-events.json"), JSON.stringify(events, null, 2));
      } finally { client.close(); }
    }
    timingObservers.delete(page);
    // Keep response/requestfailed/CDP observers through the guarded page close.
    // A periodic ping can begin while the live QueryCache is being captured.
    // The registry still owns and drains it; final bytes must include that tail.
  });
  networkFinalizers.set(info.testId, async () => {
    expect(page.isClosed()).toBe(true);
    await writing;
    await Promise.all(bodyReads);
    await fs.writeFile(info.outputPath("browser-completed-bodies.json"), JSON.stringify(browserBodies, null, 2));
    await fs.writeFile(info.outputPath("browser-console.json"), JSON.stringify(consoleRows, null, 2));
    await fs.writeFile(info.outputPath("read-initiators.json"), JSON.stringify(initiators, null, 2));
    await fs.writeFile(info.outputPath("network-capture-closed.json"), JSON.stringify({pageClosed:page.isClosed(),bodyObservations:browserBodies.length,relayRows:rows.length,registryCountsPhase:"before guarded disposal; unchanged registry asserts all settled obligations during disposal"},null,2));
  });
  page.on("console", message => { consoleRows.push({ type: message.type(), text: message.text(), location: message.location() }); });
  page.on("requestfailed", request => { consoleRows.push({ method: request.method(), url: request.url(), failure: request.failure() }); });
  async function relay(request: Request): Promise<{ status: number; headers: Record<string, string>; body: string; row: Row }> {
    const url = new URL(request.url());
    expect(url.origin).toBe("http://127.0.0.1:5173");
    const auth = request.headers()["authorization"];
    if (auth !== undefined) expect(auth).toBe("Bearer " + activeToken);
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
  function register(method: HttpMethod, path: string, calls: number | { minimum: number; maximum: number } = 1, validate?: (request: Request) => void, observed?: (row: Row) => void | Promise<void>) {
    registered.push({ method, path: prefix + path, expected: calls });
    registry.register({ name: `${method} ${path}`, method, path: prefix + path, expectedCalls: calls, handler: async request => { validate?.(request); const response = await relay(request); await observed?.(response.row); return response; } });
  }
  function registerRead(path: string, calls: number, expectedNotFound?: true, observed?: (row: Row) => void | Promise<void>) {
    registered.push({ method: "GET", path: prefix + path, expected: { calls, phase: "required", expectedNotFound } });
    registry.register({ name: `required GET ${path}`, method: "GET", path: prefix + path, expectedCalls: calls, readPhase: "required", expectedNotFound, handler: async request => { const response = await relay(request); await observed?.(response.row); return response; } });
  }
  for (const path of ["/v1/auth/status", "/health", "/api/v1/ping", "/api/v1/advisor/status", "/api/v1/instrument-lots", "/api/v1/system/diagnostics", "/v1/config/llm", "/v1/sandbox/funds", "/v1/sandbox/positions", "/v1/sandbox/status"]) {
    register("GET", path, { minimum: 0, maximum: 8 });
  }
  function registerCorruptedAck(path: string, validate: (request: Request) => void) {
    const fault = exactAcknowledgementCorruption(path);
    faults.push(fault);
    registered.push({ method: "POST", path: prefix + path, expected: { calls: 1, fault: "exact ACK target corruption" } });
    registry.register({ name: `declared malformed ACK POST ${path}`, method: "POST", path: prefix + path, expectedCalls: 1, handler: async request => {
      validate(request);
      const response = await relay(request);
      const altered = fault.apply(request.method(), new URL(request.url()).pathname.slice(prefix.length), response.status, response.body);
      await fs.writeFile(info.outputPath("malformed-ack-original.txt"), response.body);
      await fs.writeFile(info.outputPath("malformed-ack-browser.txt"), altered);
      await fs.writeFile(info.outputPath("malformed-ack-fault.json"), JSON.stringify({ method: "POST", path, count: 1, originalSha256: sha(response.body), alteredSha256: sha(altered), fault: "scope.run_id replaced; original core write unchanged" }, null, 2));
      return { ...response, headers: { ...response.headers, "content-length": String(Buffer.byteLength(altered)) }, body: altered };
    } });
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
      const target = terminalPhase ? (registry.readCounts(nativePath).completed === nativeBaseline ? 3 : 1) : (releasedFlights.size === 0 ? 2 : 1);
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
          .toEqual(releasedFlights.size === 0 ? [["pending", "fetching", 0], ["pending", "fetching", 0]] : [["success", "idle", 0], ["pending", "fetching", releasedFlights.size]]);
        releasedFlights.add(flight!.id);
      }
      heldDiscoveries.push({ phase: name, target, flight, browserFailureBeforeRelease: request.failure(), queries, responseSha256: response.row.responseSha256 });
      return response;
    } });
  }
  async function retireNative(completed: number) {
    await expect.poll(() => registry.readCounts(nativePath).completed, { intervals: [10] }).toBe(nativeBaseline + completed);
    await expect.poll(async () => shellQueries(await querySnapshot(page))
      .map(query => [query.status, query.fetchStatus, query.failures, query.error]), { intervals: [10] }).toEqual([
      ["success", "idle", 0, "null"],
      ["error", "idle", 3, "Error: A connected native broker account is required for market/timings."],
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
  await page.addInitScript(({ session, mode }) => {
    sessionStorage.setItem("flinttrade:auth-session", JSON.stringify(session));
    localStorage.setItem("flinttrade:mode", JSON.stringify({ state: { mode }, version: 2 }));
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  }, { session: bootstrap.session, mode });
  async function finish() {
    if (nativeBaseline === 0) await retireNative(nativeShellReads);
    expect(discovery.errors).toEqual([]);
    expect(discovery.locations).toHaveLength(1);
    await expect.poll(() => registry.readCounts(prefix + "/api/v1/native/accounts").completed).toBe(nativeReadBudget(info.title));
    expect(rows.filter(row => row.path === prefix + "/api/v1/native/accounts").every(row => row.status === 200 && JSON.stringify(row.response) === '{"data":{"accounts":[]},"status":"success"}')).toBe(true);
    // Keep startup running normally, but hand it off promptly after its actual
    // completed retries, rather than near the next independent heartbeat.
    // Pause against observed browser time. Legacy callers then pause at host
    // time, so align only the wall clock while paused; timer ticks do not move.
    const browserTime = await page.evaluate(() => Date.now());
    await page.clock.pauseAt(browserTime + 100);
    const hostTime = Date.now();
    await page.clock.setSystemTime(hostTime);
    await fs.writeFile(info.outputPath("startup-clock.json"), JSON.stringify({ browserTime, pausedTime: browserTime + 100, hostTime, clockTime: await page.evaluate(() => Date.now()) }, null, 2));
  }
  async function completedBodies(method: HttpMethod, path: string, count: number) {
    await expect.poll(() => browserBodies.filter(row => row.method === method && row.path === prefix + path && row.completed).length,
      { message: `Real completed ${method} ${path} bodies before rendering notifications` }).toBe(count);
  }
  async function replaceAuth(kind: "replacement" | "preview") {
    const session = kind === "replacement" ? bootstrap.replacement_session : bootstrap.preview_session;
    if (!session) throw new Error("Real issued replacement session prerequisite missing");
    const modulePath = [...loadedScripts].find(path => /\/assets\/authStore-[^/]+\.js$/.test(path));
    if (!modulePath) throw new Error("Mounted public auth owner not found");
    activeToken = session.token;
    const observation = await page.evaluate(async ({ modulePath, token }) => {
      interface Owner { getState(): { token: string | null; status: string; sessionGeneration: number; updateToken(value: string, generation: number): boolean } }
      const module: Record<string, unknown> = await import(/* @vite-ignore */ modulePath);
      const owners = Object.values(module).filter((value): value is Owner => (typeof value === "function" || typeof value === "object") && value !== null && "getState" in value && typeof value.getState === "function" && "updateToken" in value.getState());
      if (owners.length !== 1) throw new Error("Expected one mounted public auth store");
      const owner = owners[0], before = owner.getState();
      if (before.token === token) throw new Error("Not a genuine session replacement");
      const accepted = before.updateToken(token, before.sessionGeneration);
      const after = owner.getState();
      return { accepted, before: { status: before.status, generation: before.sessionGeneration }, after: { status: after.status, generation: after.sessionGeneration }, newTokenInstalled: after.token === token };
    }, { modulePath, token: session.token });
    expect(observation.accepted).toBe(true);expect(observation.newTokenInstalled).toBe(true);
    expect(observation.after.generation).toBe(observation.before.generation + 1);
    await fs.writeFile(info.outputPath("auth-replacement.json"), JSON.stringify({kind,modulePath,...observation},null,2));
    return observation;
  }
  async function replaceBackend() {
    const replace = backendReplacements.get(info.testId);
    if (!replace) throw new Error("Owned replacement controller missing");
    const before = bootstrap.runs;
    await replace();
    const replacement = Bootstrap.parse(JSON.parse(await fs.readFile(statePath!, "utf8")));
    expect(replacement.runs[0].actor).not.toBe(before[0].actor);
    expect(replacement.session.token).not.toBe(bootstrap.session.token);
    Object.assign(bootstrap, replacement);
    await fs.writeFile(info.outputPath("backend-scope-replacement.json"), JSON.stringify({ before, after: bootstrap.runs },null,2));
  }
  return { bootstrap, register, registerRead, registerCorruptedAck, rows, finish, nativePhase, retireNative, completedBodies, loadedScripts, replaceAuth, replaceBackend, queries: () => querySnapshot(page) };
}
export async function declaredReticle(info: TestInfo, predicates: Record<string, unknown>[], name = "reticle") {
  const clientPath = process.env["FLINTTRADE_E2E_RETICLE_CLIENT"];
  if (!clientPath) return;
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
      { kind: "net", method: "GET", urlContains: "/api/v1/native/accounts", status: 200, count: nativeReadBudget(info.title) }, ...predicates,
    ] };
    const verdict = await client.call("reticle_assert", { predicate, since: 0, timeout_ms: 2000 });
    await fs.writeFile(info.outputPath(name + "-verdict.json"), JSON.stringify({ predicate, verdict }, null, 2));
    // A rejected verdict still fails the case; soft checks only preserve later
    // independent evidence (e.g. actual immutable backtest after lease proof).
    expect.soft(verdict["verified"]).toBe("yes"); expect.soft(verdict["pass"]).toBe(true);
  } finally { client.close(); }
}
export async function checkpoint(page: Page, info: TestInfo, name: string) {
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
export async function addWidget(page: Page, name: string) {
  const route = new URL(page.url()).pathname.split("/").filter(Boolean).at(-1) ?? "terminal";
  const app = route.charAt(0).toUpperCase() + route.slice(1);
  const region = page.getByRole("region", { name: app + " app", exact: true });
  await expect(region).toBeVisible();
  await region.getByRole("button", { name: "Add widget", exact: true }).click();
  await page.getByRole("button", { name: "Add " + name, exact: true }).click();
}


export { expect };
