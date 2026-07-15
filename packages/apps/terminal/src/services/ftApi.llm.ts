import { buildHeaders } from "./ftApi.helpers";

export interface LlmConfigData {
  provider?: string;
  host?: string;
  model?: string;
  api_key_configured?: boolean;
  api_key_last4?: string;
}

export interface LlmConfigResponse {
  status?: string;
  message?: string;
  data?: LlmConfigData;
}

export interface LlmConfigPatch {
  provider?: string;
  host?: string;
  model?: string;
  apiKey?: string;
}

export interface LlmConnectionTestResponse {
  status: "success";
  data: {
    provider: string;
    model: string;
  };
}

function toLlmConfigPayload(
  patch: Partial<LlmConfigPatch>,
  options: { omitEmptyApiKey?: boolean } = {},
): Record<string, string> {
  const body: Record<string, string> = {};
  if ("provider" in patch) body.provider = patch.provider ?? "";
  if ("host" in patch) body.host = patch.host ?? "";
  if ("model" in patch) body.model = patch.model ?? "";
  if ("apiKey" in patch && (!options.omitEmptyApiKey || patch.apiKey?.trim())) {
    body.api_key = patch.apiKey ?? "";
  }
  return body;
}

export function isAcceptedLlmConfigStatus(status?: string): boolean {
  return !status || ["ok", "success"].includes(status);
}

export async function readLlmConfig(): Promise<LlmConfigResponse> {
  const response = await fetch("/ft-api/v1/config/llm", {
    headers: buildHeaders(false),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<LlmConfigResponse>;
}

export async function persistLlmConfigPatch(
  patch: Partial<LlmConfigPatch>,
): Promise<LlmConfigResponse> {
  const response = await fetch("/ft-api/v1/config/llm", {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(toLlmConfigPayload(patch)),
  });
  const payload = await response.json().catch(() => ({})) as LlmConfigResponse;
  if (!response.ok || !isAcceptedLlmConfigStatus(payload.status)) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}

export async function testLlmConnection(
  config: Partial<LlmConfigPatch>,
): Promise<LlmConnectionTestResponse> {
  const response = await fetch("/ft-api/v1/config/llm/test", {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(toLlmConfigPayload(config, { omitEmptyApiKey: true })),
  });
  const payload = await response.json().catch(() => ({})) as Partial<LlmConnectionTestResponse> & {
    message?: string;
  };
  if (
    !response.ok
    || payload.status !== "success"
    || typeof payload.data?.provider !== "string"
    || typeof payload.data?.model !== "string"
  ) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload as LlmConnectionTestResponse;
}
