import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { controlExecutionSession, listExecutionSessions, readExecutionSession } from "../executionSessions";
import fixture from "./fixtures/executionSessions.synthetic.json";
import cancellation from "./fixtures/executionSessions.cancel.synthetic.json";
import stale from "./fixtures/executionSessions.stale.synthetic.json";
import retirement from "./fixtures/executionSessions.retirement.synthetic.json";

let generation = 1200;
beforeEach(() => useAuthStore.setState({ status: "logged-in", token: "synthetic-native-v1", username: "synthetic-operator", sessionGeneration: ++generation }));
afterEach(() => vi.unstubAllGlobals());

function transport(handlers: Record<string, (init?: RequestInit) => Response | Promise<Response>>) {
  const calls: string[] = []; const failures: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    try {
      const handler = handlers[key];
      if (!handler) throw new Error(`Unregistered ${key}`);
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual(init?.method === "POST"
        ? { authorization: "Bearer synthetic-native-v1", "content-type": "application/json" }
        : { authorization: "Bearer synthetic-native-v1" });
      return await handler(init);
    } catch (error) { failures.push(error); throw error; }
  }));
  return { calls, failures };
}

it.each(["malformed acknowledgement", "changed generation", "changed binding revision"])("native Stop keeps %s uncertain, reads once and never resends", async fault => {
  let reads = 0;
  const stopped = fault === "changed generation" ? { ...fixture.responses.stopped.data, generation: 9 }
    : fault === "changed binding revision" ? { ...fixture.responses.stopped.data, autonomy: { ...fixture.responses.stopped.data.autonomy, revision: "e".repeat(64) } }
    : fixture.responses.stopped.data;
  const io = transport({
    "GET /api/v1/execution-sessions/bounded-one": () => new Response(JSON.stringify({ status: "success", data: ++reads === 1 ? fixture.responses.partial.data : stopped })),
    "POST /api/v1/execution-sessions/bounded-one/stop": init => {
      expect(JSON.parse(String(init?.body))).toEqual({ account: "dhan:inert-account", environment: "live", expected_generation: 0 });
      return new Response(JSON.stringify({ status: "success", data: fault === "malformed acknowledgement" ? {} : stopped }));
    },
  });
  const target = await readExecutionSession("bounded-one");
  await expect(controlExecutionSession(target, "stop")).rejects.toThrow(/unknown/);
  await expect(controlExecutionSession(target, "stop")).rejects.toThrow(/already sent/);
  expect(io.calls).toEqual(["GET /api/v1/execution-sessions/bounded-one", "POST /api/v1/execution-sessions/bounded-one/stop", "GET /api/v1/execution-sessions/bounded-one"]);
  expect(io.failures).toEqual([]);
});

it("retires a held native read when the same operator's authentication generation changes", async () => {
  let release: ((value: Response) => void) | undefined;
  const io = transport({ "GET /api/v1/execution-sessions/bounded-one": () => new Promise<Response>(resolve => { release = resolve; }) });
  const pending = readExecutionSession("bounded-one");
  const rejected = expect(pending).rejects.toThrow(/retired/);
  expect(release).toBeTypeOf("function");
  useAuthStore.setState({ sessionGeneration: ++generation, token: "different-synthetic-session" });
  release?.(new Response(JSON.stringify(fixture.responses.ready)));
  await rejected;
  expect(io.calls).toHaveLength(1); expect(io.failures).toEqual([]);
});

it.each(Object.entries({ ...cancellation.responses, ...stale.responses }))("reads untouched synthetic Core %s without inventing authority or flatness", async (_name, response) => {
  const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`;
    if (key !== "GET /api/v1/execution-sessions/bounded-one") { failures.push(key); throw new Error(key); }
    return new Response(JSON.stringify(response));
  }));
  await expect(readExecutionSession("bounded-one")).resolves.toEqual(response.data);
  expect(failures).toEqual([]);
});

it("accepts the entire real-serializer synthetic mixed Paper, legacy Live and native census", async () => {
  const unexpected: string[] = [];
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    if (key !== "GET /api/v1/execution-sessions") { unexpected.push(key); throw new Error(key); }
    return new Response(JSON.stringify(fixture.responses.mixed));
  }));
  const rows = await listExecutionSessions();
  expect(rows.map(row => row.run_id)).toEqual(["bounded-one", "legacy-synthetic", "paper-synthetic"]);
  expect(rows[0]).toMatchObject({ entries_armed: false, native_ready: true, autonomy: { authorised: true, binding: { actor: "bounded:bounded-one" } } });
  expect(calls).toHaveLength(1); expect(unexpected).toEqual([]);
});

it("preserves captured Core command receipts and unresolved obligations on an exact read", async () => {
  const unexpected: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`;
    if (key !== "GET /api/v1/execution-sessions/bounded-one") { unexpected.push(key); throw new Error(key); }
    return new Response(JSON.stringify(fixture.responses.partial));
  }));
  const result = await readExecutionSession("bounded-one");
  expect(result).toEqual(fixture.responses.partial.data);
  expect(unexpected).toEqual([]);
});

it("refuses native activation and closes at the client boundary without sending", async () => {
  const io = transport({ "GET /api/v1/execution-sessions/bounded-one": () => new Response(JSON.stringify(fixture.responses.ready)) });
  const target = await readExecutionSession("bounded-one");
  for (const operation of ["start", "rearm", "close"] as const) {
    await expect(controlExecutionSession(target, operation)).rejects.toThrow(/inspection|Stop entries/);
  }
  expect(io.calls).toEqual(["GET /api/v1/execution-sessions/bounded-one"]);
  expect(io.failures).toEqual([]);
});

it.each([
  ["configured without grant", fixture.responses.configured],
  ["qualified without grant", retirement.controls.qualifiedWithoutGrant],
  ["already revoked", fixture.responses.stopped],
  ["restart retired grant", stale.responses.restart],
  ["legacy without projection", { status: "success", data: fixture.responses.mixed.data[1] }],
])("refuses native Stop for %s", async (_name, response) => {
  const io = transport({ [`GET /api/v1/execution-sessions/${response.data.run_id}`]: () => new Response(JSON.stringify(response)) });
  const target = await readExecutionSession(response.data.run_id);
  await expect(controlExecutionSession(target, "stop")).rejects.toThrow(/inspection/);
  expect(io.calls).toHaveLength(1); expect(io.failures).toEqual([]);
});

it.each(Object.entries(retirement.scenarios))("retires a retained %s-blocked grant with captured Stop ACK and exact GET, without entry authority", async (_name, responses) => {
  let reads = 0;
  const io = transport({
    "GET /api/v1/execution-sessions/bounded-one": () => new Response(JSON.stringify(++reads === 1 ? responses.blocked : responses.stopped)),
    "POST /api/v1/execution-sessions/bounded-one/stop": init => {
      expect(JSON.parse(String(init?.body))).toEqual({ account: "dhan:inert-account", environment: "live", expected_generation: 0 });
      return new Response(JSON.stringify(responses.stopAck));
    },
  });
  const target = await readExecutionSession("bounded-one");
  expect(target).toMatchObject({ entries_armed: false, native_ready: false, autonomy: { authorised: false, grant: { revoked: false } } });
  for (const operation of ["start", "rearm", "close"] as const) {
    await expect(controlExecutionSession(target, operation)).rejects.toThrow(/inspection/);
  }
  await expect(controlExecutionSession(target, "stop")).resolves.toEqual(responses.stopped.data);
  await expect(controlExecutionSession(target, "stop")).rejects.toThrow(/already sent/);
  expect(io.calls).toEqual(["GET /api/v1/execution-sessions/bounded-one", "POST /api/v1/execution-sessions/bounded-one/stop", "GET /api/v1/execution-sessions/bounded-one"]);
  expect(io.failures).toEqual([]);
});

it.each([
  ["kill with obligations", cancellation.responses.killBlocked],
  ["stale qualification with obligations", stale.responses.staleQualification],
])("requests retirement for captured %s but never confirms a malformed ACK or resends", async (_name, response) => {
  const io = transport({
    "GET /api/v1/execution-sessions/bounded-one": () => new Response(JSON.stringify(response)),
    "POST /api/v1/execution-sessions/bounded-one/stop": init => {
      expect(JSON.parse(String(init?.body))).toEqual({ account: "dhan:inert-account", environment: "live", expected_generation: 0 });
      return new Response(JSON.stringify({ status: "success", data: {} }));
    },
  });
  const target = await readExecutionSession("bounded-one");
  expect(target.autonomy?.obligations.length).toBeGreaterThan(0);
  await expect(controlExecutionSession(target, "stop")).rejects.toThrow(/unknown/);
  await expect(controlExecutionSession(target, "stop")).rejects.toThrow(/already sent/);
  expect(io.calls).toEqual(["GET /api/v1/execution-sessions/bounded-one", "POST /api/v1/execution-sessions/bounded-one/stop", "GET /api/v1/execution-sessions/bounded-one"]);
  expect(io.failures).toEqual([]);
});

it("does not certify a native Stop whose acknowledgement and readback still report effective authority", async () => {
  let reads = 0;
  const armed = { ...fixture.responses.ready, data: { ...fixture.responses.ready.data, generation: 1 } };
  const io = transport({
    "GET /api/v1/execution-sessions/bounded-one": () => new Response(JSON.stringify(++reads === 1 ? fixture.responses.ready : armed)),
    "POST /api/v1/execution-sessions/bounded-one/stop": init => {
      expect(JSON.parse(String(init?.body))).toEqual({ account: "dhan:inert-account", environment: "live", expected_generation: 0 });
      return new Response(JSON.stringify(armed));
    },
  });
  const target = await readExecutionSession("bounded-one");
  await expect(controlExecutionSession(target, "stop")).rejects.toThrow(/unknown/);
  expect(io.calls).toEqual(["GET /api/v1/execution-sessions/bounded-one", "POST /api/v1/execution-sessions/bounded-one/stop", "GET /api/v1/execution-sessions/bounded-one"]);
  expect(io.failures).toEqual([]);
});

const cancellationOrderContradictions = [
  ["symbol", "OTHER"], ["exchange", "BSE"], ["action", "SELL"],
  ["product", "MIS"], ["order_type", "MARKET"], ["quantity", 200], ["price", 101],
  ["broker", "other"], ["account_id", "other"], ["strategy", "bounded:other"],
] as const;
it.each(cancellationOrderContradictions)("rejects cancellation expected-order %s contradiction at both complete-census and exact-read boundaries", async (field, value) => {
  // Single-field synthetic negatives, not purported producer observations.
  const broken = structuredClone(cancellation.responses.cancelRequested);
  const cancel = broken.data.autonomy.commands.find(command => command.operation === "cancel")!;
  Object.assign(cancel.expected_order!, { [field]: value });
  const io = transport({
    "GET /api/v1/execution-sessions": () => new Response(JSON.stringify({ status: "success", data: [fixture.responses.paper.data, broken.data] })),
    "GET /api/v1/execution-sessions/bounded-one": () => new Response(JSON.stringify(broken)),
  });
  await expect(listExecutionSessions()).rejects.toThrow(/unknown|unavailable/);
  await expect(readExecutionSession("bounded-one")).rejects.toThrow(/unknown/);
  expect(io.calls).toEqual(["GET /api/v1/execution-sessions", "GET /api/v1/execution-sessions/bounded-one"]);
  expect(io.failures).toEqual([]);
});

it.each(["missing placement", "cancel references itself", "different broker order", "extra order field", "missing order field", "numeric string"])("refuses %s in cancellation evidence without partial census", async fault => {
  const broken = structuredClone(cancellation.responses.cancelRequested);
  const cancel = broken.data.autonomy.commands.find(command => command.operation === "cancel")!;
  if (fault === "missing placement") cancel.placement_command_id = "absent";
  if (fault === "cancel references itself") cancel.placement_command_id = cancel.command_id;
  if (fault === "different broker order") cancel.body.order_id = "other-order";
  if (fault === "extra order field") Object.assign(cancel.expected_order!, { extra: "unsupported" });
  if (fault === "missing order field") Reflect.deleteProperty(cancel.expected_order!, "symbol");
  if (fault === "numeric string") Object.assign(cancel.expected_order!, { quantity: "2" });
  const io = transport({ "GET /api/v1/execution-sessions": () => new Response(JSON.stringify({ status: "success", data: [fixture.responses.paper.data, broken.data] })) });
  await expect(listExecutionSessions()).rejects.toThrow(/unknown|unavailable/);
  expect(io.calls).toEqual(["GET /api/v1/execution-sessions"]); expect(io.failures).toEqual([]);
});

it.each(["pending_admission", "dispatched", "cancel_requested", "partial"])("accepts bound cancellation %s evidence without equating observations from different moments", async state => {
  // Explicit synthetic compatible variants; only immutable order values must match.
  const response = structuredClone(cancellation.responses.cancelRequested);
  const cancel = response.data.autonomy.commands.find(command => command.operation === "cancel")!;
  const placement = response.data.autonomy.commands.find(command => command.command_id === "command-one")!;
  Object.assign(cancel, { state, events: ["pending_admission", state], filled_quantity: 0 });
  Object.assign(placement, { state: "partial", events: [...placement.events, "partial"], filled_quantity: 1 });
  // JSON property insertion order is not order identity.
  Object.assign(cancel, { expected_order: Object.fromEntries(Object.entries(cancel.expected_order!).reverse()) });
  const io = transport({
    "GET /api/v1/execution-sessions": () => new Response(JSON.stringify({ status: "success", data: [fixture.responses.paper.data, response.data] })),
    "GET /api/v1/execution-sessions/bounded-one": () => new Response(JSON.stringify(response)),
  });
  await expect(listExecutionSessions()).resolves.toEqual([fixture.responses.paper.data, response.data]);
  await expect(readExecutionSession("bounded-one")).resolves.toEqual(response.data);
  expect(io.calls).toEqual(["GET /api/v1/execution-sessions", "GET /api/v1/execution-sessions/bounded-one"]);
  expect(io.failures).toEqual([]);
});

type NativeFixture = typeof fixture.responses.partial.data;
const contradictions: [string, (row: NativeFixture) => unknown][] = [
  ["outer account", r => ({ ...r, account: "dhan:foreign" })],
  ["outer run", r => ({ ...r, run_id: "foreign" })],
  ["operator is not the bounded actor", r => ({ ...r, actor: r.autonomy.binding.actor })],
  ["matching malformed operator identities", r => ({ ...r, actor: "operator:invalid", autonomy: { ...r.autonomy, operator: "operator:invalid", grant: { ...r.autonomy.grant, operator: "operator:invalid" } } })],
  ["binding account", r => ({ ...r, autonomy: { ...r.autonomy, binding: { ...r.autonomy.binding, account_id: "foreign" } } })],
  ["binding bounded actor", r => ({ ...r, autonomy: { ...r.autonomy, binding: { ...r.autonomy.binding, actor: r.actor } } })],
  ["configuration binding", r => ({ ...r, config: { ...r.config, policy_revision: "foreign" } })],
  ["grant revision", r => ({ ...r, autonomy: { ...r.autonomy, grant: { ...r.autonomy.grant, binding_revision: "f".repeat(64) } } })],
  ["qualification revision", r => ({ ...r, autonomy: { ...r.autonomy, qualification: { ...r.autonomy.qualification, binding_revision: "f".repeat(64) } } })],
  ["revoked effective grant", r => ({ ...r, autonomy: { ...r.autonomy, grant: { ...r.autonomy.grant, revoked: true } } })],
  ["missing evidence", r => ({ ...r, autonomy: { ...r.autonomy, qualification: null } })],
  ["missing authority projection", r => ({ ...r, autonomy: null })],
  ["unknown authority field", r => ({ ...r, autonomy: { ...r.autonomy, unrestricted: true } })],
  ["unknown admission reason", r => ({ ...r, autonomy: { ...r.autonomy, admission_reason: "new_unknown_authority" } })],
  ["contradictory outer readiness", r => ({ ...r, native_ready: true })],
  ["readiness despite obligations", r => ({ ...r, native_ready: true, autonomy: { ...r.autonomy, native_ready: true } })],
  ["missing obligation", r => ({ ...r, autonomy: { ...r.autonomy, obligations: [] } })],
  ["extra obligation", r => ({ ...r, autonomy: { ...r.autonomy, obligations: ["command-one", "foreign"] } })],
  ["duplicate receipt", r => ({ ...r, autonomy: { ...r.autonomy, commands: [...r.autonomy.commands, ...r.autonomy.commands] } })],
  ["foreign receipt", r => ({ ...r, autonomy: { ...r.autonomy, commands: r.autonomy.commands.map(c => ({ ...c, run_id: "foreign" })) } })],
  ["foreign command account", r => ({ ...r, autonomy: { ...r.autonomy, commands: r.autonomy.commands.map(c => ({ ...c, body: { ...c.body, account_id: "foreign" } })) } })],
  ["unknown command state", r => ({ ...r, autonomy: { ...r.autonomy, commands: r.autonomy.commands.map(c => ({ ...c, state: "flat" })) } })],
  ["obligation protection", r => ({ ...r, protection: "not_granted", autonomy: { ...r.autonomy, protection: "not_granted" } })],
  ["effective authority in configured state", r => ({ ...r, state: "configured", autonomy: { ...r.autonomy, state: "configured" } })],
  ["effective authority in stopped state", r => ({ ...r, state: "entries_stopped", autonomy: { ...r.autonomy, state: "entries_stopped" } })],
  ["terminal receipt concealing known fills", r => ({ ...r, native_ready: true, protection: "not_granted", autonomy: {
    ...r.autonomy, native_ready: true, protection: "not_granted", admission_reason: "canonical_admission_required", obligations: [],
    commands: r.autonomy.commands.map(c => ({ ...c, state: "settled" })),
  } })],
  ["settlement without fill observation", r => ({ ...r, native_ready: true, protection: "not_granted", autonomy: {
    ...r.autonomy, native_ready: true, protection: "not_granted", admission_reason: "canonical_admission_required", obligations: [],
    commands: r.autonomy.commands.map(c => ({ ...c, state: "settled", filled_quantity: undefined })),
  } })],
];
it.each(contradictions)("rejects the whole census for %s, never a filtered partial census", async (_name, alter) => {
  const calls: string[] = []; const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`; calls.push(key);
    if (key !== "GET /api/v1/execution-sessions") { failures.push(key); throw new Error(key); }
    return new Response(JSON.stringify({ status: "success", data: [fixture.responses.paper.data, alter(fixture.responses.partial.data)] }));
  }));
  await expect(listExecutionSessions()).rejects.toThrow(/unknown|unavailable/);
  expect(calls).toHaveLength(1); expect(failures).toEqual([]);
});

it.each(["paper", "ready", "acknowledged", "partial", "stopped", "configured"] as const)("reads untouched captured Core synthetic %s response", async name => {
  const response = fixture.responses[name]; const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`;
    if (key !== `GET /api/v1/execution-sessions/${response.data.run_id}`) { failures.push(key); throw new Error(key); }
    return new Response(JSON.stringify(response));
  }));
  await expect(readExecutionSession(response.data.run_id)).resolves.toEqual(response.data);
  expect(failures).toEqual([]);
});

it.each([
  { ...fixture.responses.paper.data, native_ready: true },
  { ...fixture.responses.paper.data, account: "paper:run:foreign" },
  { ...fixture.responses.paper.data, autonomy: fixture.responses.ready.data.autonomy },
  { ...fixture.responses.mixed.data[1], native_ready: true },
])("preserves Paper and unqualified Live authority constraints %#", async row => {
  const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method} ${url.replace(/^\/ft-api/, "")}`;
    if (key !== "GET /api/v1/execution-sessions") { failures.push(key); throw new Error(key); }
    return new Response(JSON.stringify({ status: "success", data: [row] }));
  }));
  await expect(listExecutionSessions()).rejects.toThrow(/unknown/);
  expect(failures).toEqual([]);
});
