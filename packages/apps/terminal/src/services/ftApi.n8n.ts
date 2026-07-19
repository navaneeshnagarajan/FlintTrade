/**
 * n8n bridge settings client — /v1/config/n8n (bare v1 family).
 *
 * Mirrors ftApi.whatsapp.ts: reads are redacted (the API key never leaves
 * the backend — only `api_key_set`), a blank key on save preserves the
 * stored one, and `clearApiKey` explicitly forgets it. The host is
 * non-secret and round-trips in full.
 */

import { buildHeaders, getBase } from "./ftApi.helpers";

export interface N8nConfigData {
  host: string;
  api_key_set: boolean;
}

export interface N8nConfigResponse {
  status?: string;
  message?: string;
  data?: N8nConfigData;
}

export interface N8nConfigPatch {
  host?: string;
  /** A NEW API key to store; blank/omitted preserves the existing one. */
  apiKey?: string;
  /** Explicitly forget the stored key (mutually exclusive with apiKey). */
  clearApiKey?: boolean;
}

export async function readN8nConfig(): Promise<N8nConfigResponse> {
  const response = await fetch(`${getBase()}/v1/config/n8n`, {
    headers: buildHeaders(false),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<N8nConfigResponse>;
}

export async function persistN8nConfig(patch: N8nConfigPatch): Promise<N8nConfigResponse> {
  const body: Record<string, unknown> = {};
  if (patch.host !== undefined) body.host = patch.host.trim();
  if (patch.apiKey?.trim()) body.api_key = patch.apiKey.trim();
  if (patch.clearApiKey) body.clear_api_key = true;

  const response = await fetch(`${getBase()}/v1/config/n8n`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({})) as N8nConfigResponse;
  if (!response.ok || !["ok", "success"].includes(payload.status ?? "")) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}
