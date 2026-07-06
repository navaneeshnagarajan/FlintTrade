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

import {
  applyOpenAlgoRestPort,
  persistOpenAlgoConfigPatch,
  readOpenAlgoConfig,
  testOpenAlgoConnection,
} from "../ftApi.openalgo";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ftApi.openalgo", () => {
  beforeEach(() => {
    storeState.apiKey = "";
    storeState.token = "";
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("persists OpenAlgo config with canonical payload and shared auth headers", async () => {
    storeState.apiKey = "openalgo-key";
    storeState.token = "jwt-token";
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ status: "ok" }));

    await persistOpenAlgoConfigPatch({
      apiKey: "broker-api-key",
      host: "http://localhost:5000",
      port: "5000",
      wsPort: "8765",
    });

    expect(fetch).toHaveBeenCalledWith("/ft-api/v1/config/openalgo", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": "openalgo-key",
        Authorization: "Bearer jwt-token",
      },
      body: JSON.stringify({
        api_key: "broker-api-key",
        host: "http://localhost:5000",
        port: "5000",
        ws_port: "8765",
      }),
    });
  });

  it("applies REST port only when the host URL omits an explicit port", () => {
    expect(applyOpenAlgoRestPort("http://localhost", "5010")).toBe("http://localhost:5010");
    expect(applyOpenAlgoRestPort("http://localhost:5000", "5010")).toBe("http://localhost:5000");
  });

  it("reads OpenAlgo config with auth headers but no JSON content type", async () => {
    storeState.token = "jwt-token";
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { host: "http://localhost:5000" } }),
    );

    await readOpenAlgoConfig();

    expect(fetch).toHaveBeenCalledWith("/ft-api/v1/config/openalgo", {
      headers: { Authorization: "Bearer jwt-token" },
    });
  });

  it("normalises connection-test hosts and preserves HTTP status fallback", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({}, 400));

    const result = await testOpenAlgoConnection({
      host: "http://localhost:5000//",
      apiKey: "bad-key",
    });

    expect(result.message).toBe("Server returned 400");
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      host: "http://localhost:5000",
      api_key: "bad-key",
    });
  });
});
