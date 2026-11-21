import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { createNativeV2Client, ExecutionSessionError, NativeV2PreflightError, listExecutionSessions, readExecutionSession } from "../executionSessions";
import fixture from "./fixtures/native-v2-captured-v2.json";

let generation = 9000;
beforeEach(() => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-studio", username: "mounted-operator",
    sessionGeneration: ++generation });
  const account = { account_id: "Mounted", broker: "dhan", source: "native" as const,
    label: "Synthetic inert account", status: "connected" as const, is_primary: true,
    connected_at: null, error_message: null };
  useBrokerStore.setState({ accounts: [account], activeAccountId: brokerAccountKey(account) });
});
afterEach(() => { vi.unstubAllGlobals(); });

it("configures through the public client with unchanged captured DTOs and exact independent readback", async () => {
  const samples = fixture.samples.filter(row => row.case.endsWith(
    "test_normal_factory_mounts_versioned_configuration_without_authority"));
  const requested = samples.find(row => row.method === "POST")!;
  const calls: string[] = []; const failures: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init?.method} ${path}`);
    try {
      const sample = samples.find(row => row.path === path && row.method === init?.method);
      expect(sample).toBeDefined();
      expect(Object.fromEntries(new Headers(init?.headers))).toEqual(init?.method === "POST"
        ? { authorization: "Bearer synthetic-studio", "content-type": "application/json" }
        : { authorization: "Bearer synthetic-studio" });
      if (init?.body) expect(JSON.parse(String(init.body))).toEqual(requested.request_json);
      return new Response(sample!.body, { status: sample!.status });
    } catch (error) { failures.push(error); throw error; }
  }));
  const client = createNativeV2Client();
  try {
    const observed = await client.configure(requested.request_json);
    expect(observed.view).toEqual(JSON.parse(requested.body).data);
    expect(observed.session.autonomy_v2).toEqual(observed.view);
    expect(calls).toEqual(["POST /api/v1/execution-sessions/native-v2",
      "GET /api/v1/execution-sessions/mounted-native/autonomy-v2",
      "GET /api/v1/execution-sessions/mounted-native"]);
    expect(failures).toEqual([]);
  } finally { client.dispose(); }
});

it("decodes both actual normal-factory nominal cash/options session projections and their entire censuses", async () => {
  for (const sample of fixture.samples.filter(row => row.status === 200
    && row.method === "GET" && !row.path.includes("autonomy-v2"))) {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method} ${url}`);
      expect(url.replace(/^\/ft-api/, "")).toBe(sample.path);
      return new Response(sample.body);
    }));
    const raw = JSON.parse(sample.body);
    const result = sample.path.endsWith("/execution-sessions")
      ? await listExecutionSessions() : await readExecutionSession("mounted-native");
    expect(result).toEqual(raw.data);
    expect(calls).toHaveLength(1);
  }
});

function captured(caseName: string, method: string, path: string, last = false) {
  const rows = fixture.samples.filter(row => row.case.endsWith(caseName) && row.method === method && row.path === path);
  expect(rows.length).toBeGreaterThan(0);
  return rows[last ? rows.length - 1 : 0]!;
}
const base = "/api/v1/execution-sessions";
const exact = `${base}/mounted-native`;

it("keeps completed local preflight distinct from an actual server refusal and sends no default permission", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const client = createNativeV2Client();
  try {
    await expect(client.configure({ schema_version: "2", config: {} })).rejects.toBeInstanceOf(NativeV2PreflightError);
    expect(fetcher).not.toHaveBeenCalled();
    const sample = captured("test_empty_qualification_evaluates_owners_without_provider_reads", "POST", `${exact}/autonomy-v2/qualify`);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(sample.body, { status: sample.status })));
    const configured = fixture.samples.find(row => row.method === "POST" && row.path === `${base}/native-v2`)!;
    const refused = await client.configure(configured.request_json).catch(error => error);
    expect(refused).toBeInstanceOf(ExecutionSessionError);
    expect(refused).not.toBeInstanceOf(NativeV2PreflightError);
    expect(refused).toMatchObject({ outcome: "refused" });
    expect(fetch).toHaveBeenCalledTimes(1);
  } finally { client.dispose(); }
});

it.each(["account switch", "account A-B-A", "operator generation", "dispose"])(
  "aborts and suppresses a held read after %s, even when the transport delivers its body late", async retirement => {
    const sample = captured("test_normal_factory_mounts_versioned_configuration_without_authority", "GET", `${exact}/autonomy-v2`);
    let release: ((response: Response) => void) | undefined;
    let signal: AbortSignal | null | undefined;
    const fetcher = vi.fn((_url: string, init?: RequestInit) => {
      signal = init?.signal;
      return new Promise<Response>(resolve => { release = resolve; });
    });
    vi.stubGlobal("fetch", fetcher);
    const client = createNativeV2Client();
    const pending = client.read("mounted-native");
    const rejected = expect(pending).rejects.toMatchObject({ outcome: "retired" });
    expect(release).toBeTypeOf("function");
    if (retirement.startsWith("account")) {
      const original = useBrokerStore.getState().activeAccountId!;
      useBrokerStore.getState().setActiveAccount("native:dhan:Other");
      if (retirement === "account A-B-A") useBrokerStore.getState().setActiveAccount(original);
    } else if (retirement === "operator generation") useAuthStore.setState({ sessionGeneration: ++generation });
    else client.dispose();
    expect(signal?.aborted).toBe(true);
    release?.(new Response(sample.body));
    await rejected;
    expect(fetcher).toHaveBeenCalledTimes(1);
    client.dispose();
  },
);

it("stops an ungranted stale run using its actual generation without implying custody settlement", async () => {
  const caseName = "test_freshness_is_local_and_stale_account_does_not_block_stop";
  const initial = captured(caseName, "GET", exact);
  const stop = captured(caseName, "POST", `${exact}/stop`);
  const finalView = captured(caseName, "GET", `${exact}/autonomy-v2`, true);
  const finalSession = captured(caseName, "GET", exact, true);
  const calls: string[] = []; const failures: unknown[] = [];
  let stopped = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init?.method} ${path}`);
    try {
      if (init?.method === "POST") {
        expect(path).toBe(`${exact}/stop`);
        expect(JSON.parse(String(init.body))).toEqual(stop.request_json);
        stopped = true; return new Response(stop.body);
      }
      expect([exact, `${exact}/autonomy-v2`]).toContain(path);
      return new Response(path.endsWith("autonomy-v2") ? finalView.body : stopped ? finalSession.body : initial.body);
    } catch (error) { failures.push(error); throw error; }
  }));
  const target = await readExecutionSession("mounted-native");
  const client = createNativeV2Client();
  try {
    expect(target.autonomy_v2).toMatchObject({ grant: null, effective_authority: "none", observation_freshness: "stale" });
    const result = await client.stop(target);
    expect(result.session).toEqual(JSON.parse(finalSession.body).data);
    expect(result.view).toMatchObject({ entry_state: "retired", duty: null, effective_authority: "none" });
    await expect(client.stop(target)).rejects.toThrow(/already sent/);
    expect(calls).toEqual([`GET ${exact}`, `POST ${exact}/stop`, `GET ${exact}/autonomy-v2`, `GET ${exact}`]);
    expect(failures).toEqual([]);
  } finally { client.dispose(); }
});

it.each(["malformed acknowledgement", "successful-HTTP error envelope", "readback unavailable"])(
  "preserves %s as unknown after a possible configure and never retries", async fault => {
    const caseName = "test_normal_factory_mounts_versioned_configuration_without_authority";
    const configured = captured(caseName, "POST", `${base}/native-v2`);
    const view = captured(caseName, "GET", `${exact}/autonomy-v2`);
    const shared = captured(caseName, "GET", exact);
    const calls: string[] = []; const failures: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^\/ft-api/, ""); calls.push(`${init?.method} ${path}`);
      try {
        if (init?.method === "POST") {
          expect(path).toBe(`${base}/native-v2`);
          // Labelled adversarial mutations of a real response, never positive evidence.
          return new Response(fault === "readback unavailable" ? configured.body : JSON.stringify(
            fault === "successful-HTTP error envelope"
              ? { status: "error", code: "An installed operator session is required." }
              : { status: "success", data: {} }));
        }
        expect([exact, `${exact}/autonomy-v2`]).toContain(path);
        if (fault === "readback unavailable") throw new TypeError("synthetic lost readback");
        return new Response(path === exact ? shared.body : view.body);
      } catch (error) {
        if (error instanceof TypeError && error.message === "synthetic lost readback") throw error;
        failures.push(error); throw error;
      }
    }));
    const client = createNativeV2Client();
    try {
      await expect(client.configure(configured.request_json)).rejects.toMatchObject({ outcome: "unknown" });
      await expect(client.configure(configured.request_json)).rejects.toThrow(/already sent/);
      expect(calls).toEqual(fault === "readback unavailable"
        ? [`POST ${base}/native-v2`, `GET ${exact}/autonomy-v2`]
        : [`POST ${base}/native-v2`, `GET ${exact}/autonomy-v2`, `GET ${exact}`]);
      expect(failures).toEqual([]);
    } finally { client.dispose(); }
  },
);
