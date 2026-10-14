import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { createProtectionPolicyClient } from "../protectionPolicy";
const scope = { run_id: "protection-client", actor: "operator", account: "paper:run:protection-client", environment: "paper" as const };
const policy = { policy_revision: "synthetic", valid_until: 2000000000, position: { symbol: "TEST", exchange: "NSE" as const, product: "CNC" as const, entry_order_ids: ["synthetic-entry"], quantity: 1 }, hedge_scope: [], risk_policy: "unhedged-cash-reduction-only" as const, max_quantity: 1, max_notional: 100, read: { selector: "synthetic:quotes", valid_until: 2000000000, max_reads: 10, max_age_seconds: 5 } };
function snapshot(revision = 0) { return { scope, revision, policy: revision ? policy : null, authority_state: revision ? "active" : "not_issued", usage: revision ? { reads: 0, quantity_used: 0, notional_used: 0 } : null, duty: { state: revision ? "retained" : "not_granted", remaining_quantity: revision ? 1 : null, reconciliation_required: false, attempts: [] }, supervision: "unavailable" }; }
const response = (data: unknown) => new Response(JSON.stringify({ status: "success", data }), { status: 200 });
beforeEach(() => useAuthStore.setState({ status: "logged-in", username: "operator", token: "synthetic-protection-client", sessionGeneration: 29000 }));
afterEach(() => vi.unstubAllGlobals());

it("refuses client-edited revision evidence before protection I/O", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(snapshot())));
  const client = createProtectionPolicyClient(scope); const value = await client.read();
  value.revision = 19;
  await expect(client.approve(value, policy)).rejects.toThrow(/revision/i);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("reads exact duty after lost approval without claiming success or replaying", async () => {
  let reads = 0; const methods: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    methods.push(init?.method ?? "");
    if (init?.method === "POST") throw new Error("lost synthetic ACK");
    return response(snapshot(reads++ ? 1 : 0));
  }));
  const client = createProtectionPolicyClient(scope); const initial = await client.read();
  await expect(client.approve(initial, policy)).rejects.toThrow(/unknown/i);
  expect(methods).toEqual(["GET", "POST", "GET"]);
  await expect(client.approve(initial, policy)).rejects.toThrow(/read/i);
  const current = await client.read(); expect(current.duty.state).toBe("retained");
  expect(current.supervision).toBe("unavailable");
});

it.each(["scope", "missing-duty", "invented-empty"])("fails closed for %s protection readback", async change => {
  const value: Record<string, unknown> = snapshot();
  if (change === "scope") value.scope = { ...scope, account: "another-book" };
  if (change === "missing-duty") delete value.duty;
  if (change === "invented-empty") value.revision = 8;
  vi.stubGlobal("fetch", vi.fn(async () => response(value)));
  await expect(createProtectionPolicyClient(scope).read()).rejects.toThrow(/unavailable/i);
});

it("does not continue held approval into readback after operator retirement", async () => {
  let release!: (value: Response) => void;
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(url);
    if (init?.method === "POST") return new Promise<Response>(resolve => { release = resolve; });
    return response(snapshot());
  }));
  const client = createProtectionPolicyClient(scope); const initial = await client.read();
  const write = client.approve(initial, policy); const rejected = expect(write).rejects.toThrow(/retired/i);
  useAuthStore.setState({ sessionGeneration: 29001, token: "replacement" });
  release(response({ scope, revision: 1, policy })); await rejected;
  expect(calls).toHaveLength(2);
});
