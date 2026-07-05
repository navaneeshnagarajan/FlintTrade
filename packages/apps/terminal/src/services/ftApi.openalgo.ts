import { buildHeaders } from "./ftApi.helpers";

export interface OpenAlgoConfigData {
  api_key_configured?: boolean;
  api_key_last4?: string;
  host?: string;
  ws_port?: string | number;
}

export interface OpenAlgoConfigResponse {
  status?: string;
  message?: string;
  data?: OpenAlgoConfigData;
}

export interface OpenAlgoConnectionPatch {
  apiKey?: string;
  host?: string;
  wsPort?: string;
}

export interface OpenAlgoConnectionTestResult {
  status?: string;
  message?: string;
  httpStatus?: number;
  ok?: boolean;
}

export function isAcceptedOpenAlgoConfigStatus(status?: string): boolean {
  return !status || ["ok", "success", "partial"].includes(status);
}

function toOpenAlgoConfigPayload(connection: Partial<OpenAlgoConnectionPatch>): Record<string, string> {
  const body: Record<string, string> = {};
  if ("apiKey" in connection) body.api_key = connection.apiKey ?? "";
  if ("host" in connection) body.host = connection.host ?? "";
  if ("wsPort" in connection) body.ws_port = connection.wsPort ?? "";
  return body;
}

export async function readOpenAlgoConfig(): Promise<OpenAlgoConfigResponse> {
  const response = await fetch("/ft-api/v1/config/openalgo", {
    headers: buildHeaders(false),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<OpenAlgoConfigResponse>;
}

export async function persistOpenAlgoConfigPatch(
  connection: Partial<OpenAlgoConnectionPatch>,
): Promise<OpenAlgoConfigResponse> {
  const response = await fetch("/ft-api/v1/config/openalgo", {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(toOpenAlgoConfigPayload(connection)),
  });
  const payload = await response.json().catch(() => ({})) as OpenAlgoConfigResponse;
  if (!response.ok || !isAcceptedOpenAlgoConfigStatus(payload.status)) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}

export async function testOpenAlgoConnection(input: {
  host: string;
  apiKey: string;
}): Promise<OpenAlgoConnectionTestResult> {
  const response = await fetch("/ft-api/v1/test-connection", {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify({
      host: input.host.replace(/\/+$/, ""),
      api_key: input.apiKey,
    }),
    signal: AbortSignal.timeout(10_000),
  });
  const payload = await response
    .json()
    .catch(() => ({ status: "error", message: "Invalid JSON from backend" })) as OpenAlgoConnectionTestResult;
  return {
    ...payload,
    ok: response.ok,
    httpStatus: response.status,
    message: payload.message || (!response.ok ? `Server returned ${response.status}` : undefined),
  };
}
