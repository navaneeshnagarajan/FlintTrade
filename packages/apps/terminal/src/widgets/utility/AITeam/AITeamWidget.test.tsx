import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.ai", () => ({
  getTeamConfig: vi.fn(),
  updateTeamConfig: vi.fn(),
  runTeamAnalysisStream: vi.fn(),
}));
import {
  getTeamConfig,
  updateTeamConfig,
  runTeamAnalysisStream,
  type TeamAnalyzeResponse,
  type TeamStreamFrame,
} from "@/services/ftApi.ai";
import AITeamWidget from "./AITeamWidget";

const mockConfig = getTeamConfig as unknown as ReturnType<typeof vi.fn>;
const mockUpdate = updateTeamConfig as unknown as ReturnType<typeof vi.fn>;
const mockAnalyse = runTeamAnalysisStream as unknown as ReturnType<typeof vi.fn>;

const AGENTS = [
  {
    name: "Technical Analyst",
    role_type: "technical",
    system_prompt: "",
    enabled: true,
    temperature: 0.3,
    role_id: "technical",
    model_tier: "quick",
  },
  {
    name: "Risk Manager",
    role_type: "risk_manager",
    system_prompt: "",
    enabled: true,
    temperature: 0.1,
    role_id: "risk",
    model_tier: "quick",
  },
];

const PRESETS = [
  {
    name: "derivatives_desk",
    description: "Options and futures desk",
    agents: [
      { role: "technical", system_prompt: "Read the tape", model_tier: "quick" },
      { role: "risk", system_prompt: "Judge the trade", model_tier: "deep" },
    ],
  },
];

const PRESET_AGENTS = [
  {
    name: "Options Analyst",
    role_type: "technical",
    system_prompt: "",
    enabled: true,
    temperature: 0.2,
    role_id: "options_analyst",
    model_tier: "quick",
  },
];

const RESULT: TeamAnalyzeResponse = {
  analysis: {
    symbol: "NIFTY",
    exchange: "NSE_INDEX",
    agent_analyses: [
      { agent_name: "Technical Analyst", role_type: "technical", report: "Bullish breakout above 24000.", signal: "BUY", confidence: 0.72, timestamp: "", error: "" },
    ],
    consensus_signal: "BUY",
    consensus_confidence: 0.68,
    consensus_reasoning: "Majority bullish.",
    timestamp: "",
    errors: [],
  },
  recommendation: {
    symbol: "NIFTY",
    exchange: "NSE_INDEX",
    action: "BUY",
    confidence: 0.68,
    reasoning: "Majority bullish.",
    agent_count: 2,
    bullish_count: 1,
    bearish_count: 0,
    neutral_count: 1,
    timestamp: "",
  },
};

async function* streamOf(frames: TeamStreamFrame[]): AsyncGenerator<TeamStreamFrame, void, unknown> {
  for (const frame of frames) yield frame;
}

const RESULT_STREAM: TeamStreamFrame[] = [
  {
    type: "event",
    event: {
      task_id: "technical",
      agent_role: "Technical Analyst",
      event_type: "started",
      data: {},
      timestamp: "2026-07-10T00:00:00Z",
    },
  },
  {
    type: "event",
    event: {
      task_id: "technical",
      agent_role: "Technical Analyst",
      event_type: "completed",
      data: {},
      timestamp: "2026-07-10T00:00:01Z",
    },
  },
  { type: "result", data: RESULT },
  { type: "done" },
];

function renderWidget() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AITeamWidget />
    </QueryClientProvider>,
  );
}

describe("AITeamWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConfig.mockResolvedValue({
      agents: AGENTS,
      modes: ["flat", "dag", "sequential", "debate"],
      presets: PRESETS,
      active_preset: "",
    });
    mockUpdate.mockResolvedValue({ agents: AGENTS, presets: PRESETS, active_preset: "" });
    mockAnalyse.mockImplementation(() => streamOf(RESULT_STREAM));
  });

  it("lists the specialist agent roster from the backend", async () => {
    renderWidget();
    expect(await screen.findByText("Technical Analyst")).toBeInTheDocument();
    expect(screen.getByText("Risk Manager")).toBeInTheDocument();
  });

  it("runs a team analysis and renders the consensus and per-agent report", async () => {
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));

    expect(await screen.findByText("Consensus")).toBeInTheDocument();
    // Consensus action appears (badge) and the agent's real report text shows.
    expect(screen.getByText(/Bullish breakout above 24000/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(mockAnalyse).toHaveBeenCalledWith(
        "NIFTY",
        "NSE_INDEX",
        undefined,
        { mode: "flat", preset: null },
        expect.any(AbortSignal),
      ),
    );
  });

  it("renders without crashing when the analysis omits agent_analyses/errors", async () => {
    const partialResult = {
      analysis: {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        consensus_signal: "HOLD",
        consensus_confidence: 0.5,
        consensus_reasoning: "",
        timestamp: "",
        // agent_analyses + errors deliberately omitted (malformed/partial backend response)
      },
      recommendation: {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        action: "HOLD",
        confidence: 0.5,
        reasoning: "",
        agent_count: 0,
        bullish_count: 0,
        bearish_count: 0,
        neutral_count: 0,
        timestamp: "",
      },
    };
    mockAnalyse.mockImplementation(() =>
      streamOf([
        { type: "result", data: partialResult as unknown as TeamAnalyzeResponse },
        { type: "done" },
      ]),
    );
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));

    expect(await screen.findByText("Consensus")).toBeInTheDocument();
  });

  it("surfaces a configure-LLM message when analysis fails", async () => {
    mockAnalyse.mockImplementation(() => {
      async function* fail(): AsyncGenerator<TeamStreamFrame, void, unknown> {
        throw new Error("LLM not configured");
      }
      return fail();
    });
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));

    expect(await screen.findByText(/configure an LLM provider in Settings/i)).toBeInTheDocument();
  });

  it("runs the selected mode and preset and renders lifecycle progress", async () => {
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("button", { name: "DAG" }));
    fireEvent.click(screen.getByRole("combobox", { name: /team preset/i }));
    fireEvent.click(await screen.findByRole("option", { name: /derivatives desk/i }));
    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));

    await waitFor(() =>
      expect(mockAnalyse).toHaveBeenCalledWith(
        "NIFTY",
        "NSE_INDEX",
        undefined,
        { mode: "dag", preset: "derivatives_desk" },
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByRole("status", { name: /team analysis progress/i })).toHaveTextContent(
      /Technical Analyst/i,
    );
    expect(screen.getByRole("status", { name: /team analysis progress/i })).toHaveTextContent(
      /Completed/i,
    );
    expect(screen.getByText("Consensus")).toBeInTheDocument();
  });

  it("saves a selected preset through the preset config contract", async () => {
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("combobox", { name: /team preset/i }));
    fireEvent.click(await screen.findByRole("option", { name: /derivatives desk/i }));
    const saveBtn = screen.getByRole("button", { name: /save team configuration/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    fireEvent.click(saveBtn);

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ preset: "derivatives_desk" }));
  });

  it("runs the custom roster explicitly when a server preset is active", async () => {
    mockConfig.mockResolvedValue({
      agents: PRESET_AGENTS,
      custom_agents: AGENTS,
      modes: ["flat", "dag", "sequential", "debate"],
      presets: PRESETS,
      active_preset: "derivatives_desk",
    });
    renderWidget();
    await screen.findByText("Options Analyst");

    fireEvent.click(screen.getByRole("combobox", { name: /team preset/i }));
    fireEvent.click(await screen.findByRole("option", { name: /custom roster/i }));
    expect(await screen.findByText("Risk Manager")).toBeInTheDocument();
    expect(screen.queryByText("Options Analyst")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));

    await waitFor(() =>
      expect(mockAnalyse).toHaveBeenCalledWith(
        "NIFTY",
        "NSE_INDEX",
        undefined,
        { mode: "flat", preset: null },
        expect.any(AbortSignal),
      ),
    );
  });

  it("runs fixed debate mode without applying the configured preset", async () => {
    mockConfig.mockResolvedValue({
      agents: AGENTS,
      modes: ["flat", "dag", "sequential", "debate"],
      presets: PRESETS,
      active_preset: "derivatives_desk",
    });
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("button", { name: "Debate" }));
    expect(screen.getByRole("combobox", { name: /team preset/i })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));

    await waitFor(() =>
      expect(mockAnalyse).toHaveBeenCalledWith(
        "NIFTY",
        "NSE_INDEX",
        undefined,
        { mode: "debate", preset: null },
        expect.any(AbortSignal),
      ),
    );
  });

  it("surfaces a failure when a stream ends without a result", async () => {
    mockAnalyse.mockImplementation(() => streamOf([RESULT_STREAM[0]]));
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));

    expect(await screen.findByText(/configure an LLM provider in Settings/i)).toBeInTheDocument();
    expect(screen.queryByText("Consensus")).not.toBeInTheDocument();
  });

  it("aborts an in-flight stream from the stop control", async () => {
    let runSignal: AbortSignal | undefined;
    mockAnalyse.mockImplementation(
      (
        _symbol: string,
        _exchange: string,
        _marketData: undefined,
        _options: unknown,
        signal: AbortSignal,
      ) => {
        runSignal = signal;
        async function* pending(): AsyncGenerator<TeamStreamFrame, void, unknown> {
          yield RESULT_STREAM[0];
          await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
        }
        return pending();
      },
    );
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));
    fireEvent.click(await screen.findByRole("button", { name: /stop team analysis/i }));

    expect(runSignal?.aborted).toBe(true);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /run team analysis/i })).toBeEnabled(),
    );
  });

  it("saves toggled agent enablement via updateTeamConfig", async () => {
    renderWidget();
    await screen.findByText("Technical Analyst");

    // Save is disabled until a toggle makes the roster dirty.
    fireEvent.click(screen.getByRole("switch", { name: /toggle technical analyst/i }));
    expect(screen.getByRole("button", { name: /run team analysis/i })).toBeDisabled();

    const saveBtn = screen.getByRole("button", { name: /save team configuration/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    fireEvent.click(saveBtn);

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({
        agents: [
          {
            name: "Technical Analyst",
            role_type: "technical",
            system_prompt: "",
            enabled: false,
            temperature: 0.3,
            role_id: "technical",
            model_tier: "quick",
          },
          {
            name: "Risk Manager",
            role_type: "risk_manager",
            system_prompt: "",
            enabled: true,
            temperature: 0.1,
            role_id: "risk",
            model_tier: "quick",
          },
        ],
      }),
    );
  });
});
