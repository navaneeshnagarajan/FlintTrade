/**
 * WhatsApp alert settings client — /v1/config/whatsapp (bare v1 family).
 *
 * Mirrors ftApi.telegram.ts: reads are redacted (the webhook URL never
 * leaves the backend — only `webhook_url_set`), a blank URL on save
 * preserves the stored one, and `clearWebhookUrl` explicitly forgets it.
 */

import { buildHeaders, getBase } from "./ftApi.helpers";

export interface WhatsAppConfigData {
  enabled: boolean;
  webhook_url_set: boolean;
}

export interface WhatsAppConfigResponse {
  status?: string;
  message?: string;
  data?: WhatsAppConfigData;
}

export interface WhatsAppConfigPatch {
  enabled: boolean;
  /** A NEW webhook URL to store; blank/omitted preserves the existing one. */
  webhookUrl?: string;
  /** Explicitly forget the stored URL (mutually exclusive with webhookUrl). */
  clearWebhookUrl?: boolean;
}

export async function readWhatsAppConfig(): Promise<WhatsAppConfigResponse> {
  const response = await fetch(`${getBase()}/v1/config/whatsapp`, {
    headers: buildHeaders(false),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<WhatsAppConfigResponse>;
}

export async function persistWhatsAppConfig(
  patch: WhatsAppConfigPatch,
): Promise<WhatsAppConfigResponse> {
  const body: Record<string, unknown> = { enabled: patch.enabled };
  if (patch.webhookUrl?.trim()) body.webhook_url = patch.webhookUrl.trim();
  if (patch.clearWebhookUrl) body.clear_webhook_url = true;

  const response = await fetch(`${getBase()}/v1/config/whatsapp`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({})) as WhatsAppConfigResponse;
  if (!response.ok || !["ok", "success"].includes(payload.status ?? "")) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}
