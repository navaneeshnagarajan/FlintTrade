/**
 * useAdvisorLlmStatus — Chat LLM readiness aligned with Settings `#llm`.
 *
 * Explore / demo-user still probe advisor/status, but a Settings empty
 * appearance (GET /v1/config/llm 401) must win over env-default
 * ``configured: true``.
 */

import type { ReactNode } from "react";
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ADVISOR_LLM_STATUS_QUERY_KEY,
  SETTINGS_LLM_HYDRATION_QUERY_KEY,
  useAdvisorLlmStatus,
} from "../useAdvisorLlmStatus";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function isLlmConfigGet(input: unknown, init?: RequestInit): boolean {
  const url = String(input);
  return url.includes("/config/llm") && !url.includes("/test") && init?.method !== "POST";
}

function mockAdvisorAndSettings(options: {
  advisor: "configured" | "unconfigured" | "unreachable" | "unknown";
  settings: "ready" | "unauthorized";
}): void {
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (isLlmConfigGet(input, init)) {
      if (options.settings === "unauthorized") {
        return jsonResponse({
          status: "error",
          message: "LLM configuration requires an authenticated session",
        }, 401);
      }
      return jsonResponse({
        status: "success",
        data: { provider: "openai", model: "test", api_key_configured: true },
      });
    }
    if (options.advisor === "unreachable") {
      throw new TypeError("Failed to fetch");
    }
    if (options.advisor === "unknown") {
      return jsonResponse({ status: "error" });
    }
    return jsonResponse({
      status: "success",
      data: {
        configured: options.advisor === "configured",
        provider: options.advisor === "configured" ? "openai" : "",
        model: options.advisor === "configured" ? "test" : "",
      },
    });
  });
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useAdvisorLlmStatus", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    useModeStore.setState({ mode: "explore" });
    useAuthStore.setState({ token: null });
  });

  afterEach(() => {
    onlineManager.setOnline(true);
    vi.unstubAllGlobals();
  });

  it("probes advisor/status even when the session is Explore demo-user", async () => {
    useModeStore.setState({ mode: "explore" });
    useAuthStore.setState({ token: "demo-user" });
    mockAdvisorAndSettings({ advisor: "unconfigured", settings: "unauthorized" });

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("unconfigured"));
    expect(result.current.configured).toBe(false);
    expect(useModeStore.getState().mode).toBe("explore");
    expect(useAuthStore.getState().token).toBe("demo-user");
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/advisor/status"))).toBe(true);
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/config/llm"))).toBe(true);
    expect(ADVISOR_LLM_STATUS_QUERY_KEY).toEqual(["advisor-llm-readiness"]);
    expect(SETTINGS_LLM_HYDRATION_QUERY_KEY).toEqual(["settings-llm-hydration"]);
  });

  it("treats Explore Settings #llm empty as unconfigured even when advisor/status is configured", async () => {
    useModeStore.setState({ mode: "explore" });
    useAuthStore.setState({ token: "demo-user" });
    mockAdvisorAndSettings({ advisor: "configured", settings: "unauthorized" });

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("unconfigured"));
    expect(result.current.configured).toBe(false);
  });

  it("treats a configured probe as ready Chat chrome only when Settings #llm can load", async () => {
    useModeStore.setState({ mode: "live" });
    useAuthStore.setState({ token: "session-jwt" });
    mockAdvisorAndSettings({ advisor: "configured", settings: "ready" });

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("ready"));
    expect(result.current.configured).toBe(true);
  });

  it("maps an unreachable probe to Disconnected when Settings #llm is ready", async () => {
    useModeStore.setState({ mode: "live" });
    useAuthStore.setState({ token: "session-jwt" });
    mockAdvisorAndSettings({ advisor: "unreachable", settings: "ready" });

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("disconnected"));
    expect(result.current.configured).toBe(false);
  });

  it("maps a broken configured-looking probe to Error when Settings #llm is ready", async () => {
    useModeStore.setState({ mode: "live" });
    useAuthStore.setState({ token: "session-jwt" });
    mockAdvisorAndSettings({ advisor: "unknown", settings: "ready" });

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("error"));
    expect(result.current.configured).toBe(false);
  });

  it("does not keep Connected while a remount refetch of cached configured is in flight", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(ADVISOR_LLM_STATUS_QUERY_KEY, "configured");
    client.setQueryData(SETTINGS_LLM_HYDRATION_QUERY_KEY, "ready");
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      await pending;
      if (isLlmConfigGet(input, init)) {
        return jsonResponse({
          status: "success",
          data: { provider: "", model: "", api_key_configured: false },
        });
      }
      return jsonResponse({
        status: "success",
        data: { configured: false, provider: "", model: "" },
      });
    });

    const { result } = renderHook(() => useAdvisorLlmStatus(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(true));
    expect(result.current.chrome).toBe("loading");
    expect(result.current.configured).toBe(false);

    release();
    await waitFor(() => expect(result.current.chrome).toBe("unconfigured"));
    expect(result.current.configured).toBe(false);
  });

  it("still probes advisor/status when the browser reports offline", async () => {
    onlineManager.setOnline(false);
    mockAdvisorAndSettings({ advisor: "unconfigured", settings: "unauthorized" });

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("unconfigured"));
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/advisor/status"))).toBe(true);
  });
});
