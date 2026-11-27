import fs from "node:fs/promises";
import { createWriteStream } from "node:fs";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { createHash } from "node:crypto";
import { test, expect, request as ownedRequest, type Request } from "@playwright/test";
import { z } from "zod";
import { createSyntheticFixtureRegistry } from "./fixture-registry";
import { armIncidentProtocol, SYSTEM_INSPECTION_CASE, type IncidentScope, type ProducerRow } from "./incident-delivery-protocol";

const cases = ["positive", "default deny", "unknown id", "foreign channel id", "wrong phase", "wrong case", "wrong server", "wrong pid", "wrong auth generation", "missing authorization", "claim body", "query", "method", "endpoint", "foreign origin", "double claim", "receipt before claim", "wrong claim token", "submitted receipt", "unknown receipt", "extra receipt field", "receipt replay", "retired", "missing claim", "missing receipt", "trading", "account", "model", "config"] as const;
for (const scenario of cases) test("incident protocol " + scenario, async ({ page, context }, info) => {
  const python = process.env["FLINTTRADE_E2E_PYTHON"];
  const server = process.env["FLINTTRADE_E2E_CORE_SERVER"];
  const state = process.env["FLINTTRADE_E2E_CORE_STATE"];
  if (!python || !server || !state) throw new Error("Owned isolated normal Core required");
  const key = createHash("sha256").update(info.testId).digest("hex");
  const child = spawn(python, [server, "--port", "5100", "--case-key", key, "--output", info.outputPath("normal-core")], { stdio: ["pipe", "pipe", "pipe"] });
  const log = createWriteStream(info.outputPath("normal-core.log"));
  child.stdout.pipe(log, { end: false }); child.stderr.pipe(log, { end: false });
  const lines = createInterface({ input: child.stdout });
  const exited = new Promise<number | null>((resolve, reject) => { child.once("error", reject); child.once("close", code => { log.end(); resolve(code); }); });
  const transport = await ownedRequest.newContext();
  try {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("Core readiness timeout")), 30000);
      lines.on("line", line => { if (line === "R24_CORE_READY") { clearTimeout(timer); resolve(); } });
      void exited.then(code => { clearTimeout(timer); reject(new Error("Early core exit " + code)); }, reject);
    });
    const bootstrap = z.object({ baseURL: z.string(), session: z.object({ token: z.string() }) }).parse(JSON.parse(await fs.readFile(state, "utf8")));
    const startup = z.object({ pid: z.number(), case_key: z.literal(key) }).parse(JSON.parse(await fs.readFile(info.outputPath("normal-core/startup.json"), "utf8")));
    const scope: IncidentScope = { caseId: info.testId, title: SYSTEM_INSPECTION_CASE, server: bootstrap.baseURL, pid: startup.pid, auth: "Bearer " + bootstrap.session.token, phase: "system-inspection" };
    let current = { ...scope };
    const native = await transport.get(scope.server + "/api/v1/native/accounts", { headers: { Authorization: scope.auth } }); expect(native.status()).toBe(503);
    const diagnostics = await transport.get(scope.server + "/api/v1/system/diagnostics", { headers: { Authorization: scope.auth } }); expect(diagnostics.status()).toBe(200);
    const ledger = async (): Promise<ProducerRow[]> => JSON.parse(await fs.readFile(info.outputPath("normal-core/core-http-ledger.json"), "utf8"));
    const before = await ledger();
    await page.setExtraHTTPHeaders({ Authorization: scope.auth });
    await page.goto(scope.server + "/health");
    await page.setExtraHTTPHeaders({});
    const registry = await createSyntheticFixtureRegistry(page, { name: info.title, frontendOrigin: scope.server });
    const relay = async (request: Request) => {
      const response = await transport.fetch(request.url(), { method: request.method(), headers: request.headers(), ...(request.postData() === null ? {} : { data: request.postData()! }), maxRedirects: 0 });
      return { status: response.status(), headers: response.headers(), body: await response.text() };
    };
    const options = { registry, origin: scope.server, prefix: "", scope, current: async () => current, diagnosticsWire: await diagnostics.text(), producerLedger: before, expectedNativeReads: 1, relay };
    if (scenario === "positive") {
      // Bind the actual HTTP response to this exact producer exchange, not a
      // generated label or an independently matching operation/count census.
      const nativeRow = before.find(row => row.method === "GET" && row.path === "/api/v1/native/accounts");
      expect(native.headers()["x-diagnostic-request-id"]).toBeTruthy();
      expect(nativeRow).toHaveProperty("diagnostic_request_id", native.headers()["x-diagnostic-request-id"]);
      const producerRows = before.filter(row => row.path === "/api/v1/native/accounts");
      const responseIds = producerRows.map(row => z.object({ diagnostic_request_id: z.string() }).parse(row).diagnostic_request_id);
      const corruptions = [
        { name: "missing", ids: [null, responseIds[1]] },
        { name: "foreign", ids: [diagnostics.headers()["x-diagnostic-request-id"], responseIds[1]] },
        { name: "swapped", ids: [responseIds[1], responseIds[0]] },
        { name: "duplicate", ids: [responseIds[0], responseIds[0]] },
      ];
      for (const corruption of corruptions) {
        const rows = before.map(row => {
          const index = producerRows.indexOf(row);
          return index < 0 ? row : { ...row, diagnostic_request_id: corruption.ids[index] };
        });
        expect(() => armIncidentProtocol({ ...options, producerLedger: rows }), corruption.name).toThrow(/correlation|exchange/);
      }
      // Real producer operands, not a permissive fake API. Each corrupted
      // authority input must fail before registering a single write handler.
      expect(() => armIncidentProtocol({ ...options, scope: { ...scope, title: "foreign case" } })).toThrow("wrong case or phase");
      expect(() => armIncidentProtocol({ ...options, scope: { ...scope, phase: "before System" } })).toThrow("wrong case or phase");
      expect(() => armIncidentProtocol({ ...options, diagnosticsWire: options.diagnosticsWire + " " })).toThrow("same-Core diagnostics bytes");
      expect(() => armIncidentProtocol({ ...options, producerLedger: before.filter(row => row.path !== "/api/v1/native/accounts") })).toThrow("producer census count");
      expect(() => armIncidentProtocol({ ...options, producerLedger: [...before, before.find(row => row.path === "/api/v1/native/accounts")!] })).toThrow("producer census count");
      expect(() => armIncidentProtocol({ ...options, producerLedger: before.map(row => row.path === "/api/v1/native/accounts" ? { ...row, authorization_sha256: "foreign" } : row) })).toThrow("producer auth/status");
      expect(() => armIncidentProtocol({ ...options, expectedNativeReads: 8 })).toThrow("bounded producer reads");
    }
    const protocol = scenario === "default deny" ? undefined : armIncidentProtocol(options);
    const census = z.object({ data: z.object({ operational_events: z.object({ incidents: z.array(z.object({ deliveries: z.array(z.object({ id: z.string(), channel: z.string() })) })) }) }) }).parse(await diagnostics.json());
    const delivery = census.data.operational_events.incidents[0]!.deliveries.find(row => row.channel === "desktop")!;
    const root = "/api/v1/system/incidents/deliveries/";
    const path = root + delivery.id;
    async function send(url: string, body?: string, method = "POST", auth = scope.auth) {
      return page.evaluate(async ({ url, body, method, auth }) => {
        const response = await fetch(url, { method, headers: { ...(auth ? { Authorization: auth } : {}), ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, ...(body === undefined ? {} : { body }) });
        return response.json();
      }, { url: url.startsWith("http") ? url : scope.server + url, body, method, auth });
    }
    let accepted = 0;
    let claim = "";
    const receipt = () => JSON.stringify({ claim, state: "failed" });
    if (["double claim", "wrong claim token", "submitted receipt", "unknown receipt", "extra receipt field", "missing receipt", "receipt replay"].includes(scenario)) {
      const result = z.object({ claim: z.uuid() }).parse(await send(path + "/claim")); claim = result.claim; accepted++;
    }
    if (scenario === "receipt replay") { await send(path + "/receipt", receipt()); accepted++; }
    const changed: Partial<Record<typeof scenario, Partial<IncidentScope>>> = {
      "wrong phase": { phase: "other" }, "wrong case": { caseId: "foreign" }, "wrong server": { server: "http://127.0.0.1:5173" }, "wrong pid": { pid: startup.pid + 1 }, "wrong auth generation": { auth: scope.auth + "foreign" },
    };
    current = { ...current, ...changed[scenario] };
    if (scenario === "retired") protocol!.retire();
    if (scenario === "positive") {
      for (const incident of census.data.operational_events.incidents) {
        const id = incident.deliveries.find(row => row.channel === "desktop")!.id;
        const response = z.object({ claim: z.uuid(), state: z.literal("sending") }).parse(await send(root + id + "/claim"));
        const result = await send(root + id + "/receipt", JSON.stringify({ claim: response.claim, state: "failed" }));
        expect(result).toMatchObject({ id, channel: "desktop", state: "failed", attempts: 1 }); accepted += 2;
      }
      protocol!.assertComplete();
      const readback = await transport.get(scope.server + "/api/v1/system/diagnostics", { headers: { Authorization: scope.auth } });
      protocol!.verifyReadback(await readback.json());
      const durable = await ledger();
      protocol!.verifyCoreLedger(durable);
      expect(() => protocol!.verifyCoreLedger(durable.slice(0, -2))).toThrow("Core write multiset");
      expect(() => protocol!.verifyCoreLedger([...durable, durable.find(row => row.path.endsWith("/claim"))!])).toThrow("Core write multiset");
      registry.assertSatisfied(); await registry.dispose();
    } else if (["missing claim", "missing receipt"].includes(scenario)) {
      expect(() => protocol!.assertComplete()).toThrow("missing/extra protocol exchanges");
      expect(() => registry.assertSatisfied()).toThrow("unused handler or usage mismatch");
      await expect(registry.dispose()).rejects.toThrow("unused handler or usage mismatch");
    } else {
      let target = path + "/claim"; let body: string | undefined; let method = "POST"; let auth = scope.auth;
      if (scenario === "unknown id") target = root + "00000000-0000-4000-8000-000000000001/claim";
      if (scenario === "foreign channel id") target = root + census.data.operational_events.incidents[0]!.deliveries.find(row => row.channel === "email")!.id + "/claim";
      if (scenario === "claim body") body = "{}";
      if (scenario === "query") target += "?extra=1";
      if (scenario === "method") method = "PUT";
      if (scenario === "endpoint") target = path + "/retry";
      if (scenario === "foreign origin") target = "http://127.0.0.1:5173" + target;
      if (scenario === "missing authorization") auth = "";
      if (["receipt before claim", "wrong claim token", "submitted receipt", "unknown receipt", "extra receipt field", "receipt replay"].includes(scenario)) { target = path + "/receipt"; body = receipt(); }
      if (scenario === "wrong claim token") body = JSON.stringify({ claim: "00000000-0000-4000-8000-000000000001", state: "failed" });
      if (scenario === "submitted receipt") body = JSON.stringify({ claim, state: "submitted_unobserved" });
      if (scenario === "unknown receipt") body = JSON.stringify({ claim, state: "unknown" });
      if (scenario === "extra receipt field") body = JSON.stringify({ claim, state: "failed", extra: true });
      if (scenario === "trading") target = "/api/v1/orders";
      if (scenario === "account") target = "/api/v1/native/accounts";
      if (scenario === "model") target = "/api/v1/backtest/training/jobs";
      if (scenario === "config") target = "/v1/config/llm";
      await expect(send(target, body, method, auth)).rejects.toThrow();
      expect(() => registry.assertSatisfied()).toThrow(/handler error|handler overuse|unexpected request|method mismatch|path mismatch/);
      await expect(registry.dispose()).rejects.toThrow(/handler error|handler overuse|unexpected request|method mismatch|path mismatch/);
    }
    const after = await ledger();
    expect(after.filter(row => row.method !== "GET").length - before.filter(row => row.method !== "GET").length).toBe(accepted);
    await fs.writeFile(info.outputPath("protocol-control.json"), JSON.stringify({ scenario, accepted, before, after, protocol: protocol?.evidence() }, null, 2));
  } finally {
    await transport.dispose(); await context.close(); child.stdin.end("STOP\n");
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      expect(await Promise.race([exited, new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("Core stop timeout")), 30000); })])).toBe(0);
      const shutdown = JSON.parse(await fs.readFile(info.outputPath("normal-core/shutdown.json"), "utf8"));
      expect(shutdown).toMatchObject({ admission_drained: true, listener_stopped: true, listener_closed_probe: true, remaining_threads: [] });
      expect(Object.values(shutdown.owners).every(row => z.object({ closed: z.literal(true) }).safeParse(row).success)).toBe(true);
    } finally { clearTimeout(timer); lines.close(); if (child.exitCode === null && child.signalCode === null) { child.kill("SIGKILL"); await exited; } }
  }
});
