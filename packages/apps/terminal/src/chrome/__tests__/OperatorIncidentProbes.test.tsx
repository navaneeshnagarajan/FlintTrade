import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetOperatorSignals, useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { OperatorIncidentProbes } from "../OperatorIncidentProbes";

vi.mock("@/hooks/useAdvisorLlmStatus", () => ({
  useAdvisorLlmStatus: () => ({
    chrome: "unconfigured",
    configured: false,
    isLoading: false,
    refetch: async () => undefined,
  }),
}));

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderProbes(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <OperatorIncidentProbes />
    </QueryClientProvider>,
  );
}

describe("OperatorIncidentProbes Laya heartbeat", () => {
  beforeEach(() => {
    resetOperatorSignals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("records Laya Down from the desk ping", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/ping")) {
        return jsonResponse({ status: "ok", laya: "down" });
      }
      return jsonResponse({ status: "healthy" });
    }));
    renderProbes();
    await waitFor(() => {
      expect(useOperatorSignalStore.getState().decisionStatus).toBe("down");
    });
  });

  it("records Ready only when the heartbeat says Ready", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/ping")) return jsonResponse({ status: "ok", laya: "ready" });
      return jsonResponse({ status: "healthy" });
    }));
    renderProbes();
    await waitFor(() => {
      expect(useOperatorSignalStore.getState().decisionStatus).toBe("ready");
    });
  });

  it("stays Down when the heartbeat omits Laya", async () => {
    useOperatorSignalStore.setState({ decisionStatus: "ready" });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/ping")) return jsonResponse({ status: "ok" });
      return jsonResponse({ status: "healthy" });
    }));
    renderProbes();
    await waitFor(() => {
      expect(useOperatorSignalStore.getState().decisionStatus).toBe("down");
    });
    expect(useOperatorSignalStore.getState().decisionStatus).not.toBe("ready");
  });
});
