import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { createRunPolicyClient } from "../runPolicy";

const scope = { run_id: "policy-client", actor: "operator", account: "paper:run:policy-client", environment: "paper" as const };
const proposal = { action: "access", expected_revision: 2, value: { operations: ["evaluation.read"], valid_until: 2000000000, evidence: "synthetic explicit policy" } };
const provenance = "operator-supplied-not-measured-entitlement";
const config = (revision = 2) => ({ scope, policy_provenance: provenance, controls: { access: { revision, value: revision === 3 ? proposal.value : null }, "grant:reasoning": { revision: 0, value: null }, "learning-dataset": { revision: 0, value: null }, "learning-policy": { revision: 0, value: null }, "learning-binding": { revision: 0, value: null } } });
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const preview = () => ({ scope, policy_provenance: provenance, proposal, confirmation: "synthetic-one-use", expires_in_seconds: 120 });
beforeEach(() => useAuthStore.setState({ status: "logged-in", token: "synthetic-r29", username: "operator", sessionGeneration: 299 }));
afterEach(() => vi.unstubAllGlobals());

it("reads exact policy after a lost confirm and requires explicit readback before another preview", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    if (url.endsWith("/preview")) return response(preview());
    if (url.endsWith("/confirm")) throw new Error("private body must not escape");
    return response(config(3));
  }));
  const client = createRunPolicyClient(scope);
  const pending = await client.preview(proposal);
  await expect(client.confirm(pending)).rejects.toThrow(/unknown|unavailable/i);
  expect(calls.map(path => path.split("/").at(-1))).toEqual(["preview", "confirm", "configuration"]);
  await expect(client.preview(proposal)).rejects.toThrow(/read/i);
  expect(calls).toHaveLength(3);
  await expect(client.confirm(pending)).rejects.toThrow(/consumed|cancelled/i);
  await client.read();
  await client.preview({ ...proposal, expected_revision: 2 });
});

it("refuses mutation of a preview's complete captured value before confirmation", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(preview())));
  const client = createRunPolicyClient(scope);
  const view = await client.preview(proposal);
  view.proposal.value.evidence = "different proposal";
  await expect(client.confirm(view)).rejects.toThrow(/changed|mismatch/i);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("retires a held decoded response on token replacement even within the same auth generation", async () => {
  let release!: (value: unknown) => void;
  const decoded = new Promise(resolve => { release = resolve; });
  const responseBody = new Response("{}");
  vi.spyOn(responseBody, "json").mockImplementation(() => decoded);
  vi.stubGlobal("fetch", vi.fn(async () => responseBody));
  const client = createRunPolicyClient(scope);
  const read = client.read();
  const rejected = expect(read).rejects.toThrow(/retired/i);
  useAuthStore.setState({ token: "replacement-operator-token" });
  release(config()); await rejected;
});

it("never accepts a malformed or wrong-scope read", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...config(), scope: { ...scope, account: "paper:run:other" } })));
  await expect(createRunPolicyClient(scope).read()).rejects.toThrow(/scope|mismatch/i);
});

it("rejects a successful configuration envelope with omitted authoritative controls", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...config(), controls: {} })));
  await expect(createRunPolicyClient(scope).read()).rejects.toThrow(/configuration|unavailable/i);
});

it("captures the selected scope rather than a caller-owned mutable object", async () => {
  const selected = { ...scope };
  vi.stubGlobal("fetch", vi.fn(async () => response({ ...config(), scope: { ...scope, account: "foreign-book" } })));
  const client = createRunPolicyClient(selected);
  selected.account = "foreign-book";
  await expect(client.read()).rejects.toThrow(/scope/i);
});

it("counts preview transit time against the one-use lifetime", async () => {
  const clock = vi.spyOn(Date, "now").mockReturnValue(1000);
  vi.stubGlobal("fetch", vi.fn(async () => { clock.mockReturnValue(122000); return response(preview()); }));
  const client = createRunPolicyClient(scope);
  try { const view = await client.preview(proposal); await expect(client.confirm(view)).rejects.toThrow(/expired/); expect(fetch).toHaveBeenCalledTimes(1); }
  finally { clock.mockRestore(); }
});

it("does not verify matching ACK/readback when the committed value differs from the exact proposal", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/preview") ? response(preview()) : response({ ...config(3), controls: { ...config(3).controls, access: { revision: 3, value: { ...proposal.value, operations: ["training.start"] } } } })));
  const client = createRunPolicyClient(scope); const view = await client.preview(proposal);
  await expect(client.confirm(view)).rejects.toThrow(/value|proposal|mismatch/i);
});

it("cancels an in-flight preview without accepting its late confirmation", async () => {
  let release!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { release = resolve; })));
  const client = createRunPolicyClient(scope);
  const request = client.preview(proposal); const refused = expect(request).rejects.toThrow(/cancelled|retired/i);
  client.cancel(); release(response(preview())); await refused;
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("keeps confirmation expiry private instead of trusting editable presentation", async () => {
  const clock = vi.spyOn(Date, "now").mockReturnValue(1000);
  vi.stubGlobal("fetch", vi.fn(async () => response(preview())));
  const client = createRunPolicyClient(scope); const view = await client.preview(proposal);
  view.expiresAt = 999999999;
  clock.mockReturnValue(122000);
  try { await expect(client.confirm(view)).rejects.toThrow(/expired/i); expect(fetch).toHaveBeenCalledTimes(1); }
  finally { clock.mockRestore(); }
});

it("disposal rejects late previews and cannot be revived by another read", async () => {
  let release!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { release = resolve; })));
  const client = createRunPolicyClient(scope);
  const work = client.preview(proposal); const rejected = expect(work).rejects.toThrow(/retired/i);
  client.dispose(); release(response(preview())); await rejected;
  await expect(client.read()).rejects.toThrow(/retired/i);
  expect(fetch).toHaveBeenCalledTimes(1);
});
