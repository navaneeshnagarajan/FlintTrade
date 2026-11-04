import { createHash } from "node:crypto";
import { z } from "zod";
import type { Request } from "@playwright/test";
import type { SyntheticFixtureRegistry, SyntheticResponse } from "./fixture-registry";

export const SYSTEM_INSPECTION_CASE = "nine actual app mounts retain layout and context with honest System and local help";
const hash = (value: string) => createHash("sha256").update(value).digest("hex");
const Receipt = z.object({ id: z.uuid(), channel: z.enum(["desktop", "email", "telegram"]), state: z.string(), attempts: z.number().int(), updated_at: z.string() });
const Incident = z.object({ id: z.uuid(), correlation_id: z.string(), source: z.literal("core_http"), scope: z.literal("core_process"), severity: z.literal("critical"), code: z.literal("http_failure"), freshness: z.literal("observed"), operation: z.enum(["native_accounts.list_native_accounts", "native_accounts.connect_native_account"]), measurement: z.object({ state: z.literal("measured"), status_code: z.literal(503) }), root_cause: z.object({ state: z.literal("unknown"), code: z.null() }), deliveries: z.array(Receipt).length(3) });
const Diagnostics = z.object({ status: z.literal("success"), data: z.object({ operational_events: z.object({ status: z.literal("available"), durable: z.literal(true), source: z.literal("operational_sqlite"), scope: z.literal("core_process"), retention: z.literal("until_manual_deletion"), has_more: z.literal(false), next_cursor: z.null(), incidents: z.array(Incident) }) }) });
export interface IncidentScope { caseId: string; title: string; server: string; pid: number; auth: string; phase: string }
export interface ProducerRow { method: string; path: string; status: number; authorization_sha256: string; body_sha256: string; response_sha256: string; body: unknown; response: unknown; diagnostic_request_id?: string | null }
interface Options {
  registry: SyntheticFixtureRegistry; origin: string; prefix: string;
  scope: IncidentScope; current(): Promise<IncidentScope>;
  diagnosticsWire: string; producerLedger: ProducerRow[]; expectedNativeReads: number;
  relay(request: Request): Promise<SyntheticResponse>;
}
function requireThat(value: unknown, message: string): asserts value { if (!value) throw new Error("incident protocol: " + message); }

/** Explicit finite opt-in. The ordinary registry has no incident exception.
 * IDs come from an authenticated producer census BEFORE any browser write.
 * Transport uncertainty consumes the slot; it never authorises a retry.
 */
export function armIncidentProtocol(options: Options) {
  const { registry, origin, prefix, relay } = options;
  const scope = Object.freeze({ ...options.scope });
  requireThat(scope.title === SYSTEM_INSPECTION_CASE && scope.phase === "system-inspection", "wrong case or phase");
  requireThat(scope.caseId.length > 0 && scope.pid > 0 && scope.auth.startsWith("Bearer ") && /^http:\/\/127\.0\.0\.1:(5100|5173)$/.test(scope.server), "missing fixture identity");
  requireThat(Number.isSafeInteger(options.expectedNativeReads) && options.expectedNativeReads >= 1 && options.expectedNativeReads <= 7, "bounded producer reads");
  const diagnosticsRows = options.producerLedger.filter(row => row.method === "GET" && row.path === "/api/v1/system/diagnostics" && row.status === 200 && row.authorization_sha256 === hash(scope.auth) && row.body_sha256 === hash("") && row.response_sha256 === hash(options.diagnosticsWire));
  requireThat(diagnosticsRows.length === 1, "authenticated same-Core diagnostics bytes required");
  const census = Diagnostics.parse(JSON.parse(options.diagnosticsWire)).data.operational_events;
  const producers = options.producerLedger.filter(row => row.path === "/api/v1/native/accounts");
  requireThat(producers.length === options.expectedNativeReads + 1, "producer census count");
  requireThat(producers.filter(row => row.method === "POST").length === 1 && producers.filter(row => row.method === "GET").length === options.expectedNativeReads, "producer operation census");
  requireThat(producers.every(row => row.status === 503 && row.authorization_sha256 === hash(scope.auth)), "producer auth/status");
  requireThat(producers.filter(row => row.method === "GET").every(row => row.body_sha256 === hash("")), "producer GET body");
  const connect = producers.find(row => row.method === "POST")!;
  z.object({ adapter_id: z.literal("dhan"), account_id: z.literal("synthetic-unavailable"), credentials: z.object({}).strict() }).strict().parse(connect.body);
  z.object({ error: z.literal("broker_account_cutover_unavailable") }).strict().parse(connect.response);
  requireThat(census.incidents.length === producers.length, "incident census count");
  requireThat(census.incidents.filter(row => row.operation === "native_accounts.list_native_accounts").length === options.expectedNativeReads, "incident operation census");
  requireThat(census.incidents.filter(row => row.operation === "native_accounts.connect_native_account").length === 1, "fixture connect census");
  const responseIds = producers.map(row => row.diagnostic_request_id);
  requireThat(responseIds.every(id => typeof id === "string" && /^[0-9a-f]{8}\.[0-9a-f]{4}\.4[0-9a-f]{3}\.[89ab][0-9a-f]{3}\.[0-9a-f]{12}$/.test(id)), "missing/invalid producer exchange correlation");
  requireThat(new Set(responseIds).size === producers.length, "duplicate producer exchange correlation");
  const ids = new Set<string>(); const correlations = new Set<string>();
  const entries = census.incidents.map(incident => {
    requireThat(!correlations.has(incident.correlation_id), "repeated correlation"); correlations.add(incident.correlation_id);
    const producer = producers.find(row => row.diagnostic_request_id === incident.correlation_id);
    requireThat(producer && incident.operation === (producer.method === "GET" ? "native_accounts.list_native_accounts" : "native_accounts.connect_native_account"), "incident correlation must join its exact producer exchange/operation");
    requireThat(new Set(incident.deliveries.map(row => row.channel)).size === 3, "channel census");
    for (const row of incident.deliveries) {
      requireThat(!ids.has(row.id), "duplicate delivery"); ids.add(row.id);
      requireThat(row.attempts === 0 && row.state === (row.channel === "desktop" ? "browser_pending" : "disabled"), "initial attempt/channel state");
    }
    return { incident, delivery: incident.deliveries.find(row => row.channel === "desktop")!, state: "pending", claim: "" };
  });
  let retired = false;
  const exchanges: { method: string; path: string; body: string; status: number; response: string }[] = [];
  async function check(request: Request, path: string) {
    requireThat(!retired, "retired phase");
    const current = await options.current();
    requireThat(Object.keys(scope).every(key => current[key as keyof IncidentScope] === scope[key as keyof IncidentScope]), "case/server/auth/phase generation changed");
    requireThat(request.method() === "POST" && request.url() === origin + path && request.headers()["authorization"] === scope.auth, "exact request scope");
  }
  for (const entry of entries) {
    const base = prefix + "/api/v1/system/incidents/deliveries/" + entry.delivery.id;
    registry.register({ name: "audited incident claim " + entry.delivery.id, method: "POST", path: base + "/claim", expectedCalls: 1, handler: async request => {
      await check(request, base + "/claim");
      requireThat(request.postData() === null && entry.state === "pending", "empty one-shot claim required");
      entry.state = "claim-in-flight";
      const response = await relay(request);
      exchanges.push({ method: request.method(), path: base + "/claim", body: "", status: response.status ?? 0, response: response.body ?? "" });
      requireThat(response.status === 200 && typeof response.body === "string", "claim response unavailable; no retry");
      const claim = z.object({ id: z.literal(entry.delivery.id), claim: z.uuid(), state: z.literal("sending") }).strict().parse(JSON.parse(response.body));
      entry.claim = claim.claim; entry.state = "claimed";
      return response;
    } });
    registry.register({ name: "audited incident receipt " + entry.delivery.id, method: "POST", path: base + "/receipt", expectedCalls: 1, handler: async request => {
      await check(request, base + "/receipt");
      requireThat(entry.state === "claimed" && request.postData() === JSON.stringify({ claim: entry.claim, state: "failed" }), "matching failed receipt required");
      requireThat(request.headers()["content-type"] === "application/json", "receipt content type");
      entry.state = "receipt-in-flight";
      const response = await relay(request);
      exchanges.push({ method: request.method(), path: base + "/receipt", body: request.postData()!, status: response.status ?? 0, response: response.body ?? "" });
      requireThat(response.status === 200 && typeof response.body === "string", "receipt uncertain; no retry");
      const readback = Receipt.parse(JSON.parse(response.body));
      requireThat(readback.id === entry.delivery.id && readback.channel === "desktop" && readback.state === "failed" && readback.attempts === 1, "receipt identity/state mismatch");
      entry.state = "complete"; return response;
    } });
  }
  function assertComplete() { requireThat(entries.every(entry => entry.state === "complete") && exchanges.length === entries.length * 2, "missing/extra protocol exchanges"); }
  function signatures(rows: { method: string; path: string; status: number; bodySha256: string; responseSha256: string }[]) {
    return rows.map(row => JSON.stringify([row.method, row.path, row.status, row.bodySha256, row.responseSha256])).sort();
  }
  const expectedWrites = () => exchanges.map(row => ({ ...row, bodySha256: hash(row.body), responseSha256: hash(row.response) }));
  return {
    count: entries.length * 2,
    predicates: [{ kind: "net", method: "POST", count: entries.length * 2 }, ...entries.flatMap(entry => ["claim", "receipt"].map(action => ({ kind: "net", method: "POST", urlContains: "/api/v1/system/incidents/deliveries/" + entry.delivery.id + "/" + action, status: 200, count: 1 })))],
    assertComplete,
    assertOnlyWrites(rows: { method: string; path: string; bodySha256: string; responseSha256: string; status: number }[]) {
      assertComplete();
      const actual = rows.filter(row => row.method !== "GET");
      requireThat(JSON.stringify(signatures(actual)) === JSON.stringify(signatures(expectedWrites())), "unexpected non-GET write multiset");
    },
    verifyCoreLedger(rows: ProducerRow[]) {
      assertComplete();
      const project = (row: ProducerRow) => ({ ...row, bodySha256: row.body_sha256, responseSha256: row.response_sha256 });
      const before = options.producerLedger.filter(row => row.method !== "GET").map(project);
      const expected = [...before, ...expectedWrites().map(row => ({ ...row, path: row.path.slice(prefix.length) }))];
      const actual = rows.filter(row => row.method !== "GET");
      requireThat(actual.every(row => row.authorization_sha256 === hash(scope.auth)), "Core write auth");
      requireThat(JSON.stringify(signatures(actual.map(project))) === JSON.stringify(signatures(expected)), "Core write multiset");
    },
    verifyReadback(value: unknown) {
      assertComplete();
      const after = Diagnostics.parse(value).data.operational_events;
      for (const entry of entries) {
        const incident = after.incidents.find(row => row.id === entry.incident.id);
        requireThat(incident?.correlation_id === entry.incident.correlation_id && incident.operation === entry.incident.operation, "durable incident changed");
        for (const previous of entry.incident.deliveries) {
          const actual = incident.deliveries.find(row => row.id === previous.id);
          requireThat(actual?.state === (previous.channel === "desktop" ? "failed" : "disabled") && actual.attempts === (previous.channel === "desktop" ? 1 : 0), "durable receipt/channel changed");
        }
      }
    },
    retire() { retired = true; },
    evidence() { return { scope: { ...scope, auth: hash(scope.auth) }, diagnosticsWire: options.diagnosticsWire, diagnosticsSha256: hash(options.diagnosticsWire), census, producers, exchanges, states: entries.map(entry => ({ id: entry.delivery.id, state: entry.state })) }; },
  };
}
