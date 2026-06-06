import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.ai", () => ({
  getOpenClawStatus: vi.fn(),
  getOpenClawAgents: vi.fn(),
  deployOpenClawAgent: vi.fn(),
  stopOpenClawAgent: vi.fn(),
}));
import {
  getOpenClawStatus,
  getOpenClawAgents,
  deployOpenClawAgent,
  stopOpenClawAgent,
} from "@/services/ftApi.ai";
import OpenClawWidget from "./OpenClawWidget";

const mockStatus = getOpenClawStatus as unknown as ReturnType<typeof vi.fn>;
const mockAgents = getOpenClawAgents as unknown as ReturnType<typeof vi.fn>;
const mockDeploy = deployOpenClawAgent as unknown as ReturnType<typeof vi.fn>;
const mockStop = stopOpenClawAgent as unknown as ReturnType<typeof vi.fn>;

function renderWidget() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <OpenClawWidget />
    </QueryClientProvider>,
  );
}

const AGENT = {
  id: "a-1",
  name: "scalper-nifty",
  status: "running",
  strategy: "momentum",
  symbols: ["NIFTY"],
  created_at: "",
};

describe("OpenClawWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStatus.mockResolvedValue({ connected: true });
    mockAgents.mockResolvedValue({ agents: [] });
    mockDeploy.mockResolvedValue({ status: "success", agent_id: "a-1" });
    mockStop.mockResolvedValue({ status: "success" });
  });

  it("lists running agents from the gateway", async () => {
    mockAgents.mockResolvedValue({ agents: [AGENT] });
    renderWidget();
    expect(await screen.findByText("scalper-nifty")).toBeInTheDocument();
  });

  it("stops an agent via the gateway", async () => {
    mockAgents.mockResolvedValue({ agents: [AGENT] });
    renderWidget();
    fireEvent.click(await screen.findByRole("button", { name: /stop scalper-nifty/i }));
    await waitFor(() => expect(mockStop).toHaveBeenCalledWith("a-1"));
  });

  it("deploys an agent with the parsed config", async () => {
    renderWidget();
    await screen.findByText(/Connected/i); // status resolved -> deploy enabled

    fireEvent.change(screen.getByLabelText("Agent name"), { target: { value: "my-agent" } });
    fireEvent.change(screen.getByLabelText("Symbols"), { target: { value: "NIFTY, BANKNIFTY" } });
    fireEvent.click(screen.getByRole("button", { name: /deploy agent/i }));

    await waitFor(() =>
      expect(mockDeploy).toHaveBeenCalledWith({
        name: "my-agent",
        strategy: "momentum",
        symbols: ["NIFTY", "BANKNIFTY"],
      }),
    );
  });

  it("shows the gateway offline and disables deploy when disconnected", async () => {
    mockStatus.mockResolvedValue({ connected: false });
    renderWidget();
    // Exact match: the status badge, not the "Gateway offline — no agents." list text.
    expect(await screen.findByText("Gateway offline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /deploy agent/i })).toBeDisabled();
  });
});
