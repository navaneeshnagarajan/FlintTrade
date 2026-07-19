/**
 * N8nSection.test — the n8n Bridge tab (honest offline / online / no-key states).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const mockReadN8nConfig = vi.fn();
const mockPersistN8nConfig = vi.fn();
vi.mock("@/services/ftApi.n8n", () => ({
  readN8nConfig: () => mockReadN8nConfig() as Promise<unknown>,
  persistN8nConfig: (patch: unknown) => mockPersistN8nConfig(patch) as Promise<unknown>,
}));

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
  beforeEach(() => {
    vi.clearAllMocks();
    mockReadN8nConfig.mockResolvedValue({
      status: "success",
      data: { host: "", api_key_set: false },
    });
  });

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

  it("surfaces a failed activate/deactivate instead of staying silent", async () => {
    vi.mocked(checkN8nHealth).mockResolvedValue({ running: true });
    vi.mocked(listN8nWorkflows).mockResolvedValue({
      workflows: [{ id: "7", name: "Morning gap scan", active: true }],
      count: 1,
    });
    vi.mocked(deactivateN8nWorkflow).mockRejectedValue(
      new Error("Failed to deactivate workflow 7"),
    );

    renderSection();

    await waitFor(() => expect(screen.getByText("Morning gap scan")).toBeInTheDocument());
    fireEvent.click(
      screen.getByRole("button", { name: "Deactivate workflow Morning gap scan" }),
    );

    await waitFor(() =>
      expect(screen.getByText(/failed to deactivate workflow 7/i)).toBeInTheDocument(),
    );
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


describe("N8nSection connection settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockReadN8nConfig.mockResolvedValue({
      status: "success",
      data: { host: "http://10.0.0.5:5678", api_key_set: true },
    });
    vi.mocked(checkN8nHealth).mockRejectedValue(new Error("offline"));
  });

  it("hydrates the host and discloses a stored key without revealing it", async () => {
    renderSection();
    await waitFor(() =>
      expect(screen.getByLabelText("n8n host URL")).toHaveValue("http://10.0.0.5:5678"),
    );
    expect(screen.getByLabelText("n8n API key")).toHaveAttribute(
      "placeholder",
      expect.stringContaining("saved"),
    );
  });

  it("saves the connection settings and clears the key draft", async () => {
    mockPersistN8nConfig.mockResolvedValue({
      status: "ok",
      data: { host: "http://10.0.0.5:5678", api_key_set: true },
    });
    renderSection();
    await waitFor(() =>
      expect(screen.getByLabelText("n8n host URL")).toHaveValue("http://10.0.0.5:5678"),
    );

    fireEvent.change(screen.getByLabelText("n8n API key"), {
      target: { value: "fresh-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save/i }));

    await waitFor(() => expect(mockPersistN8nConfig).toHaveBeenCalledOnce());
    expect(mockPersistN8nConfig).toHaveBeenCalledWith({
      host: "http://10.0.0.5:5678",
      apiKey: "fresh-key",
    });
    await waitFor(() =>
      expect(screen.getByLabelText("n8n API key")).toHaveValue(""),
    );
  });

  it("surfaces a rejected save honestly", async () => {
    mockPersistN8nConfig.mockRejectedValue(new Error("host must be an http(s) URL"));
    renderSection();
    await waitFor(() => expect(mockReadN8nConfig).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /^save/i }));
    expect(await screen.findByText(/http\(s\) URL/i)).toBeInTheDocument();
  });
});
