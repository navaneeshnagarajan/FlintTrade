/**
 * Skill-draft review client — /api/v1/ai/skill-drafts (AI1).
 *
 * Drafts are session lessons the agent rendered for OPERATOR review; they
 * influence nothing until approved. Approve/reject are guarded writes (the
 * shared headers carry the operator's session JWT).
 */

import { buildHeaders, getBase } from "./ftApi.helpers";

export interface SkillDraftSummary {
  name: string;
  description: string;
  modified_at: number;
}

async function request<T>(path: string, method = "GET"): Promise<T> {
  const response = await fetch(`${getBase()}/api/v1/ai/skill-drafts${path}`, {
    method,
    headers: buildHeaders(method !== "GET"),
  });
  const payload = await response.json().catch(() => ({})) as {
    status?: string;
    message?: string;
    data?: T;
  };
  if (!response.ok || payload.status === "error") {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return (payload.data ?? undefined) as T;
}

/** Pending draft summaries, newest first. */
export const listSkillDrafts = () => request<SkillDraftSummary[]>("");

/** One draft's full markdown. */
export const readSkillDraft = (name: string) =>
  request<{ name: string; content: string }>(`/${encodeURIComponent(name)}`);

/** Approve a draft into the operator skills directory (guarded). */
export const approveSkillDraft = (name: string) =>
  request<undefined>(`/${encodeURIComponent(name)}/approve`, "POST");

/** Reject (delete) a draft (guarded). */
export const rejectSkillDraft = (name: string) =>
  request<undefined>(`/${encodeURIComponent(name)}`, "DELETE");
