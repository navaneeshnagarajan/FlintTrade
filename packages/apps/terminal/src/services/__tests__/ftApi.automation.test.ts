import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.stubEnv("DEV", true);

const auth = vi.hoisted(() => ({ token: "" }));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: auth.token }) },
}));
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "" }) },
}));

import {
  createWebhook,
  deleteWebhook,
  getWebhooks,
  setWebhookEnabled,
} from "../ftApi.automation";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  auth.token = "";
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("webhook automation service", () => {
  it("unwraps the real DELETE envelope and uses the path-backed id", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      status: "success",
      data: { message: "Webhook removed" },
    }));

    await expect(deleteWebhook("v1/webhook/custom/my signal")).resolves.toEqual({
      message: "Webhook removed",
    });
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/api/v1/webhooks/v1%2Fwebhook%2Fcustom%2Fmy%20signal");
    expect(init.method).toBe("DELETE");
  });

  it("keeps all webhook mutations read-only in a public demo session", async () => {
    auth.token = "demo-user";
    const config = {
      name: "Demo",
      path: "/v1/webhook/custom/demo",
      type: "custom" as const,
      enabled: true,
      secret: "not-sent",
    };

    await expect(getWebhooks()).resolves.toEqual({ webhooks: [] });
    await expect(createWebhook(config)).rejects.toThrow("unavailable in Demo mode");
    await expect(setWebhookEnabled("v1/webhook/custom/demo", false)).rejects.toThrow(
      "unavailable in Demo mode",
    );
    await expect(deleteWebhook("v1/webhook/custom/demo")).rejects.toThrow(
      "unavailable in Demo mode",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not mistake local dev bypass for the public demo", async () => {
    auth.token = "dev-bypass";
    vi.mocked(fetch).mockResolvedValue(jsonResponse({
      status: "success",
      data: { webhooks: [] },
    }));

    await expect(getWebhooks()).resolves.toEqual({ webhooks: [] });
    expect(fetch).toHaveBeenCalledOnce();
  });
});
