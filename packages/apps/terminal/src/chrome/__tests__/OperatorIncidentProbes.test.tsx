import { notifyManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LAYA_STATUS_POLL_MS } from "@/lib/layaStatus";
import { useModeStore } from "@/stores/modeStore";
import { resetOperatorSignals, useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { DeskStatusCluster } from "../DeskStatusCluster";
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

  it("shows a stop and a start on the chip within 1.5 seconds", async () => {
    notifyManager.setScheduler((callback) => {
      callback();
    });
    vi.useFakeTimers();
    let practice: "ready" | "down" = "ready";
    let reason: string | null = null;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/ping")) {
        return jsonResponse({
          status: "ok",
          laya: practice,
          laya_practice: practice,
          laya_live_qualified: practice === "ready",
          laya_reason: reason,
        });
      }
      return jsonResponse({ status: "healthy" });
    }));
    useModeStore.setState({ mode: "practice" });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <OperatorIncidentProbes />
        <DeskStatusCluster />
      </QueryClientProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Laya Ready");

    practice = "down";
    reason = "stopped";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(LAYA_STATUS_POLL_MS);
    });
    const stopped = screen.getByTestId("laya-surface");
    expect(stopped).toHaveTextContent("Laya Down");
    expect(stopped.textContent).not.toMatch(/Ready/);

    practice = "ready";
    reason = null;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(LAYA_STATUS_POLL_MS);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Laya Ready");
    vi.useRealTimers();
    notifyManager.setScheduler((callback) => {
      setTimeout(callback, 0);
    });
  });
});
