import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.ai", () => ({
  getAgentBackends: vi.fn(),
  runAgent: vi.fn(),
}));

import { getAgentBackends, runAgent, type AgentEvent, type BackendItem } from "@/services/ftApi.ai";
import AIBackendsWidget from "./AIBackendsWidget";

const mockGetBackends = getAgentBackends as unknown as ReturnType<typeof vi.fn>;
const mockRunAgent = runAgent as unknown as ReturnType<typeof vi.fn>;

function renderWidget() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AIBackendsWidget />
    </QueryClientProvider>,
  );
}

async function* streamOf(events: AgentEvent[]): AsyncGenerator<AgentEvent, void, unknown> {
  for (const event of events) {
    yield event;
  }
}

const LLM_READY: BackendItem = {
  id: "cerebras",
  display_name: "Cerebras",
  kind: "llm",
  auth_mode: "api_key",
  description: "Cerebras inference (OpenAI-compatible chat completions).",
  llm_provider: "cerebras",
  detect_binaries: [],
  invocation: [],
  requires_binary: false,
  status: "ready",
};

const LLM_NEEDS_CONFIG: BackendItem = {
  id: "claude-code-oauth",
  display_name: "Claude Code (OAuth + credits)",
  kind: "llm",
  auth_mode: "oauth",
  description: "Anthropic Claude via an operator-supplied OAuth token.",
  llm_provider: "anthropic",
  detect_binaries: [],
  invocation: [],
  requires_binary: false,
  status: "needs_config",
};

const CODEX_READY: BackendItem = {
  id: "codex",
  display_name: "Codex CLI",
  kind: "cli_agent",
  auth_mode: "cli_managed",
  description: "OpenAI Codex CLI app-server.",
  llm_provider: null,
  detect_binaries: ["codex"],
  invocation: ["codex", "app-server"],
  requires_binary: true,
  status: "ready",
};

const HERMES_NOT_INSTALLED: BackendItem = {
  id: "hermes",
  display_name: "Hermes Agent (ACP)",
  kind: "acp_agent",
  auth_mode: "cli_managed",
  description: "Nous Hermes agent bridged over its ACP stdio entrypoint.",
  llm_provider: null,
  detect_binaries: ["hermes", "hermes-acp"],
  invocation: ["hermes", "acp"],
  requires_binary: true,
  status: "not_installed",
};

describe("AIBackendsWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetBackends.mockResolvedValue({
      backends: [LLM_READY, LLM_NEEDS_CONFIG, CODEX_READY, HERMES_NOT_INSTALLED],
    });
  });

  it("lists backends badged by kind and status", async () => {
    renderWidget();
    expect(await screen.findByText("Cerebras")).toBeInTheDocument();
    expect(screen.getByText("Codex CLI")).toBeInTheDocument();
    expect(screen.getByText("Hermes Agent (ACP)")).toBeInTheDocument();
    // Kind + status badges are rendered.
    expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);
    expect(screen.getByText("Needs config")).toBeInTheDocument();
    expect(screen.getByText("Not installed")).toBeInTheDocument();
  });

  it("points LLM backends to Settings and never shows a run box", async () => {
    renderWidget();
    await screen.findByText("Cerebras");
    // No prompt box for chat providers.
    expect(screen.queryByLabelText("Prompt for Cerebras")).not.toBeInTheDocument();
    // A Settings affordance exists.
    expect(screen.getAllByRole("button", { name: /settings/i }).length).toBeGreaterThan(0);
  });

  it("shows an install hint for a not-installed agent and no run control", async () => {
    renderWidget();
    await screen.findByText("Hermes Agent (ACP)");
    expect(screen.getByText(/Not installed on this host/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run Hermes Agent/i })).not.toBeInTheDocument();
  });

  it("streams agent output into the pane and stops on done", async () => {
    mockRunAgent.mockImplementation(() =>
      streamOf([
        { kind: "output", text: "Hello ", data: null },
        { kind: "output", text: "world", data: null },
        { kind: "done", text: "", data: null },
      ]),
    );
    renderWidget();

    fireEvent.click(await screen.findByRole("button", { name: /Run Codex CLI/i }));
    fireEvent.change(screen.getByLabelText("Prompt for Codex CLI"), {
      target: { value: "summarise the repo" },
    });
    // Running an agent starts a local process, so it is confirmed first: the
    // Run button opens the dialog, and the dialog's action actually runs it.
    fireEvent.click(screen.getByRole("button", { name: /Run agent/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^Run agent$/ }));

    const pane = await screen.findByTestId("agent-output");
    await waitFor(() => expect(pane).toHaveTextContent("Hello world"));
    expect(pane).toHaveTextContent(/Completed/i);
    expect(mockRunAgent).toHaveBeenCalledWith("codex", "summarise the repo", expect.any(AbortSignal));
  });

  it("renders tool and error frames distinctly", async () => {
    mockRunAgent.mockImplementation(() =>
      streamOf([
        { kind: "tool", text: "read_file(app.py)", data: null },
        { kind: "error", text: "agent could not reach the model", data: null },
        { kind: "done", text: "", data: null },
      ]),
    );
    renderWidget();

    fireEvent.click(await screen.findByRole("button", { name: /Run Codex CLI/i }));
    fireEvent.change(screen.getByLabelText("Prompt for Codex CLI"), {
      target: { value: "do it" },
    });
    // Running an agent starts a local process, so it is confirmed first: the
    // Run button opens the dialog, and the dialog's action actually runs it.
    fireEvent.click(screen.getByRole("button", { name: /Run agent/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^Run agent$/ }));

    expect(await screen.findByText("read_file(app.py)")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/could not reach the model/i);
  });

  it("surfaces an honest backend error when the run helper throws", async () => {
    mockRunAgent.mockImplementation(() => {
       
      async function* thrower(): AsyncGenerator<AgentEvent, void, unknown> {
        throw new Error("Codex CLI is not installed on this host.");
      }
      return thrower();
    });
    renderWidget();

    fireEvent.click(await screen.findByRole("button", { name: /Run Codex CLI/i }));
    fireEvent.change(screen.getByLabelText("Prompt for Codex CLI"), {
      target: { value: "go" },
    });
    // Running an agent starts a local process, so it is confirmed first: the
    // Run button opens the dialog, and the dialog's action actually runs it.
    fireEvent.click(screen.getByRole("button", { name: /Run agent/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^Run agent$/ }));

    expect(await screen.findByText(/is not installed on this host/i)).toBeInTheDocument();
  });

  it("shows an honest error state when the catalogue fails to load", async () => {
    mockGetBackends.mockRejectedValue(new Error("Agent backends unavailable"));
    renderWidget();
    expect(await screen.findByText(/Agent backends unavailable/i)).toBeInTheDocument();
  });
});
