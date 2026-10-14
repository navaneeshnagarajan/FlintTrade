import { z } from "zod";
import { authoritativeKnowledgeScopeSchema, sameKnowledgeScope, type AuthoritativeKnowledgeScope, type KnowledgeBinding } from "./knowledgeScope";
import { buildHeaders, getBase } from "./ftApi.helpers";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from "@/stores/authStore";
import { captureOperatorIncidentScope, isOperatorIncidentScopeCurrent } from "@/lib/operatorIncidentScope";
import { isPublicDemoBuild } from "@/lib/demoSession";
function captureKnowledgeFence(isCurrent?: () => boolean) {
  const auth = captureAuthSessionFence();
  const scope = captureOperatorIncidentScope();
  return () => {
    if (!isAuthSessionFenceCurrent(auth) || !isOperatorIncidentScopeCurrent(scope) || isCurrent?.() === false) {
      throw new Error("Knowledge response belongs to a retired scope");
    }
    if (useAuthStore.getState().status !== "logged-in" || !useAuthStore.getState().token) throw new Error("Operator session required");
  };
}
export async function knowledgeRequest(path: string, body?: unknown, options: { expectedStatus?: number; isCurrent?: () => boolean } = {}): Promise<Record<string, unknown>> {
  if (isPublicDemoBuild()) throw new Error("Installed knowledge and learning permissions are unavailable in the public preview.");
  if (!path.startsWith("/v1/knowledge/") && !path.startsWith("/v1/learning/permissions/")
    && !/^\/api\/v1\/ai\/skill-drafts(?:\/[a-z0-9][a-z0-9_-]{0,127}(?:\/candidate)?)?$/.test(path)) throw new Error("Unsupported knowledge path");
  const assertCurrent = captureKnowledgeFence(options.isCurrent);
  assertCurrent();
  const response = await fetch(`${getBase()}${path}`, { method: body === undefined ? "GET" : "POST", headers: buildHeaders(body !== undefined), cache: "no-store", ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  const data = z.record(z.string(), z.unknown()).parse(await response.json());
  assertCurrent();
  if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : typeof data.message === "string" ? data.message : `Knowledge unavailable (${response.status})`);
  if (options.expectedStatus !== undefined && response.status !== options.expectedStatus) throw new Error("Knowledge acknowledgement status mismatch; outcome unverified");
  return data;
}
const skillName = z.string().regex(/^[a-z0-9][a-z0-9_-]{0,127}$/);
const identity = z.string().min(1).max(256);
const packageHash = z.string().regex(/^[a-f0-9]{64}$/);
export const knowledgeSkillSchema = z.object({
  name: skillName,
  description: z.string().optional(),
  version_id: identity,
  package_hash: packageHash,
  origin: z.enum(["stock", "adapted", "learned"]),
  state: z.enum(["candidate", "validated", "default", "quarantined", "retired"]),
  enabled: z.boolean(), default: z.boolean(), validated: z.boolean(), run_pinned: z.boolean(),
  unavailable_reason: z.string().nullable(),
}).refine(row => !row.enabled || (row.validated && (row.default || row.run_pinned)
  && (row.state === "default" || row.state === "validated") && row.unavailable_reason === null),
"Inconsistent enabled knowledge identity");
export type KnowledgeSkill = z.infer<typeof knowledgeSkillSchema>;
export type KnowledgeIdentity = Pick<KnowledgeSkill, "name" | "version_id" | "package_hash">;
export function sameKnowledgeIdentity(left: KnowledgeIdentity, right: KnowledgeIdentity) {
  return left.name === right.name && left.version_id === right.version_id && left.package_hash === right.package_hash;
}
export async function listKnowledgeSkills(isCurrent?: () => boolean) {
  const catalogue = z.object({ scope: authoritativeKnowledgeScopeSchema, skills: z.array(knowledgeSkillSchema) })
    .parse(await knowledgeRequest("/v1/knowledge/skills", undefined, { isCurrent }));
  const rows = catalogue.skills;
  const versions = new Set<string>();
  const enabled = new Set<string>();
  for (const row of rows) {
    if (versions.has(row.version_id) || (row.enabled && enabled.has(row.name))) throw new Error("Ambiguous knowledge catalogue identity");
    versions.add(row.version_id);
    if (row.enabled) enabled.add(row.name);
  }
  return catalogue;
}
export function assertKnowledgeBinding(binding: KnowledgeBinding, scope: AuthoritativeKnowledgeScope) {
  if (binding.isCurrent?.() === false) throw new Error("Knowledge response belongs to a retired scope");
  binding.observe?.(scope);
  if (!sameKnowledgeScope(binding.scope, scope)) throw new Error("Authoritative knowledge scope changed; refresh and select again");
}
export async function readKnowledgeSkill(name: string, expected: KnowledgeIdentity, binding: KnowledgeBinding) {
  const { isCurrent } = binding;
  const assertCurrent = captureKnowledgeFence(isCurrent);
  assertCurrent();
  skillName.parse(name);
  if (name !== expected.name) throw new Error("Canonical knowledge identity mismatch");
  const data = z.object({ scope: authoritativeKnowledgeScopeSchema, reference: z.string(), version: identity, body: z.string(), classification: z.enum(["public", "private"]), receipt: z.string().min(1) }).parse(await knowledgeRequest(`/v1/knowledge/skills/${encodeURIComponent(name)}`, undefined, { isCurrent }));
  assertCurrent();
  assertKnowledgeBinding(binding, data.scope);
  if (data.reference !== `skill:${name}` || data.version !== expected.version_id) throw new Error("Canonical knowledge version identity changed; refresh and read the intended version");
  const catalogue = await listKnowledgeSkills(isCurrent);
  assertKnowledgeBinding(binding, catalogue.scope);
  const current = catalogue.skills.find(row => sameKnowledgeIdentity(row, expected));
  assertCurrent();
  if (!current?.enabled) throw new Error("Knowledge version is no longer enabled; refresh the catalogue");
  return data;
}

const versionSchema = z.looseObject({
  version: identity, version_id: identity, context_scope: authoritativeKnowledgeScopeSchema, name: skillName, kind: z.literal("skill-version"),
  origin: z.enum(["stock", "adapted", "learned"]), package_hash: packageHash,
  files: z.record(z.string(), z.string()).refine(files => Object.keys(files).length > 0),
  rights: z.record(z.string(), z.unknown()),
});
export async function exportKnowledgeVersion(expected: KnowledgeSkill, binding: KnowledgeBinding) {
  const { isCurrent } = binding;
  const value = versionSchema.parse(await knowledgeRequest(`/v1/knowledge/versions/${encodeURIComponent(expected.version_id)}`, undefined, { isCurrent }));
  assertKnowledgeBinding(binding, value.context_scope);
  // `version` retains the stock release label; only version_id is ledger identity.
  if (value.name !== expected.name || value.origin !== expected.origin || value.package_hash !== expected.package_hash
    || value.version_id !== expected.version_id) throw new Error("Canonical export identity mismatch");
  return value;
}
export async function retireKnowledgeVersion(expected: KnowledgeIdentity, reason: string, binding: KnowledgeBinding) {
  const { isCurrent } = binding;
  const assertCurrent = captureKnowledgeFence(isCurrent);
  assertCurrent();
  if (!reason.trim() || new TextEncoder().encode(reason).length > 4096) throw new Error("A bounded retirement reason is required");
  const result = z.object({ version: identity, state: z.literal("retired"), receipt: z.string().min(1) })
    .parse(await knowledgeRequest(`/v1/knowledge/versions/${encodeURIComponent(expected.version_id)}/retire`, { reason }, { isCurrent }));
  if (result.version !== expected.version_id) throw new Error("Retirement acknowledgement identity mismatch; outcome unverified");
  assertCurrent();
  const catalogue = await listKnowledgeSkills(isCurrent);
  assertKnowledgeBinding(binding, catalogue.scope);
  assertCurrent();
  const rows = catalogue.skills;
  const exact = rows.find(row => sameKnowledgeIdentity(row, expected));
  if (!exact || exact.state !== "retired" || exact.enabled) throw new Error("Retirement readback mismatch; outcome unverified");
  return { ...result, catalogue };
}

const draftRoot = "/api/v1/ai/skill-drafts";
const draftSchema = z.union([knowledgeSkillSchema, z.object({
  name: skillName, description: z.string().optional(), state: z.literal("unavailable"), enabled: z.literal(false),
})]);
export async function listKnowledgeDrafts() {
  const rows = z.object({ status: z.literal("success"), data: z.array(draftSchema) }).parse(await knowledgeRequest(draftRoot)).data;
  if (new Set(rows.map(row => row.name)).size !== rows.length) throw new Error("Ambiguous retained draft identity");
  return rows;
}
export async function readKnowledgeDraft(name: string, isCurrent?: () => boolean) {
  skillName.parse(name);
  const result = z.object({ status: z.literal("success"), data: z.object({ name: skillName, content: z.string() }) })
    .parse(await knowledgeRequest(`${draftRoot}/${encodeURIComponent(name)}`, undefined, { isCurrent })).data;
  if (result.name !== name) throw new Error("Retained draft identity mismatch");
  return result;
}
export async function intakeKnowledgeDraft(expected: KnowledgeIdentity, isCurrent?: () => boolean) {
  const assertCurrent = captureKnowledgeFence(isCurrent);
  assertCurrent();
  skillName.parse(expected.name);
  const result = z.object({ status: z.literal("accepted"), data: knowledgeSkillSchema })
    .parse(await knowledgeRequest(`${draftRoot}/${encodeURIComponent(expected.name)}/candidate`, {}, { expectedStatus: 202, isCurrent })).data;
  if (!sameKnowledgeIdentity(result, expected) || result.state !== "candidate" || result.enabled || result.validated || result.default || result.run_pinned) {
    throw new Error("Candidate intake identity/state mismatch; outcome unverified");
  }
  assertCurrent();
  const rows = await listKnowledgeDrafts();
  assertCurrent();
  const readback = rows.find(row => row.state !== "unavailable" && sameKnowledgeIdentity(row, result));
  if (!readback || readback.state !== "candidate" || readback.enabled || readback.validated || readback.default || readback.run_pinned) {
    throw new Error("Candidate intake readback mismatch; outcome unverified");
  }
  return result;
}
