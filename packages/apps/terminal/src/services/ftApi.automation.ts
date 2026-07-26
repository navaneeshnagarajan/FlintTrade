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
  type: "custom";
  enabled: boolean;
  secret_configured: boolean;
}

export interface WebhookCreateConfig extends Omit<WebhookConfig, "id" | "secret_configured"> {
  /** Required at creation and never echoed by list/get responses. */
  secret: string;
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
