/**
 * N8nSection.test — the n8n Bridge tab (honest offline / online / no-key states).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi", () => ({
  checkN8nHealth: vi.fn(),
  listN8nWorkflows: vi.fn(),
  activateN8nWorkflow: vi.fn(),
  deactivateN8nWorkflow: vi.fn(),
  triggerN8nWebhook: vi.fn(),
}));

import N8nSection from "../N8nSection";
import {
  activateN8nWorkflow,
  checkN8nHealth,
  deactivateN8nWorkflow,
  listN8nWorkflows,
  triggerN8nWebhook,
} from "@/services/ftApi";

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <N8nSection />
    </QueryClientProvider>,
  );
}

describe("N8nSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows an honest offline state with the setup hint", async () => {
    vi.mocked(checkN8nHealth).mockRejectedValue(new Error("n8n is not reachable"));

    renderSection();

    await waitFor(() => expect(screen.getByText("Offline")).toBeInTheDocument());
    expect(screen.getByText(/no n8n instance is reachable/i)).toBeInTheDocument();
    expect(screen.getByText("N8N_HOST")).toBeInTheDocument();
    // No workflow machinery is rendered while offline.
    expect(screen.queryByText("Workflows")).not.toBeInTheDocument();
    expect(listN8nWorkflows).not.toHaveBeenCalled();
  });

  it("lists workflows when online and toggles activation", async () => {
    vi.mocked(checkN8nHealth).mockResolvedValue({ running: true });
    vi.mocked(listN8nWorkflows).mockResolvedValue({
      workflows: [{ id: "7", name: "Morning gap scan", active: true }],
      count: 1,
    });
    vi.mocked(deactivateN8nWorkflow).mockResolvedValue({ workflow_id: "7", active: false });

    renderSection();

    await waitFor(() => expect(screen.getByText("Morning gap scan")).toBeInTheDocument());
    expect(screen.getByText("Online")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate workflow Morning gap scan" }),
    );
    await waitFor(() => expect(deactivateN8nWorkflow).toHaveBeenCalledWith("7"));
    expect(activateN8nWorkflow).not.toHaveBeenCalled();
  });

  it("surfaces the backend error and the API-key hint when listing fails", async () => {
    vi.mocked(checkN8nHealth).mockResolvedValue({ running: true });
    vi.mocked(listN8nWorkflows).mockRejectedValue(new Error("n8n API key not configured"));

    renderSection();

    await waitFor(() =>
      expect(screen.getByText(/n8n API key not configured/i)).toBeInTheDocument(),
    );
    expect(screen.getByText("N8N_API_KEY")).toBeInTheDocument();
  });

  it("triggers a webhook workflow and reports success", async () => {
    vi.mocked(checkN8nHealth).mockResolvedValue({ running: true });
    vi.mocked(listN8nWorkflows).mockResolvedValue({ workflows: [], count: 0 });
    vi.mocked(triggerN8nWebhook).mockResolvedValue({});

    renderSection();

    await waitFor(() => expect(screen.getByText("Online")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("n8n webhook ID"), {
      target: { value: "abc-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /trigger/i }));

    await waitFor(() => expect(triggerN8nWebhook).toHaveBeenCalledWith("abc-123"));
    expect(screen.getByText(/webhook triggered/i)).toBeInTheDocument();
  });
});
