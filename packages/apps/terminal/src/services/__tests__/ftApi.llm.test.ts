import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const storeState = vi.hoisted(() => ({
  apiKey: "",
  token: "",
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: storeState.apiKey }) },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: storeState.token }) },
}));

import { persistLlmConfigPatch, readLlmConfig } from "../ftApi.llm";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ftApi.llm", () => {
  beforeEach(() => {
    storeState.apiKey = "";
    storeState.token = "";
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("persists LLM config with canonical payload and shared auth headers", async () => {
    storeState.token = "jwt-token";
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ status: "ok" }));

    await persistLlmConfigPatch({
      provider: "openai",
      host: "",
      model: "gpt-4o",
      apiKey: "sk-unit-key",
    });

    expect(fetch).toHaveBeenCalledWith("/ft-api/v1/config/llm", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer jwt-token",
      },
      body: JSON.stringify({
        provider: "openai",
        host: "",
        model: "gpt-4o",
        api_key: "sk-unit-key",
      }),
    });
  });

  it("reads LLM config with auth headers but no JSON content type", async () => {
    storeState.token = "jwt-token";
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { provider: "openai" } }),
    );

    await readLlmConfig();

    expect(fetch).toHaveBeenCalledWith("/ft-api/v1/config/llm", {
      headers: { Authorization: "Bearer jwt-token" },
    });
  });
});
