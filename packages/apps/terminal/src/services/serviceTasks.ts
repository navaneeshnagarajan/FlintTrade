import { z } from "zod";
import { buildHeaders, getBase } from "./ftApi.helpers";
import { captureAuthSessionFence, isAuthSessionFenceCurrent } from "@/stores/authStore";
import { isPublicDemoBuild } from "@/lib/demoSession";
import { captureOperatorIncidentScope, isOperatorIncidentScopeCurrent } from "@/lib/operatorIncidentScope";

export { readConnectionCollection as readServiceConnections } from "./serviceConnectionControls";
const Receipt = z.looseObject({ request_id: z.string(), outcome: z.string(), code: z.string().optional(), output: z.string().optional(), output_digest: z.string().regex(/^[0-9a-f]{64}$/).optional() });
export type ServiceTaskReceipt = z.infer<typeof Receipt>;
// Weak keys do not own/retain answer text. Values carry only the original
// authority fence; copying or serialising a receipt cannot transfer its text.
const transientOwners = new WeakMap<ServiceTaskReceipt, () => void>();
export interface ServiceTask {
  request_id: string; mode: "fixed" | "automatic";
  selection: { connection_id: string; connection_revision: string; model: string; effort: string } | null;
  prompt: string; classification: "public" | "private"; context_refs: string[];
  purpose: "assistant"; deadline_ms: number; max_output_tokens: number; required_hard_controls: string[];
}
async function request(path: string, method: "GET" | "POST" | "PUT", body?: unknown, etag?: string) {
  if (isPublicDemoBuild()) throw new Error("Provider tasks are unavailable in the frozen public preview.");
  const fence = captureAuthSessionFence();
  const response = await fetch(`${getBase()}/v1/services/connections${path}`, { method, headers: { ...buildHeaders(body !== undefined), ...(etag ? { "If-Match": etag } : {}) }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}), cache: "no-store" });
  const data: unknown = await response.json();
  if (!isAuthSessionFenceCurrent(fence)) throw new Error("Session changed; this response was retired.");
  if (!response.ok) {
    const parsed = z.object({ error: z.string() }).safeParse(data);
    throw new Error(parsed.success ? parsed.data.error : `Service request refused (${response.status})`);
  }
  return { data, etag: response.headers.get("ETag") ?? "" };
}

function captureTaskFence(isCurrent?: () => boolean) {
  const auth = captureAuthSessionFence();
  const local = captureOperatorIncidentScope();
  return () => {
    if (!isAuthSessionFenceCurrent(auth) || !isOperatorIncidentScopeCurrent(local) || isCurrent?.() === false) {
      throw new Error("Task scope changed; this receipt was retired.");
    }
  };
}
export async function readServiceTask(id: string, transient?: ServiceTaskReceipt, isCurrent?: () => boolean): Promise<ServiceTaskReceipt> {
  const assertCurrent = captureTaskFence(isCurrent);
  const assertOriginal = transient?.output !== undefined ? transientOwners.get(transient) : undefined;
  if (transient?.output !== undefined && !assertOriginal) throw new Error("Transient answer scope unavailable; output retired.");
  assertCurrent();
  assertOriginal?.();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(id)) throw new Error("Request identity must be a canonical UUID4.");
  const result = Receipt.parse((await request(`/tasks/${id}`, "GET")).data);
  assertCurrent();
  if (result.request_id !== id) throw new Error("Receipt identity mismatch.");
  if (result.output !== undefined) throw new Error("Durable task receipt unexpectedly contains plaintext; outcome unverified.");
  const reconciled = transient ? await reconcileOutput(transient, result) : result;
  assertCurrent();
  assertOriginal?.();
  if (reconciled.output !== undefined) transientOwners.set(reconciled, assertOriginal ?? assertCurrent);
  return reconciled;
}
async function reconcileOutput(transient: ServiceTaskReceipt, durable: ServiceTaskReceipt): Promise<ServiceTaskReceipt> {
  if (transient.request_id !== durable.request_id || transient.outcome !== durable.outcome || transient.code !== durable.code) {
    throw new Error("Task receipt outcome mismatch; outcome unverified.");
  }
  if (transient.output_digest !== durable.output_digest) throw new Error("Task receipt digest mismatch; outcome unverified.");
  if (transient.output === undefined) return durable;
  // Presentation-only bound, never truncate an answer or change the core record.
  if (transient.output.length > 1_048_576 || new TextEncoder().encode(transient.output).length > 1_048_576) {
    throw new Error("Task output exceeds the transient display limit; output unverified.");
  }
  if (transient.outcome !== "completed" || transient.code !== "ok" || durable.accounting === "unknown"
    || !transient.output_digest) {
    throw new Error("Task output digest unavailable or mismatched; output unverified.");
  }
  // service_usage_contracts.canonical(string) uses Python ensure_ascii=True:
  // quote/escape JSON first, then escape DEL/non-ASCII UTF-16 code units (pairs
  // for astral characters). Hashing raw UTF-8 text is NOT the durable contract.
  const canonical = JSON.stringify(transient.output).replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  const digest = Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
  if (digest !== durable.output_digest) throw new Error("Task output digest mismatch; output unverified.");
  return { ...durable, output: transient.output };
}
export async function dispatchServiceTask(task: ServiceTask, isCurrent?: () => boolean): Promise<ServiceTaskReceipt> {
  const assertCurrent = captureTaskFence(isCurrent);
  assertCurrent();
  const sent = Receipt.parse((await request("/tasks", "POST", task)).data);
  assertCurrent();
  if (sent.request_id !== task.request_id) throw new Error("Task identity mismatch.");
  // ACK or a successful POST alone is not the deliverable. Read the exact
  // durable record. An unknown/lost result is never automatically resubmitted.
  const durable = await readServiceTask(task.request_id, undefined, isCurrent);
  const result = await reconcileOutput(sent, durable);
  assertCurrent();
  if (result.output !== undefined) transientOwners.set(result, assertCurrent);
  return result;
}
function controlPath(path: string): string {
  if (path === "task-routing" || /^[\w-]+\/admission$/.test(path) || /^quota-groups\/[\w-]+$/.test(path)) return `/${path}`;
  throw new Error("Unsupported control path.");
}
export async function readServiceControl(path: string) {
  const result = await request(controlPath(path), "GET");
  if (!/^"\d+"$/.test(result.etag)) throw new Error("Control revision unavailable.");
  const data = z.looseObject({ revision: z.number().int().nonnegative(), policy: z.unknown() }).parse(result.data);
  if (result.etag !== `"${data.revision}"`) throw new Error("Control revision mismatch.");
  return { ...data, etag: result.etag };
}
export async function saveServiceControl(path: string, etag: string, policy: unknown) {
  if (!/^"\d+"$/.test(etag)) throw new Error("Read the current control revision before saving.");
  const written = await request(controlPath(path), "PUT", policy, etag);
  const durable = await readServiceControl(path);
  if (durable.etag !== written.etag) throw new Error("Control changed during verification. Reload before editing.");
  return durable;
}
