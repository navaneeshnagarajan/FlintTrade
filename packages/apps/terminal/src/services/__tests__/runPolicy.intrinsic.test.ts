import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { createRunPolicyClient, type ExactControlSelector } from "../runPolicy";
import type { RunScope } from "../runPolicyTransport";
import { contradict, contradictions, fixtures, registerPolicy, response, transportFailures } from "./runPolicy.intrinsicTestUtils";
import coreFixtures from "./runPolicy.core-fixture.json";

beforeEach(() => {
  transportFailures.length = 0;
  useAuthStore.setState(state => ({ status: "logged-in", token: "synthetic-intrinsic", username: "operator", sessionGeneration: state.sessionGeneration + 1 }));
});
afterEach(() => { vi.unstubAllGlobals(); expect(transportFailures).toEqual([]); });

it.each(fixtures)("accepts untouched real-owner $category unissued and issued reads and confirm", async fixture => {
  const paths = registerPolicy(fixture);
  const client = createRunPolicyClient(fixture.base.scope as RunScope);
  try {
    expect(await client.readControl(fixture.selector as ExactControlSelector)).toEqual(fixture.before);
    const view = await client.preview(fixture.proposal);
    expect((await client.confirm(view)).exact_control).toEqual(fixture.after.exact_control);
    expect(await client.readControl(fixture.selector as ExactControlSelector)).toEqual(fixture.after);
    expect(paths.calls).toEqual([`GET ${paths.exact}`, `POST ${paths.base}/preview`, `POST ${paths.base}/confirm`, `GET ${paths.exact}`, `GET ${paths.exact}`]);
  } finally { client.dispose(); }
});

it.each(contradictions.flatMap(fault => ["selected", "configuration"].map(seam => ({ ...fault, seam }))))("refuses $category $field contradiction before $seam publication", async ({ seam, ...fault }) => {
  const changed = contradict(fault.fixture.after, fault);
  const paths = registerPolicy(fault.fixture, { selected: changed, base: { ...fault.fixture.base, exact_control: changed.exact_control } });
  const client = createRunPolicyClient(fault.fixture.base.scope as RunScope);
  try {
    await expect(seam === "selected" ? client.readControl(fault.fixture.selector as ExactControlSelector) : client.read()).rejects.toMatchObject({ outcome: "unknown" });
    expect(paths.calls).toEqual([`GET ${seam === "selected" ? paths.exact : paths.base}`]);
  } finally { client.dispose(); }
});

it.each(contradictions.flatMap(fault => ["ACK", "GET", "both"].map(seam => ({ ...fault, seam }))))("keeps $category $field contradictory $seam unverified and requires explicit read", async ({ seam, ...fault }) => {
  const { fixture } = fault;
  const paths = registerPolicy(fixture, {
    ack: seam === "GET" ? fixture.confirmed : contradict(fixture.confirmed, fault),
    after: seam === "ACK" ? fixture.after : contradict(fixture.after, fault),
  });
  const client = createRunPolicyClient(fixture.base.scope as RunScope);
  try {
    await client.readControl(fixture.selector as ExactControlSelector);
    const view = await client.preview(fixture.proposal);
    await expect(client.confirm(view)).rejects.toMatchObject({ outcome: "unknown" });
    await expect(client.preview(fixture.proposal)).rejects.toThrow(/read/i);
    await expect(client.confirm(view)).rejects.toThrow(/consumed|cancelled/i);
    expect(paths.calls).toEqual([`GET ${paths.exact}`, `POST ${paths.base}/preview`, `POST ${paths.base}/confirm`, `GET ${paths.exact}`]);
    if (seam === "ACK") expect(await client.readControl(fixture.selector as ExactControlSelector)).toEqual(fixture.after);
    else {
      await expect(client.readControl(fixture.selector as ExactControlSelector)).rejects.toMatchObject({ outcome: "unknown" });
      await expect(client.preview(fixture.proposal)).rejects.toThrow(/read/i);
    }
    expect(paths.calls).toHaveLength(5);
  } finally { client.dispose(); }
});

const identitySelectors = contradictions.filter(fault => ["identity.trial", "identity.connection_id"].includes(fault.field));
it.each(identitySelectors.flatMap(fault => ["selected", "configuration", "preview"].map(seam => ({ ...fault, seam }))))("rejects unissued $category $field contradiction at $seam without a confirm", async ({ seam, ...fault }) => {
  const { fixture } = fault;
  const changed = contradict(fixture.before, fault);
  const paths = registerPolicy(fixture, {
    selected: changed, base: { ...fixture.base, exact_control: changed.exact_control },
    preview: { ...fixture.preview, target_identity: changed.exact_control.identity },
  });
  const client = createRunPolicyClient(fixture.base.scope as RunScope);
  try {
    const work = seam === "preview" ? client.preview(fixture.proposal)
      : seam === "selected" ? client.readControl(fixture.selector as ExactControlSelector) : client.read();
    await expect(work).rejects.toMatchObject({ outcome: "unknown" });
    expect(paths.calls).toEqual([seam === "preview" ? `POST ${paths.base}/preview` : `GET ${seam === "selected" ? paths.exact : paths.base}`]);
  } finally { client.dispose(); }
});

const access = coreFixtures.find(fixture => fixture.proposal.action === "access")!;
const heldCases = [
  ...fixtures.map(fixture => ({ ...fixture, scope: fixture.base.scope, selector: fixture.selector as ExactControlSelector | null })),
  { ...access, category: "general-access", scope: access.before.scope, selector: null },
].flatMap(fixture => ["ACK", "GET"].flatMap(held => ["cancel", "keep"].map(retirement => ({ ...fixture, held, retirement }))));

it.each(heldCases)("$category public $retirement during held $held never rewinds or repeats the accepted write", async fixture => {
  const base = `/v1/model-runs/${fixture.scope.run_id}/configuration`;
  const exact = fixture.selector ? `${base}/control?${new URLSearchParams(fixture.selector)}` : base;
  const calls: string[] = [];
  let release!: () => void;
  let entered!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const reached = new Promise<void>(resolve => { entered = resolve; });
  let acceptedWrites = 0;
  let heldOnce = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init.method} ${path}`);
    try {
      const headers = new Headers(init.headers);
      expect(headers.get("Authorization")).toBe("Bearer synthetic-intrinsic");
      expect(headers.has("X-API-Key")).toBe(false);
      if (init.method === "POST" && path === `${base}/preview`) {
        expect(JSON.parse(String(init.body))).toEqual(fixture.proposal);
        return response(fixture.preview);
      }
      if (init.method === "POST" && path === `${base}/confirm`) {
        expect(JSON.parse(String(init.body))).toEqual({ ...fixture.proposal, confirmation: fixture.preview.confirmation });
        acceptedWrites++;
        if (fixture.held === "ACK") { entered(); await held; }
        return response(fixture.confirmed);
      }
      if (init.method === "GET" && path === exact) {
        if (fixture.held === "GET" && !heldOnce) { heldOnce = true; entered(); await held; }
        return response(fixture.after);
      }
      throw new Error(`Unregistered ${init.method} ${path}`);
    } catch (error) { transportFailures.push(String(error)); throw error; }
  }));
  const client = createRunPolicyClient(fixture.scope as RunScope);
  try {
    const preview = await client.preview(fixture.proposal);
    const result = client.confirm(preview).then(value => ({ value, error: null }), (error: unknown) => ({ value: null, error }));
    await reached;
    expect(acceptedWrites).toBe(1);
    if (fixture.retirement === "cancel") client.cancel();
    release();
    const settled = await result;
    if (fixture.retirement === "cancel") {
      expect(settled.value).toBeNull();
      expect(settled.error).toMatchObject({ outcome: "retired" });
      await expect(client.preview(fixture.proposal)).rejects.toThrow(/read/i);
    } else {
      expect(settled.error).toBeNull();
      expect(settled.value).toMatchObject(fixture.after);
    }
    await expect(client.confirm(preview)).rejects.toThrow(/consumed|cancelled/i);
    expect(calls).toEqual([`POST ${base}/preview`, `POST ${base}/confirm`, `GET ${exact}`]);
    // This is an independent observation, not rollback of the accepted write.
    expect(await (fixture.selector ? client.readControl(fixture.selector) : client.read())).toEqual(fixture.after);
    expect(acceptedWrites).toBe(1);
    expect(calls).toEqual([`POST ${base}/preview`, `POST ${base}/confirm`, `GET ${exact}`, `GET ${exact}`]);
  } finally { release(); client.dispose(); }
});
