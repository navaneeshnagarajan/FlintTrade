import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { connectionProfiles, createConnection, deleteConnection, isConnectionEtag, readConnectionCollection, updateConnection, type ServiceConnection } from "../serviceConnectionControls";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";

const id = "5a765bd0-48c1-4b8a-8db7-c94633b1abca";
const key = "2c607ae2-54e0-427c-b5cc-6eaf214b5932";
const tag = `"${"a".repeat(64)}"`;
const nextTag = `"${"b".repeat(64)}"`;
const config = { provider_id: "llm:openai", label: "Research", model: "explicit-model", auth_mode: "api_key" };
const row: ServiceConnection = { schema_version: 1, connection_id: id, ...config, endpoint: "https://api.openai.com/v1/chat/completions", credential_configured: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
const snapshot = { etag: tag, connections: [row] };
const reply = (value: unknown, etag = nextTag, status = 200) => new Response(JSON.stringify(value), { status, headers: { ETag: etag } });
beforeEach(() => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-session", username: "synthetic", sessionGeneration: 1 });
  useConnectionStore.setState({ apiKey: "" });
});
afterEach(() => vi.unstubAllGlobals());

it("pins all static setup facts to the actual backend profile declarations without importing a runtime", () => {
  const source = readFileSync(resolve(process.cwd(), "../../core/core/src/flinttrade_core/llm_provider_profiles.py"), "utf8");
  const facts = [...source.matchAll(/LLMProviderProfile\(\s*provider_id=LLMProvider\.(\w+),([\s\S]*?)\n    \),/g)].map(([, id, fields]) => ({
    id: `llm:${id.toLowerCase()}`,
    endpoint: /managed_runtime=True/.test(fields) || /requires_host=True/.test(fields) ? null : fields.match(/endpoint_template="([^"]+)"/)?.[1],
    auth: [...(fields.match(/auth_modes=\(([^)]*)\)/)?.[1] ?? "").matchAll(/"([^"]+)"/g)].map(match => match[1]),
    operatorEndpoint: /requires_host=True/.test(fields),
  }));
  expect(facts).toHaveLength(14);
  expect(connectionProfiles.map(profile => ({ id: profile.id, endpoint: profile.endpoint, auth: profile.auth, operatorEndpoint: profile.operatorEndpoint ?? false })).sort((a, b) => a.id.localeCompare(b.id))).toEqual(facts.sort((a, b) => a.id.localeCompare(b.id)));
});

it.each(["label", "model", "auth_mode", "endpoint", "provider_id", "credential_configured", "created_at", "connection_id"])("refuses a relabelled update response (%s) before any readback", async field => {
  const changed: Record<string, unknown> = { ...row, [field]: field === "credential_configured" ? true : field === "created_at" ? "2025-01-01T00:00:00Z" : field === "connection_id" ? key : "foreign" };
  const fetch = vi.fn(async () => reply(changed)); vi.stubGlobal("fetch", fetch);
  const { provider_id: _provider, ...changes } = config;
  await expect(updateConnection(snapshot, row, changes, key)).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(["", 'W/"weak"', '"one", "two"', '"bad\\value\n"', "*", '"unclosed'])("rejects invalid or weak collection tags before mutation (%s)", async etag => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect(isConnectionEtag(etag)).toBe(false);
  await expect(createConnection({ connections: [], etag }, config, key)).rejects.toThrow();
  expect(fetch.mock.calls.length).toBe(0);
});

it.each([
  { connections: [row, row] }, { connections: [row, null] }, { connections: "wrong" }, [], null,
  { connections: [{ ...row, credential: "synthetic-only" }] },
  { connections: [{ ...row, endpoint: "https://foreign.invalid" }] },
  { connections: [{ ...row, auth_mode: "invented" }] },
])("rejects an entire malformed collection rather than filtering it", async body => {
  vi.stubGlobal("fetch", vi.fn(async () => reply(body)));
  await expect(readConnectionCollection()).rejects.toThrow();
});

it("refuses deletion acknowledgement while the exact record remains in readback", async () => {
  const fetch = vi.fn(async (_url: string, init: RequestInit) => reply(init.method === "DELETE" ? { deleted: true } : { connections: [row] }));
  vi.stubGlobal("fetch", fetch);
  await expect(deleteConnection(snapshot, row, key)).rejects.toThrow("Deletion could not be verified");
  expect(fetch).toHaveBeenCalledTimes(2);
});

it.each([
  { ...config, provider_id: "invented" }, { ...config, endpoint: "https://foreign.invalid" },
  { ...config, auth_mode: "invented" }, { ...config, credential: "" },
  { ...config, credential: "synthetic-only", clear_credential: true },
  { ...config, connection_id: id }, { ...config, label: "\ninvalid" },
  { ...config, provider_id: "llm:custom", endpoint: "https://user:pass@synthetic.invalid" },
  { ...config, provider_id: "llm:custom", endpoint: "https://synthetic.invalid?credential=x" },
])("rejects malformed mutation input before transport without coercion", async configuration => {
  const fetch = vi.fn(async () => reply(row)); vi.stubGlobal("fetch", fetch);
  await expect(createConnection({ connections: [], etag: tag }, configuration, key)).rejects.toThrow();
  expect(fetch.mock.calls.length).toBe(0);
});

it("rejects a target absent from the exact reviewed collection before mutation", async () => {
  const fetch = vi.fn(async () => reply({ deleted: true })); vi.stubGlobal("fetch", fetch);
  await expect(deleteConnection({ etag: tag, connections: [] }, row, key)).rejects.toThrow();
  expect(fetch.mock.calls.length).toBe(0);
});

it("refuses an unchanged write revision before readback", async () => {
  const fetch = vi.fn(async () => reply(row, tag)); vi.stubGlobal("fetch", fetch);
  await expect(createConnection({ connections: [], etag: tag }, config, key)).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(["item", "collection"])("refuses a later collection revision at the %s readback without resending", async phase => {
  let requests = 0;
  const fetch = vi.fn(async (_url: string, init: RequestInit) => {
    requests += 1;
    if (init.method === "POST") return reply(row);
    return reply(requests === 2 ? row : { connections: [row] }, requests === (phase === "item" ? 2 : 3) ? tag : nextTag);
  });
  vi.stubGlobal("fetch", fetch);
  await expect(createConnection({ connections: [], etag: tag }, config, key)).rejects.toThrow();
  expect(fetch.mock.calls.filter(([, init]) => init.method === "POST")).toHaveLength(1);
  expect(requests).toBe(phase === "item" ? 2 : 3);
});
