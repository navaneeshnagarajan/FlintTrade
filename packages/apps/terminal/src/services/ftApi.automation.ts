import { del, get, isDemoAuthSession, isDemoUserSession, patch, post } from "./ftApi.helpers";

export interface CronJob {
  name: string;
  description: string;
  trigger_type: string;
  status: string;
  last_run: string | null;
  run_count: number;
  error_count: number;
}

export interface WebhookConfig {
  id: string;
  path: string;
  name: string;
  type: "tradingview" | "chartink" | "gocharting" | "custom";
  enabled: boolean;
  secret_configured: boolean;
}

export interface WebhookCreateConfig extends Omit<WebhookConfig, "id" | "secret_configured"> {
  /** Required at creation and never echoed by list/get responses. */
  secret: string;
}

export interface N8nWorkflow {
  id: string;
  name: string;
  active: boolean;
  createdAt?: string;
  updatedAt?: string;
}

export interface N8nWebhookTriggerResult {
  [key: string]: unknown;
}

export const getCronJobs = () =>
  isDemoAuthSession()
    ? Promise.resolve({ jobs: [] })
    : get<{ jobs: CronJob[] }>("cron/jobs");

export const pauseCronJob = (name: string) =>
  post<{ status: string }>(
    "cron/jobs/" + encodeURIComponent(name) + "/pause",
  );

export const resumeCronJob = (name: string) =>
  post<{ status: string }>(
    "cron/jobs/" + encodeURIComponent(name) + "/resume",
  );

export const getWebhooks = () =>
  isDemoUserSession()
    ? Promise.resolve({ webhooks: [] })
    : get<{ webhooks: WebhookConfig[] }>("webhooks");

export const createWebhook = (config: WebhookCreateConfig) =>
  isDemoUserSession()
    ? Promise.reject(new Error("Webhook configuration is unavailable in Demo mode."))
    : post<WebhookConfig>("webhooks", config);

export const setWebhookEnabled = (id: string, enabled: boolean) =>
  isDemoUserSession()
    ? Promise.reject(new Error("Webhook configuration is unavailable in Demo mode."))
    : patch<WebhookConfig>("webhooks/" + encodeURIComponent(id), { enabled });

export const deleteWebhook = (id: string) =>
  isDemoUserSession()
    ? Promise.reject(new Error("Webhook configuration is unavailable in Demo mode."))
    : del<{ message: string }>("webhooks/" + encodeURIComponent(id));

export const checkN8nHealth = () =>
  isDemoAuthSession()
    ? Promise.resolve({ running: false })
    : get<{ running: boolean }>("automation/n8n/health");

export const listN8nWorkflows = () =>
  isDemoAuthSession()
    ? Promise.resolve({ workflows: [], count: 0 })
    : get<{ workflows: N8nWorkflow[]; count: number }>("automation/n8n/workflows");

export const triggerN8nWebhook = (
  webhookId: string,
  data: Record<string, unknown> = {},
) =>
  post<N8nWebhookTriggerResult>("automation/n8n/webhook/trigger", {
    webhook_id: webhookId,
    data,
  });

export const activateN8nWorkflow = (workflowId: string) =>
  post<{ workflow_id: string; active: true }>(
    `automation/n8n/workflows/${encodeURIComponent(workflowId)}/activate`,
  );

export const deactivateN8nWorkflow = (workflowId: string) =>
  post<{ workflow_id: string; active: false }>(
    `automation/n8n/workflows/${encodeURIComponent(workflowId)}/deactivate`,
  );

export const testWhatsAppAlert = (message?: string) =>
  post<{ status: string; message: string }>("alerts/whatsapp/test", {
    ...(message ? { message } : {}),
  });
