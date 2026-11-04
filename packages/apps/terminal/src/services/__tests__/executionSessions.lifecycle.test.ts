import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { createNativeV2Client, executionSessionSchema, type NativeV2Observation } from "../executionSessions";
import { GrantRequestV2Schema } from "@/generated/nativeAutonomyV2";
import captured from "./fixtures/native-v2-lifecycle-captured-v6.json";

const seed = () => executionSessionSchema.parse(JSON.parse(captured.samples[3]!.body).data);
const selection = () => GrantRequestV2Schema.parse(captured.samples[4]!.request_json);
const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
  label: "Synthetic account", status: "connected" as const, is_primary: true, connected_at: null, error_message: null };
const failures: unknown[] = [];
let clients: ReturnType<typeof createNativeV2Client>[] = [];
function client() { const value = createNativeV2Client(); clients.push(value); return value; }
beforeEach(() => {
  vi.setSystemTime(new Date(seed().autonomy_v2!.report!.generated_at_ms));
  useAuthStore.setState({ status: "logged-in", token: "synthetic-lifecycle-client", username: "mounted-operator",
    sessionGeneration: useAuthStore.getState().sessionGeneration + 1 });
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
});
afterEach(() => {
  clients.forEach(value => value.dispose()); clients = [];
  vi.unstubAllGlobals(); vi.useRealTimers();
  const errors = failures.splice(0); expect(errors).toEqual([]);
});

type Sample = typeof captured.samples[number];
function replay(indices: number[], edit?: (row: Sample, index: number) => Sample) {
  const queue = indices.map(index => edit?.(structuredClone(captured.samples[index]!), index)
    ?? structuredClone(captured.samples[index]!));
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    try {
      const expected = queue.shift(); expect(expected).toBeDefined();
      const path = url.replace(/^\/ft-api/, "");
      calls.push(`${init?.method} ${path}`);
      expect(path).toBe(expected!.path); expect(init?.method).toBe(expected!.method);
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual(init?.method === "POST"
        ? { authorization: "Bearer synthetic-lifecycle-client", "content-type": "application/json" }
        : { authorization: "Bearer synthetic-lifecycle-client" });
      expect(init?.body === undefined ? null : JSON.parse(String(init.body))).toEqual(expected!.request_json);
      return new Response(expected!.body, { status: expected!.status });
    } catch (error) { failures.push(error); throw error; }
  }));
  return { calls, queue };
}
async function throughAcceptance(value: ReturnType<typeof createNativeV2Client>) {
  const read = await value.read("mounted-native");
  const preview = await value.preview(read.view, selection());
  return value.accept(preview.view, preview.preview);
}

it("decodes the real producer's started session without equating entries armed with native readiness", () => {
  const started = executionSessionSchema.parse(JSON.parse(captured.samples[15]!.body).data);
  expect(started.entries_armed).toBe(true); expect(started.native_ready).toBe(false);
  expect(started.autonomy_v2!.effective_authority).toBe("none");
  expect(started.autonomy_v2!.producer_state).toBe("running");
});

it.each(["preview selection", "accept duty", "grant limits", "start generation", "stop grant"])(
  "rejects a matching but contradictory %s exchange without resending", async fault => {
    // Deliberately corrupted copies, not alternative producer fixtures.
    const phases = { "preview selection": 6, "accept duty": 9, "grant limits": 12, "start generation": 15, "stop grant": 18 };
    const end = phases[fault as keyof typeof phases];
    const trace = replay(Array.from({ length: end - 1 }, (_, index) => index + 2), (row, index) => {
      const body = JSON.parse(row.body); const data = body.data;
      if (fault === "preview selection" && index === 4) data.selection.limits.max_total_quantity++;
      if (fault === "accept duty") {
        if (index === 7) data.duty_ref.id = "different-duty";
        if (index === 8) data.duty.duty_ref.id = "different-duty";
        if (index === 9) data.autonomy_v2.duty.duty_ref.id = "different-duty";
      }
      if (fault === "grant limits" && index >= 10 && index <= 12) {
        (index === 12 ? data.autonomy_v2 : data).grant.limits.max_total_quantity++;
      }
      if (fault === "start generation" && index === 15) data.generation--;
      if (fault === "stop grant" && index >= 16) {
        (index === 17 ? data : data.autonomy_v2).grant.grant_ref.id = "foreign-grant";
      }
      return { ...row, body: JSON.stringify(body) };
    });
    const value = client(); let current: NativeV2Observation = await value.read("mounted-native");
    const actions = [
      () => value.preview(current.view, selection()), () => value.accept(current.view, current.preview),
      () => value.grant(current.view, selection()), () => value.start(current.session), () => value.stop(current.session),
    ];
    const target = ["preview selection", "accept duty", "grant limits", "start generation", "stop grant"].indexOf(fault);
    for (let index = 0; index < target; index++) current = await actions[index]!();
    await expect(actions[target]!()).rejects.toMatchObject({ outcome: "unknown" });
    expect(trace.queue).toEqual([]);
    const before = [...trace.calls];
    await expect(actions[target]!()).rejects.toMatchObject({ outcome: "refused" });
    expect(trace.calls).toEqual(before);
  });

it("keeps malformed acceptance unknown even when its independent readback contains an acceptance", async () => {
  const trace = replay([2,3,4,5,6,7,8,9], (row, index) => index === 7
    ? { ...row, body: JSON.stringify({ status: "success", data: null }) } : row);
  const value = client(); const read = await value.read("mounted-native");
  const preview = await value.preview(read.view, selection());
  await expect(value.accept(preview.view, preview.preview)).rejects.toMatchObject({ outcome: "unknown" });
  expect(trace.queue).toEqual([]);
  await expect(value.grant(preview.view, selection())).rejects.toMatchObject({ outcome: "refused" });
  expect(trace.calls.filter(call => call.includes("/grant"))).toEqual([]);
});

it.each(["blank", "boolean", "fraction", "expired", "foreign report"])("refuses %s finite intent before HTTP", async bad => {
  const value = client(); const request = selection();
  const raw = structuredClone(request) as unknown as Record<string, unknown>;
  const limits = raw.limits as Record<string, unknown>;
  if (bad === "blank") limits.max_reads = "";
  if (bad === "boolean") limits.max_reads = true;
  if (bad === "fraction") limits.max_reads = 1.5;
  if (bad === "expired") raw.expires_at_ms = Date.now();
  if (bad === "foreign report") raw.report_ref = { ...request.report_ref, id: "foreign-report" };
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(value.preview(seed().autonomy_v2!, raw)).rejects.toMatchObject({ outcome: "refused" });
  expect(fetch).not.toHaveBeenCalled();
});

it("blocks another lifecycle action while preview is held and retires its late result across A-B-A", async () => {
  const value = client(); let release!: (response: Response) => void;
  const fetch = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>(resolve => { release = resolve; }));
  vi.stubGlobal("fetch", fetch);
  const pending = value.preview(seed().autonomy_v2!, selection());
  expect(fetch).toHaveBeenCalledTimes(1);
  const altered = selection(); altered.limits.max_reads++;
  await expect(value.preview(seed().autonomy_v2!, altered)).rejects.toMatchObject({ outcome: "refused" });
  expect(fetch).toHaveBeenCalledTimes(1);
  const other = { ...account, account_id: "Other" };
  useBrokerStore.setState({ accounts: [account, other], activeAccountId: brokerAccountKey(other) });
  useBrokerStore.setState({ activeAccountId: brokerAccountKey(account) });
  release(new Response(captured.samples[4]!.body, { status: 200 }));
  await expect(pending).rejects.toMatchObject({ outcome: "retired" });
  expect(fetch).toHaveBeenCalledTimes(1); expect(value.isCurrent()).toBe(false);
});

it("keeps an accepted finite selection local to this client rather than treating a displayed receipt as authority", async () => {
  const trace = replay([2,3,4,5,6,7,8,9]); const value = client();
  const accepted = await throughAcceptance(value); expect(accepted.transfer).toBeDefined(); expect(trace.queue).toEqual([]);
  const foreign = client();
  await expect(foreign.grant(accepted.view, selection())).rejects.toMatchObject({ outcome: "refused" });
  expect(trace.calls.filter(call => call.endsWith("/grant"))).toEqual([]);
});
