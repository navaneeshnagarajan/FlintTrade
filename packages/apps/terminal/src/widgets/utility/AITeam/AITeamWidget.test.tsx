import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.ai", () => ({
  getTeamConfig: vi.fn(),
  updateTeamConfig: vi.fn(),
  runTeamAnalysis: vi.fn(),
}));
import { getTeamConfig, updateTeamConfig, runTeamAnalysis } from "@/services/ftApi.ai";
import AITeamWidget from "./AITeamWidget";

const mockConfig = getTeamConfig as unknown as ReturnType<typeof vi.fn>;
const mockUpdate = updateTeamConfig as unknown as ReturnType<typeof vi.fn>;
const mockAnalyse = runTeamAnalysis as unknown as ReturnType<typeof vi.fn>;

const AGENTS = [
  { name: "Technical Analyst", role_type: "technical", system_prompt: "", enabled: true, temperature: 0.3 },
  { name: "Risk Manager", role_type: "risk_manager", system_prompt: "", enabled: true, temperature: 0.1 },
];

const RESULT = {
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
    mockConfig.mockResolvedValue({ agents: AGENTS });
    mockUpdate.mockResolvedValue({ agents: AGENTS });
    mockAnalyse.mockResolvedValue(RESULT);
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
    await waitFor(() => expect(mockAnalyse).toHaveBeenCalledWith("NIFTY", "NSE_INDEX"));
  });

  it("surfaces a configure-LLM message when analysis fails", async () => {
    mockAnalyse.mockRejectedValue(new Error("LLM not configured"));
    renderWidget();
    await screen.findByText("Technical Analyst");

    fireEvent.click(screen.getByRole("button", { name: /run team analysis/i }));

    expect(await screen.findByText(/configure an LLM provider in Settings/i)).toBeInTheDocument();
  });

  it("saves toggled agent enablement via updateTeamConfig", async () => {
    renderWidget();
    await screen.findByText("Technical Analyst");

    // Save is disabled until a toggle makes the roster dirty.
    fireEvent.click(screen.getByRole("switch", { name: /toggle technical analyst/i }));

    const saveBtn = screen.getByRole("button", { name: /save team configuration/i });
    await waitFor(() => expect(saveBtn).toBeEnabled());
    fireEvent.click(saveBtn);

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({
        agents: [
          { name: "Technical Analyst", role_type: "technical", system_prompt: "", enabled: false, temperature: 0.3 },
          { name: "Risk Manager", role_type: "risk_manager", system_prompt: "", enabled: true, temperature: 0.1 },
        ],
      }),
    );
  });
});
