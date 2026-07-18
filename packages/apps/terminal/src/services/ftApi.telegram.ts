/**
 * Telegram bot settings client — /v1/config/telegram (bare v1 family).
 *
 * Mirrors ftApi.llm.ts: reads are redacted (the token never leaves the
 * backend — only `bot_token_set`), and a blank token on save preserves any
 * stored secret. Saving with `clearToken` explicitly forgets the stored
 * token.
 */

import { buildHeaders, getBase } from "./ftApi.helpers";

export interface TelegramConfigData {
  enabled: boolean;
  chat_id: string;
  bot_token_set: boolean;
}

export interface TelegramConfigResponse {
  status?: string;
  message?: string;
  data?: TelegramConfigData;
}

export interface TelegramConfigPatch {
  enabled: boolean;
  chatId: string;
  /** A NEW token to store; blank/omitted preserves the existing one. */
  botToken?: string;
  /** Explicitly forget the stored token (mutually exclusive with botToken). */
  clearToken?: boolean;
}

export async function readTelegramConfig(): Promise<TelegramConfigResponse> {
  const response = await fetch(`${getBase()}/v1/config/telegram`, {
    headers: buildHeaders(false),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json() as Promise<TelegramConfigResponse>;
}

export async function persistTelegramConfig(
  patch: TelegramConfigPatch,
): Promise<TelegramConfigResponse> {
  const body: Record<string, unknown> = {
    enabled: patch.enabled,
    chat_id: patch.chatId,
  };
  if (patch.botToken?.trim()) body.bot_token = patch.botToken.trim();
  if (patch.clearToken) body.clear_token = true;

  const response = await fetch(`${getBase()}/v1/config/telegram`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({})) as TelegramConfigResponse;
  if (!response.ok || !["ok", "success"].includes(payload.status ?? "")) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}
