import { z } from "zod";
import { buildHeaders, getBase, isDemoAuthSession } from "./ftApi.helpers";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore, type AuthSessionFence } from "@/stores/authStore";

const uuid = z.string().regex(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
const text = (maximum: number) => z.string().max(maximum).refine(value => !/[\u0000-\u001f\u007f-\u009f]/u.test(value));
const Connection = z.strictObject({
  schema_version: z.literal(1), connection_id: uuid, provider_id: z.string(),
  label: text(128).refine(value => !!value.trim()), model: text(256),
  endpoint: z.string().nullable(), auth_mode: z.string().nullable(), credential_configured: z.boolean(),
  created_at: z.iso.datetime(), updated_at: z.iso.datetime(),
});
export const OAuthCapabilities = z.strictObject({ configured: z.boolean(), providers: z.array(z.enum(["llm:openai", "llm:openrouter"])).max(2), desktop_activation: z.literal(true).optional() }).refine(value => value.configured || (value.providers.length === 0 && value.desktop_activation === true));
const Collection = z.strictObject({ connections: z.array(Connection).max(128), oauth: OAuthCapabilities.optional() });
const Changes = z.strictObject({
  label: text(128).refine(value => !!value.trim()), model: text(256), auth_mode: z.string().nullable(), endpoint: z.string().optional(),
  credential: z.string().min(1).refine(value => new TextEncoder().encode(value).length <= 16 * 1024).optional(), clear_credential: z.literal(true).optional(),
});
const Configuration = Changes.omit({ clear_credential: true }).extend({ provider_id: z.string() });
export type ServiceConnection = z.infer<typeof Connection>;
export interface ServiceConnectionCollection { connections: ServiceConnection[]; etag: string; oauth?: z.infer<typeof OAuthCapabilities> }
export interface ConnectionConfiguration { provider_id: string; label: string; model: string; auth_mode: string | null; endpoint?: string }
export type ConnectionChanges = Omit<ConnectionConfiguration, "provider_id"> & { credential?: string; clear_credential?: true };
export interface ConnectionProfile { id: string; name: string; endpoint: string | null; auth: readonly string[]; operatorEndpoint?: boolean; protocols: string }

/** Static setup facts mirror core llm_provider_profiles, not measured readiness. */
export const connectionProfiles: readonly ConnectionProfile[] = [
  { id: "llm:openai", name: "OpenAI", endpoint: "https://api.openai.com/v1/chat/completions", auth: ["api_key", "chatgpt_oauth"], protocols: "openai_responses / assistant; openai_decisions / task_router (API key); chatgpt_responses / assistant (chatgpt_oauth). Responses: https://api.openai.com/v1/responses. Decisions: https://api.openai.com/v1/decisions." },
  { id: "llm:anthropic", name: "Anthropic", endpoint: "https://api.anthropic.com/v1/messages", auth: ["api_key", "oauth"], protocols: "anthropic_messages / assistant with api_key only. Stored oauth is not supported by R1 dispatch." },
  { id: "llm:openrouter", name: "OpenRouter", endpoint: "https://openrouter.ai/api/v1/chat/completions", auth: ["api_key"], protocols: "openrouter_chat / assistant. Admission must explicitly pin the downstream provider; no fallback." },
  { id: "llm:grok", name: "Grok (xAI)", endpoint: "https://api.x.ai/v1/chat/completions", auth: ["api_key"], protocols: "xai_responses / assistant at https://api.x.ai/v1/responses; visible-output cap only." },
  { id: "llm:custom", name: "Custom / operator-hosted Unsloth", endpoint: null, auth: ["api_key"], operatorEndpoint: true, protocols: "unsloth_chat / assistant only after separate qualification. Core appends /v1/chat/completions to this exact base URL. No runtime is installed or started." },
  { id: "llm:ollama", name: "Ollama (Managed)", endpoint: null, auth: [], protocols: "No R1 advisory adapter. Saving does not start the managed runtime." },
  { id: "llm:hermes", name: "Hermes (Nous)", endpoint: null, auth: [], operatorEndpoint: true, protocols: "No R1 advisory adapter. Configuration alone does not start an agent runtime." },
  { id: "llm:gemini", name: "Google Gemini", endpoint: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", auth: ["api_key"], protocols: "No R1 advisory adapter." },
  { id: "llm:deepseek", name: "DeepSeek", endpoint: "https://api.deepseek.com/v1/chat/completions", auth: ["api_key"], protocols: "No R1 advisory adapter." },
  { id: "llm:groq", name: "Groq", endpoint: "https://api.groq.com/openai/v1/chat/completions", auth: ["api_key"], protocols: "No R1 advisory adapter." },
  { id: "llm:mistral", name: "Mistral", endpoint: "https://api.mistral.ai/v1/chat/completions", auth: ["api_key"], protocols: "No R1 advisory adapter." },
  { id: "llm:together", name: "Together AI", endpoint: "https://api.together.xyz/v1/chat/completions", auth: ["api_key"], protocols: "No R1 advisory adapter." },
  { id: "llm:nvidia", name: "NVIDIA NIM", endpoint: "https://integrate.api.nvidia.com/v1/chat/completions", auth: ["api_key"], protocols: "No R1 advisory adapter." },
  { id: "llm:cerebras", name: "Cerebras", endpoint: "https://api.cerebras.ai/v1/chat/completions", auth: ["api_key"], protocols: "No R1 advisory adapter." },
];

export class ConnectionControlError extends Error {}
function invalid(message = "Connection response is invalid; refresh before continuing."): never { throw new ConnectionControlError(message); }
function parse<T>(schema: z.ZodType<T>, data: unknown): T {
  const result = schema.safeParse(data);
  if (!result.success) return invalid();
  return result.data;
}
export function isOperatorEndpoint(value: string): boolean {
  if (!value || value.length > 2048 || /[^\x21-\x7e]|[\\?#]/.test(value) || /%(?![a-f0-9]{2})/i.test(value)) return false;
  try {
    const url = new URL(value);
    return /^https?:\/\//i.test(value) && !!url.hostname && !url.username && !url.password && !url.host.includes("%") && !url.host.endsWith(":");
  } catch { return false; }
}
function profileFor(provider: string): ConnectionProfile {
  const profile = connectionProfiles.find(item => item.id === provider);
  if (!profile) return invalid("Unsupported connection provider.");
  return profile;
}
function validateStored(row: ServiceConnection): ServiceConnection {
  const profile = profileFor(row.provider_id);
  if ((profile.operatorEndpoint ? typeof row.endpoint !== "string" || !isOperatorEndpoint(row.endpoint) : row.endpoint !== profile.endpoint)
    || (profile.auth.length ? !profile.auth.includes(row.auth_mode ?? "") : row.auth_mode !== null || row.credential_configured)
    || Date.parse(row.updated_at) < Date.parse(row.created_at)) invalid();
  return row;
}
function expectedEndpoint(configuration: ConnectionConfiguration) {
  const profile = profileFor(configuration.provider_id);
  return profile.operatorEndpoint ? configuration.endpoint : profile.endpoint;
}
function validateChanges(provider: string, changes: ConnectionChanges) {
  const profile = profileFor(provider);
  if ((profile.operatorEndpoint ? typeof changes.endpoint !== "string" || !isOperatorEndpoint(changes.endpoint) : changes.endpoint !== undefined)
    || (profile.auth.length ? !profile.auth.includes(changes.auth_mode ?? "") : changes.auth_mode !== null || changes.credential !== undefined || changes.clear_credential)
    || (changes.credential !== undefined && changes.clear_credential)) invalid("Invalid connection configuration. Check the declared destination and authentication.");
}
function validateTarget(snapshot: ServiceConnectionCollection, target: ServiceConnection, key: string) {
  if (!isConnectionEtag(snapshot.etag) || !uuid.safeParse(key).success || !uuid.safeParse(target.connection_id).success
    || !snapshot.connections.some(row => JSON.stringify(row) === JSON.stringify(target))) invalid("Read the exact collection and target before submitting a new action.");
  validateStored(parse(Connection, target));
}
export function isConnectionEtag(value: string): boolean {
  // Collection tags are opaque SHA-256 tags, NOT the numeric policy revisions.
  return value.length <= 4096 && /^"[\x21\x23-\x7e\x80-\xff]*"$/.test(value);
}
function assertSession(fence: AuthSessionFence) {
  if (!isAuthSessionFenceCurrent(fence)) invalid("Session changed; the connection response was retired.");
}
async function request(path: string, method: "GET" | "POST" | "PATCH" | "DELETE", fence: AuthSessionFence, body?: unknown, etag?: string, key?: string) {
  assertSession(fence);
  if (isDemoAuthSession() || useAuthStore.getState().status !== "logged-in" || !useAuthStore.getState().token) invalid("Service setup requires an installed operator session.");
  const response = await fetch(`${getBase()}/v1/services/connections${path}`, {
    method, cache: "no-store", redirect: "error", headers: {
      ...buildHeaders(body !== undefined), ...(etag ? { "If-Match": etag } : {}), ...(key ? { "Idempotency-Key": key } : {}),
    }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  }).catch(() => invalid("Connection request outcome unavailable. Refresh and review before explicitly submitting again."));
  assertSession(fence);
  // Never reflect response bodies or network exceptions into UI/logs: a faulty
  // server can echo a submitted credential, including in error envelopes.
  if (!response.ok) invalid(response.status === 412 ? "Connection revision conflict. Refresh and review before explicitly submitting again." : `Service connection request refused (${response.status}). Refresh before continuing.`);
  let data: unknown;
  try { data = await response.json(); } catch { return invalid(); }
  assertSession(fence);
  const revision = response.headers.get("ETag") ?? "";
  if (!isConnectionEtag(revision)) invalid("Connection revision unavailable; refresh before continuing.");
  if (method !== "GET" && revision === etag) invalid("Connection mutation revision did not advance. Refresh before continuing.");
  return { data, etag: revision };
}
export async function readConnectionCollection(fence = captureAuthSessionFence()): Promise<ServiceConnectionCollection> {
  const result = await request("", "GET", fence);
  const data = parse(Collection, result.data);
  if (new Set(data.connections.map(row => row.connection_id)).size !== data.connections.length) invalid();
  data.connections.forEach(validateStored);
  return { ...data, etag: result.etag };
}
export async function createConnection(snapshot: ServiceConnectionCollection, configuration: ConnectionConfiguration & { credential?: string }, key: string): Promise<ServiceConnectionCollection> {
  if (!isConnectionEtag(snapshot.etag) || !uuid.safeParse(key).success) invalid("Read the collection before submitting a new action.");
  configuration = parse(Configuration, configuration);
  validateChanges(configuration.provider_id, configuration);
  const fence = captureAuthSessionFence();
  const written = await request("", "POST", fence, configuration, snapshot.etag, key);
  const row = validateStored(parse(Connection, written.data));
  if (snapshot.connections.some(item => item.connection_id === row.connection_id)
    || row.provider_id !== configuration.provider_id || row.label !== configuration.label || row.model !== configuration.model || row.auth_mode !== configuration.auth_mode
    || row.endpoint !== expectedEndpoint(configuration) || row.credential_configured !== (configuration.credential !== undefined)) invalid("Connection identity or configuration mismatch; refresh before continuing.");
  return verifyReadback(row, written.etag, fence);
}
async function verifyReadback(row: ServiceConnection, etag: string, fence: AuthSessionFence) {
  const item = await request(`/${row.connection_id}`, "GET", fence);
  if (item.etag !== etag || JSON.stringify(parse(Connection, item.data)) !== JSON.stringify(row)) invalid("Connection changed during readback. Refresh before continuing.");
  const collection = await readConnectionCollection(fence);
  const found = collection.connections.find(value => value.connection_id === row.connection_id);
  if (collection.etag !== etag || JSON.stringify(found) !== JSON.stringify(row)) invalid("Connection changed during collection readback. Refresh before continuing.");
  return collection;
}
export async function updateConnection(snapshot: ServiceConnectionCollection, target: ServiceConnection, changes: ConnectionChanges, key: string): Promise<ServiceConnectionCollection> {
  validateTarget(snapshot, target, key);
  changes = parse(Changes, changes);
  validateChanges(target.provider_id, changes);
  const fence = captureAuthSessionFence();
  const written = await request(`/${target.connection_id}`, "PATCH", fence, changes, snapshot.etag, key);
  const row = validateStored(parse(Connection, written.data));
  const endpoint = changes.endpoint ?? target.endpoint;
  const credentialExpected = changes.credential !== undefined || (!changes.clear_credential && endpoint === target.endpoint && changes.auth_mode === target.auth_mode && target.credential_configured);
  if (row.connection_id !== target.connection_id || row.provider_id !== target.provider_id || row.label !== changes.label || row.model !== changes.model || row.auth_mode !== changes.auth_mode
    || row.endpoint !== endpoint || row.credential_configured !== credentialExpected || row.created_at !== target.created_at || Date.parse(row.updated_at) < Date.parse(target.updated_at)) invalid("Connection identity or configuration mismatch; refresh before continuing.");
  return verifyReadback(row, written.etag, fence);
}
export async function deleteConnection(snapshot: ServiceConnectionCollection, target: ServiceConnection, key: string): Promise<ServiceConnectionCollection> {
  validateTarget(snapshot, target, key);
  const fence = captureAuthSessionFence();
  const written = await request(`/${target.connection_id}`, "DELETE", fence, {}, snapshot.etag, key);
  parse(z.strictObject({ deleted: z.literal(true) }), written.data);
  const collection = await readConnectionCollection(fence);
  if (collection.etag !== written.etag || collection.connections.some(row => row.connection_id === target.connection_id)) invalid("Deletion could not be verified. Refresh before continuing.");
  return collection;
}
