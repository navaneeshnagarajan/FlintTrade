/**
 * useAdvisorLlmStatus — Chat LLM readiness from advisor/status.
 *
 * The probe must run in Explore / demo-user sessions. A stale local store
 * must not produce a Connected badge.
 */

import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ADVISOR_LLM_STATUS_QUERY_KEY, useAdvisorLlmStatus } from "../useAdvisorLlmStatus";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
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
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("probes advisor/status even when the session is Explore demo-user", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: "success",
        data: { configured: false, provider: "", model: "" },
      }),
    );

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("unconfigured"));
    expect(result.current.configured).toBe(false);
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/advisor/status"))).toBe(true);
    expect(ADVISOR_LLM_STATUS_QUERY_KEY).toEqual(["advisor-llm-readiness"]);
  });

  it("treats a configured probe as ready Chat chrome", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        status: "success",
        data: { configured: true, provider: "openai", model: "test" },
      }),
    );

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("ready"));
    expect(result.current.configured).toBe(true);
  });

  it("maps an unreachable probe to Disconnected, not Connected", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useAdvisorLlmStatus(), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.chrome).toBe("disconnected"));
    expect(result.current.configured).toBe(false);
  });
});
