import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { GrantRequestV2Schema, RunViewV2Schema, OptionsRunViewV2Schema } from "@/generated/nativeAutonomyV2";
import { createNativeV2Client, executionSessionSchema, listExecutionSessions, readExecutionSession } from "../executionSessions";
import captured from "./fixtures/native-v2-lifecycle-captured-v6.json";
import receipts from "./fixtures/native-v2-receipt-captured-v2.json";

const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
  label: "Synthetic receipt account", status: "connected" as const, is_primary: true, connected_at: null, error_message: null };
const failures: unknown[] = [];
let clients: ReturnType<typeof createNativeV2Client>[] = [];
const client = () => { const value = createNativeV2Client(); clients.push(value); return value; };
const data = (index: number) => JSON.parse(captured.samples[index]!.body).data;
const selection = () => GrantRequestV2Schema.parse(captured.samples[4]!.request_json);
beforeEach(() => {
  vi.setSystemTime(new Date(data(3).autonomy_v2.report.generated_at_ms));
  useAuthStore.setState({ status: "logged-in", token: "synthetic-receipts", username: "mounted-operator",
    sessionGeneration: useAuthStore.getState().sessionGeneration + 1 });
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
});
afterEach(() => {
  clients.forEach(value => value.dispose()); clients = [];
  vi.unstubAllGlobals(); vi.useRealTimers(); expect(failures.splice(0)).toEqual([]);
});
type Sample = typeof captured.samples[number];
function replay(indices: number[], edit?: (row: Sample, index: number) => void) {
  const queue = indices.map(index => { const row = structuredClone(captured.samples[index]!); edit?.(row, index); return row; });
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    try {
      const row = queue.shift(); expect(row).toBeDefined();
      expect(url.replace(/^\/ft-api/, "")).toBe(row!.path); expect(init?.method).toBe(row!.method);
      expect(init?.body === undefined ? null : JSON.parse(String(init.body))).toEqual(row!.request_json);
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual(row!.method === "POST"
        ? { authorization: "Bearer synthetic-receipts", "content-type": "application/json" }
        : { authorization: "Bearer synthetic-receipts" });
      calls.push(`${row!.method} ${row!.path}`);
      return new Response(row!.body, { status: row!.status });
    } catch (error) { failures.push(error); throw error; }
  }));
  return { queue, calls };
}
async function accept(value: ReturnType<typeof createNativeV2Client>) {
  const read = await value.read("mounted-native");
  const preview = await value.preview(read.view, selection());
  return value.accept(preview.view, preview.preview);
}
function leaves(value: unknown, prefix = ""): string[] {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value).flatMap(([key, child]) => leaves(child, prefix ? `${prefix}.${key}` : key));
  }
  return [prefix];
}
function change(value: unknown, path: string, omission = false) {
  const keys = path.split(".");
  let parent = value as Record<string, unknown>;
  for (const key of keys.slice(0, -1)) parent = parent[key] as Record<string, unknown>;
  const key = keys.at(-1)!; const old = parent[key];
  if (omission) { delete parent[key]; return; }
  parent[key] = typeof old === "string" ? (old.length === 64 ? "b".repeat(64) : `${old}-foreign`)
    : typeof old === "number" ? old + 1 : typeof old === "boolean" ? !old : old === null ? "foreign" : ["foreign"];
}
const receiptFields = leaves(data(7));
it.each(receiptFields.flatMap(path => [false, true].map(omit => ({ path, omit }))))(
  "refuses complete-receipt mismatch $path omission=$omit without an authority write", async ({ path, omit }) => {
    const trace = replay([2,3,4,5,6,7,8,9], (row, index) => {
      if (index === 7) { const raw = JSON.parse(row.body); change(raw.data, path, omit); row.body = JSON.stringify(raw); }
    });
    const value = client();
    await expect(accept(value)).rejects.toMatchObject({ outcome: "unknown" });
    expect(trace.queue).toEqual([]);
    expect(trace.calls.filter(call => call.endsWith("/grant") || call.endsWith("/start"))).toEqual([]);
  },
);

it("keeps the independent literal receipt, census and full grant positive", async () => {
  const trace = replay([2,3,4,5,6,7,8,9,10,11,12]); const value = client();
  const accepted = await accept(value);
  const granted = await value.grant(accepted.view, selection());
  expect(granted.view.grant?.state).toBe("active"); expect(granted.view.producer_state).toBe("not_started");
  expect(granted.view.transfer_receipts).toEqual(accepted.view.transfer_receipts);
  expect(trace.queue).toEqual([]);
});

it.each([
  ["source revision", "config.producer.source_revision"],
  ["producer configuration", "config.producer.config_revision"],
  ["producer identity", "config.producer.producer_ref.id"],
  ["report source", "report.dimensions.observations.evidence_ref.revision"],
  ["duty census revision", "duty.custody_revision"],
  ["account generation", "scope.registry_generation"],
  ["binding generation", "scope.binding_revision"],
  ["report expiry", "report.expires_at_ms"],
])("refuses an exact-reference-only %s match at grant preflight", async (_name, path) => {
  const trace = replay([2,3,4,5,6,7,8,9]); const value = client(); const accepted = await accept(value);
  const changed = structuredClone(accepted.view); change(changed, path!);
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  await expect(value.grant(changed, selection())).rejects.toBeDefined();
  expect(fetcher).not.toHaveBeenCalled(); expect(trace.queue).toEqual([]);
});

it.each(leaves(selection()))("refuses changed finite selection %s after acceptance before HTTP", async path => {
  const trace = replay([2,3,4,5,6,7,8,9]); const value = client(); const accepted = await accept(value);
  const changed = selection(); change(changed, path);
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  await expect(value.grant(accepted.view, changed)).rejects.toBeDefined();
  expect(fetcher).not.toHaveBeenCalled(); expect(trace.queue).toEqual([]);
});

it.each([[8,6], [5,9], [14,12]])("rejects old/new native and generic snapshots %i/%i", async (native, generic) => {
  const trace = replay([native, generic]);
  await expect(client().read("mounted-native")).rejects.toMatchObject({ outcome: "unknown" });
  expect(trace.queue).toEqual([]);
});

it.each(["cash", "options"])("displays actual current and historical %s custody without inferring a new grant", async profile => {
  const rows = receipts.samples.filter(row => row.case.endsWith(`[${profile}]`) && row.path === "/api/v1/execution-sessions");
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    const raw = JSON.parse(row.body).data;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(row.body)));
    const result = await listExecutionSessions(); expect(result).toEqual(raw);
    for (const session of result) {
      expect(session.autonomy_v2?.effective_authority).toBe("none");
      expect(session.autonomy_v2?.grant).toBeNull();
    }
  }
  const historical = rows.map(row => JSON.parse(row.body).data).flat().find(session =>
    session.autonomy_v2.transfer_receipts.length && session.autonomy_v2.duty.receiving_acceptance_ref === null);
  if (profile === "cash") expect(historical).toBeDefined();
});

it("permits the declared historical receipt shape for display but refuses it as a current acceptance", async () => {
  // Explicit historical-shape compatibility control, not a new producer capture.
  const historical = data(8); delete historical.transfer_receipts[0].model_obligations;
  expect(RunViewV2Schema.safeParse(historical).success).toBe(true);
  expect(OptionsRunViewV2Schema.safeParse(historical).success).toBe(false);
  const trace = replay([2,3,4,5,6,7,8,9], (row, index) => {
    if (index === 7) { const raw = JSON.parse(row.body); delete raw.data.model_obligations; row.body = JSON.stringify(raw); }
  });
  await expect(accept(client())).rejects.toMatchObject({ outcome: "unknown" }); expect(trace.queue).toEqual([]);
});

it("rejects a foreign literal owner at the generic reader and an incomplete census rather than inventing an empty book", async () => {
  const foreign = structuredClone(data(3)); foreign.run_id = "mounted-native:foreign";
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "success", data: foreign }))));
  await expect(readExecutionSession("mounted-native")).rejects.toMatchObject({ outcome: "unknown" });
  expect(executionSessionSchema.safeParse(foreign).success).toBe(false);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "success", data: [data(3), foreign] }))));
  await expect(listExecutionSessions()).rejects.toMatchObject({ outcome: "unknown" });
});
