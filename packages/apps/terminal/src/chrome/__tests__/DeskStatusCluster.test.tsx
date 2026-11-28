import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { notifyManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DeskStatusCluster, useDeskStatus } from "../DeskStatusCluster";
import { OperatorIncidentProbes } from "../OperatorIncidentProbes";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import {
  resetOperatorSignals,
  useOperatorSignalStore,
  type OperatorSignalSnapshot,
} from "@/stores/operatorSignalStore";
import {
  LAYA_NOT_QUALIFIED_FOR_LIVE,
  LAYA_START_COMMAND,
  LAYA_START_DOCS_HREF,
  OLLAMA_DIGEST_DETAIL,
  OLLAMA_NOT_STARTED_MANAGED,
  OLLAMA_NOT_STARTED_UNMANAGED,
} from "@/lib/layaStatus";

vi.mock("@/hooks/useAdvisorLlmStatus", () => ({
  useAdvisorLlmStatus: () => ({ chrome: "unconfigured" }),
}));

describe("DeskStatusCluster", () => {
  beforeEach(() => {
    resetOperatorSignals();
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
    useModeStore.setState({ mode: "explore" });
    useAuthStore.setState({ status: "logged-out", token: null });
  });

  it("shows Decision model Down beside a connected broker and suggest-only LLM", () => {
    useBrokerStore.setState({
      accounts: [
        {
          account_id: "U1",
          broker: "upstox",
          source: "native",
          status: "connected",
          label: "Primary",
          connected_at: null,
          error_message: null,
          is_primary: true,
        },
      ],
      activeAccountId: "native:upstox:U1",
    });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      llmChrome: "ready",
    });
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("broker-surface")).toHaveTextContent("Broker Connected");
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down");
    expect(screen.getByTestId("llm-surface")).toHaveTextContent("LLM Connected (suggest only)");
    expect(screen.getByTestId("desk-status").textContent).not.toMatch(/Laya/);
    expect(screen.getByTestId("desk-status").textContent).toMatch(
      /Broker Connected\s*·\s*Decision model Down\s*·\s*LLM Connected \(suggest only\)/,
    );
  });

  it("shows Decision model Down until a heartbeat reports otherwise", () => {
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down");
    expect(screen.getByTestId("laya-surface")).not.toHaveTextContent("Ready");
  });

  it("shows tighter Degraded limits without Blocked chrome", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "degraded",
      layaPracticeStatus: "degraded",
      layaLiveQualified: true,
      llmChrome: "ready",
    });
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Degraded");
    expect(screen.getByTestId("laya-degraded-limits")).toHaveTextContent("Decision model degraded. Tighter limits apply.");
    expect(screen.getByTestId("desk-status").textContent).not.toMatch(/Blocked/);
    expect(screen.getByTestId("laya-degraded-limits").className).not.toMatch(/text-loss/);
  });

  it("shows Checking decision model in the neutral colour and never Ready while unconfirmed", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "ready",
      layaPracticeStatus: "ready",
      layaLiveQualified: true,
      layaChecking: true,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Checking");
    expect(chip.textContent).not.toMatch(/Ready/);
    expect(chip.className).toContain("text-text-secondary");
    expect(chip.className).not.toContain("text-loss");
    expect(chip.className).not.toContain("text-amber");
    expect(chip).toHaveAttribute("title", "Checking decision model…");
    fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Checking decision model…");
  });

  it("drops Ready when the order gate has already refused", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "ready",
      layaPracticeStatus: "ready",
      layaLiveQualified: true,
    });
    useOperatorSignalStore.getState().noteLayaDown();
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Down");
    expect(chip.textContent).not.toMatch(/Ready/);
  });

  it("shows Decision model Ready when the LLM is not configured", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "ready",
      layaPracticeStatus: "ready",
      layaLiveQualified: true,
      llmChrome: null,
    });
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("broker-surface")).toHaveTextContent("Broker Unavailable");
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Ready");
    expect(screen.getByTestId("llm-surface")).toHaveTextContent("LLM Not configured");
  });

  it("shows the sidecar state in Practice and never Down while Practice can admit", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "ready",
      layaLiveQualified: false,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Ready");
    expect(chip).not.toHaveTextContent("Down");
    expect(chip).toHaveAttribute("title", LAYA_NOT_QUALIFIED_FOR_LIVE);
    expect(chip).toHaveAttribute("data-laya-live-reason", LAYA_NOT_QUALIFIED_FOR_LIVE);
  });

  it("shows Down on the Live chip when Live is not qualified, with the same tooltip", () => {
    useModeStore.setState({ mode: "live" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "degraded",
      layaLiveQualified: false,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Down");
    expect(chip).toHaveAttribute("data-laya-live-reason", LAYA_NOT_QUALIFIED_FOR_LIVE);
  });

  it("omits the qualification tooltip when Laya is actually Down", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
    });
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down");
    expect(screen.getByTestId("laya-surface")).toHaveAttribute("data-laya-live-reason", "");
  });

  it("shows Still loading during the first load and does not flash Down", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      layaReason: "still_loading",
      layaPort: 8000,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Still loading");
    expect(chip.textContent).not.toMatch(/Down/);
    expect(chip).toHaveAttribute("title", `Still loading. Next: ${LAYA_START_COMMAND}`);
    expect(chip).toHaveAttribute("aria-label", "Decision model Still loading. Still loading");
    expect(chip).toHaveAttribute("data-laya-live-reason", "");
    useAuthStore.setState({ status: "logged-in", token: "session-jwt" });
    fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Still loading");
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
    expect(screen.getByRole("button", { name: "Start decision model" })).toBeInTheDocument();
  });

  it("shows live download progress and stays off Still loading", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      layaReason: "downloading",
      layaPort: 8000,
      layaDownloadBytes: 1_200_000_000,
      layaDownloadTotal: 3_400_000_000,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Downloading");
    expect(chip.textContent).not.toMatch(/Down\b/);
    expect(chip.className).not.toMatch(/text-loss/);
    expect(chip.textContent).not.toMatch(/Still loading/);
    expect(chip.getAttribute("title") ?? "").not.toMatch(/Next:/);
    fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Downloading the model · 1.2 of 3.4 GB");
    expect(screen.queryByTestId("laya-reason-tooltip")).not.toBeInTheDocument();
    expect(screen.queryByText(/Next:/)).not.toBeInTheDocument();
  });

  it("shows a failed download without launching copy", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      layaReason: "download_failed",
      layaPort: 8000,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Down");
    expect(chip).toHaveAttribute("title", "Check your connection, then start the decision model again.");
    fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Can't download the model");
    expect(screen.getByTestId("laya-reason-tooltip")).toHaveTextContent(
      "Check your connection, then start the decision model again.",
    );
  });

  it("shows download_failed after a restored checkpoint, not the wrong revision", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      layaReason: "download_failed",
      layaPort: 8000,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Down");
    expect(chip).toHaveAttribute("title", "Check your connection, then start the decision model again.");
    fireEvent.click(chip);
    const reason = screen.getByTestId("laya-reason");
    expect(reason).toHaveTextContent("Can't download the model");
    expect(reason).not.toHaveTextContent("Wrong model version");
    expect(screen.getByTestId("laya-reason-tooltip")).toHaveTextContent(
      "Check your connection, then start the decision model again.",
    );
  });

  it("names a port clash in the tooltip", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      layaReason: "port_in_use",
      layaPort: 8123,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Down");
    expect(chip).toHaveAttribute("title", `Port 8123 in use. Next: ${LAYA_START_COMMAND}`);
    fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Port 8123 in use");
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
    expect(screen.queryByRole("button", { name: "Start decision model" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Start the Laya model/)).not.toBeInTheDocument();
  });

  it("shows the model-check tooltip and the start-laya guide when the model cannot be verified", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      layaReason: "unverified",
      layaPort: 8000,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Down");
    expect(chip).toHaveAttribute(
      "title",
      "Installed model doesn't match the pinned version. Restart the decision model. If it repeats, reinstall the model.",
    );
    fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Can't verify the model");
    expect(screen.getByTestId("laya-reason-tooltip")).toHaveTextContent(
      "Installed model doesn't match the pinned version. Restart the decision model. If it repeats, reinstall the model.",
    );
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
    expect(screen.getByTestId("laya-start-docs").getAttribute("href")).toContain("#start-the-decision-model");
  });

  it("opens the Practice Ready reason and does not offer Start while the sidecar is up", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "ready",
      layaLiveQualified: false,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Ready");
    expect(chip.className).not.toMatch(/text-loss/);
    fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent(LAYA_NOT_QUALIFIED_FOR_LIVE);
    expect(screen.queryByRole("button", { name: "Start decision model" })).not.toBeInTheDocument();
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
  });

  it("starts the sidecar from the popover and shows Checking until Ready", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );
    useAuthStore.setState({ status: "logged-in", token: "session-jwt" });
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      layaReason: "stopped",
      layaPort: 8000,
    });
    render(<DeskStatusCluster />);
    const chip = screen.getByTestId("laya-surface");
    fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Stopped");
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
    fireEvent.click(screen.getByRole("button", { name: "Start decision model" }));
    await waitFor(() => expect(chip).toHaveTextContent("Decision model Checking"));
    expect(chip.textContent).not.toMatch(/Ready/);
    expect(chip.textContent).not.toMatch(/Down/);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Checking decision model…");
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/api/v1/decision-model/start");
    const init = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    act(() => {
      useOperatorSignalStore.setState({
        layaPracticeStatus: "ready",
        layaReason: null,
      });
    });
    expect(chip).toHaveTextContent("Decision model Ready");
    fetchSpy.mockRestore();
  });

  it("leaves Start decision model off the popover when the operator is signed out", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaLiveQualified: false,
      layaReason: "not_started",
      layaPort: 8000,
    });
    render(<DeskStatusCluster />);
    fireEvent.click(screen.getByTestId("laya-surface"));
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Not started");
    expect(screen.queryByRole("button", { name: "Start decision model" })).not.toBeInTheDocument();
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
  });

  describe("stacked Status rows", () => {
    function openStacked(signals: Partial<OperatorSignalSnapshot>) {
      useModeStore.setState({ mode: "practice" });
      useOperatorSignalStore.setState(signals);
      render(<DeskStatusCluster variant="stacked" />);
    }

    it("shows the Ready reason once, as the bold line", () => {
      openStacked({ decisionStatus: "down", layaPracticeStatus: "ready", layaLiveQualified: false });
      const panel = screen.getByTestId("desk-status");
      expect(panel.textContent?.split(LAYA_NOT_QUALIFIED_FOR_LIVE)).toHaveLength(2);
      const reason = screen.getByTestId("laya-reason");
      expect(reason).toHaveTextContent(LAYA_NOT_QUALIFIED_FOR_LIVE);
      expect(reason.className).toMatch(/font-medium/);
      expect(screen.getByTestId("laya-start-docs")).toBeInTheDocument();
    });

    it("shows a failed download once, with the help line under it", () => {
      openStacked({
        decisionStatus: "down",
        layaPracticeStatus: "down",
        layaLiveQualified: false,
        layaReason: "download_failed",
        layaPort: 8000,
      });
      const panel = screen.getByTestId("desk-status");
      expect(panel.textContent?.split("Can't download the model")).toHaveLength(2);
      expect(panel.textContent?.split("Check your connection, then start the decision model again.")).toHaveLength(2);
      const reason = screen.getByTestId("laya-reason");
      expect(reason).toHaveTextContent("Can't download the model");
      expect(reason.className).toMatch(/font-medium/);
      expect(reason.nextElementSibling).toBe(screen.getByTestId("laya-reason-tooltip"));
    });

    it("shows a model that cannot be verified once", () => {
      openStacked({
        decisionStatus: "down",
        layaPracticeStatus: "down",
        layaLiveQualified: false,
        layaReason: "unverified",
        layaPort: 8000,
      });
      expect(screen.getByTestId("desk-status").textContent?.split("Can't verify the model")).toHaveLength(2);
    });

    it("shows Downloading in the neutral colour with the progress line once", () => {
      openStacked({
        decisionStatus: "down",
        layaPracticeStatus: "down",
        layaLiveQualified: false,
        layaReason: "downloading",
        layaPort: 8000,
        layaDownloadBytes: 1_200_000_000,
        layaDownloadTotal: 3_400_000_000,
      });
      const row = screen.getByTestId("laya-surface");
      expect(row).toHaveTextContent("Decision model Downloading");
      expect(row.textContent).not.toMatch(/Down\b/);
      expect(row.querySelector(".text-loss")).toBeNull();
      const panel = screen.getByTestId("desk-status");
      expect(panel.textContent?.split("Downloading the model · 1.2 of 3.4 GB")).toHaveLength(2);
    });

    it("keeps the grey description only when there is no reason line", () => {
      openStacked({ decisionStatus: "ready", layaPracticeStatus: "ready", layaLiveQualified: true });
      expect(screen.queryByTestId("laya-reason")).not.toBeInTheDocument();
      expect(screen.getByTestId("desk-status")).toHaveTextContent("Checks every order before it is placed.");
    });
  });

  it.each(["inline", "stacked"] as const)("keeps the Ollama wrong-revision chip free of the digest sentence (%s)", (variant) => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaReason: "wrong_revision",
      layaRoute: "ollama",
      layaManaged: true,
    });
    render(<DeskStatusCluster variant={variant} />);
    const chip = screen.getByTestId("laya-surface");
    expect(chip).toHaveTextContent("Decision model Down");
    if (variant === "inline") {
      expect(chip).toHaveAttribute("aria-label", "Decision model Down. Wrong model version");
      expect(chip).toHaveAttribute("title", "Wrong model loaded. Expected convaiinnovations/laya.");
    }
    for (const surface of [chip.textContent, chip.getAttribute("aria-label"), chip.getAttribute("title")]) {
      expect((surface ?? "").toLowerCase()).not.toContain("digest");
      expect((surface ?? "").toLowerCase()).not.toContain("ollama");
      expect((surface ?? "").toLowerCase()).not.toContain("tag");
    }
    if (variant === "inline") fireEvent.click(chip);
    const reason = screen.getByTestId("laya-reason");
    expect(reason).toHaveTextContent("Wrong model version");
    expect(reason.textContent?.toLowerCase()).not.toContain("digest");
    expect(reason.textContent?.toLowerCase()).not.toContain("ollama");
    expect(reason.textContent?.toLowerCase()).not.toContain("tag");
    expect(screen.getByTestId("laya-status-detail")).toHaveTextContent(OLLAMA_DIGEST_DETAIL);
    expect(screen.queryByText(/sidecar/i)).not.toBeInTheDocument();
  });

  it.each(["inline", "stacked"] as const)("offers Start on a managed Ollama install and names no sidecar command (%s)", (variant) => {
    useAuthStore.setState({ status: "logged-in", token: "session-jwt" });
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaReason: "not_started",
      layaRoute: "ollama",
      layaManaged: true,
    });
    render(<DeskStatusCluster variant={variant} />);
    const chip = screen.getByTestId("laya-surface");
    if (variant === "inline") {
      expect(chip).toHaveAttribute("title", OLLAMA_NOT_STARTED_MANAGED);
      expect(chip.getAttribute("title")).not.toContain(LAYA_START_COMMAND);
    }
    if (variant === "inline") fireEvent.click(chip);
    expect(screen.getByTestId("laya-reason")).toHaveTextContent("Not started");
    expect(screen.getByTestId("laya-status-detail")).toHaveTextContent(OLLAMA_NOT_STARTED_MANAGED);
    expect(screen.getByRole("button", { name: "Start decision model" })).toBeInTheDocument();
    expect(screen.queryByTestId("laya-start-docs")).not.toBeInTheDocument();
    expect(screen.queryByText(/sidecar/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/laya_runtime/)).not.toBeInTheDocument();
  });

  it.each(["inline", "stacked"] as const)("tells an unmanaged Ollama install how to start, with no Start action (%s)", (variant) => {
    useAuthStore.setState({ status: "logged-in", token: "session-jwt" });
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "down",
      layaPracticeStatus: "down",
      layaReason: "not_started",
      layaRoute: "ollama",
      layaManaged: false,
    });
    render(<DeskStatusCluster variant={variant} />);
    const chip = screen.getByTestId("laya-surface");
    if (variant === "inline") expect(chip).toHaveAttribute("title", OLLAMA_NOT_STARTED_UNMANAGED);
    if (variant === "inline") fireEvent.click(chip);
    expect(screen.getByTestId("laya-status-detail")).toHaveTextContent(OLLAMA_NOT_STARTED_UNMANAGED);
    expect(screen.queryByRole("button", { name: "Start decision model" })).not.toBeInTheDocument();
    expect(screen.queryByText(/sidecar/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/laya_runtime/)).not.toBeInTheDocument();
  });
});


function LayaStatusMirror() {
  const status = useDeskStatus();
  return <span data-testid="mirrored-laya-status">{status.decision}</span>;
}

describe.each(["inline", "stacked"] as const)("Laya heartbeat identity in %s Status", (variant) => {
  let client: QueryClient;
  let heartbeat: () => Response | Promise<Response>;

  function pingResponse(body: unknown): Response {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  function ollamaHeartbeat(managed: boolean, reason: string | null = null) {
    return {
      status: "ok",
      decision_model: reason ? "down" : "ready",
      decision_model_practice: reason ? "down" : "ready",
      decision_model_live_qualified: !reason,
      decision_model_reason: reason,
      decision_model_route: "ollama",
      decision_model_managed: managed,
      decision_model_checking: false,
    };
  }

  beforeEach(() => {
    resetOperatorSignals();
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
    useAuthStore.setState({ status: "logged-in", token: "session-jwt" });
    useModeStore.setState({ mode: "practice" });
    // Deliver query updates inside act, so stale-response assertions cannot
    // pass merely because React Query has not notified its subscribers yet.
    notifyManager.setScheduler((callback) => { callback(); });
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/v1/ping")) return heartbeat();
      // Keep health, public-site probes, and the Start request fully synthetic.
      return pingResponse({ status: "ok" });
    });
  });

  afterEach(() => {
    client.clear();
    notifyManager.setScheduler((callback) => { setTimeout(callback, 0); });
    vi.restoreAllMocks();
  });

  async function renderHeartbeat(managed: boolean, reason: string | null = null) {
    heartbeat = () => pingResponse(ollamaHeartbeat(managed));
    render(
      <QueryClientProvider client={client}>
        <OperatorIncidentProbes />
        <LayaStatusMirror />
        <DeskStatusCluster variant={variant} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(useOperatorSignalStore.getState().layaRoute).toBe("ollama"));
    expect(useOperatorSignalStore.getState().layaManaged).toBe(managed);
    await waitFor(() => expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Ready"));
    if (reason !== null) {
      await nextHeartbeat(() => pingResponse(ollamaHeartbeat(managed, reason)));
      await waitFor(() => expect(useOperatorSignalStore.getState().layaReason).toBe(reason));
    }
    if (variant === "inline") fireEvent.click(screen.getByTestId("laya-surface"));
  }

  async function nextHeartbeat(response: () => Response) {
    heartbeat = response;
    await act(async () => {
      await client.refetchQueries({ queryKey: ["operator", "ping"], exact: true });
    });
  }

  const failedHeartbeats = [
    ["HTTP failure", () => new Response("unavailable", { status: 503 })],
    ["transport failure", () => { throw new Error("failed to fetch"); }],
    ["invalid JSON", () => new Response("not json", { status: 200 })],
    ["empty body", () => pingResponse({})],
    ["missing heartbeat", () => pingResponse({ status: "ok" })],
    ["invalid status", () => pingResponse({ status: "error", decision_model: "ready", decision_model_practice: "ready" })],
    ["invalid backend", () => pingResponse({ status: "ok", decision_model: "ready", decision_model_route: "unknown" })],
    ["invalid management", () => pingResponse({ ...ollamaHeartbeat(true), decision_model_managed: "true" })],
  ] as const;

  describe.each([false, true])("previously confirmed managed=%s", (managed) => {
    it.each(failedHeartbeats)("keeps backend identity and reports Down after %s", async (_name, failure) => {
      await renderHeartbeat(managed);
      expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Ready");
      await nextHeartbeat(failure);
      await waitFor(() => expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down"));
      expect(useOperatorSignalStore.getState()).toMatchObject({
        layaRoute: "ollama",
        layaManaged: managed,
        decisionStatus: "down",
        layaPracticeStatus: "down",
        layaChecking: false,
        layaLiveQualified: false,
      });
      expect(screen.queryByTestId("laya-start-docs")).not.toBeInTheDocument();
      expect(document.body).not.toHaveTextContent(LAYA_START_COMMAND);
      expect(document.body).not.toHaveTextContent(/sidecar|laya_runtime/i);
      if (managed) expect(screen.getByRole("button", { name: "Start decision model" })).toBeInTheDocument();
      else expect(screen.queryByRole("button", { name: "Start decision model" })).not.toBeInTheDocument();
    });
  });

  it("changes a confirmed Ollama backend to sidecar only after a valid sidecar heartbeat", async () => {
    await renderHeartbeat(false);
    await nextHeartbeat(() => pingResponse({
      status: "ok",
      decision_model: "down",
      decision_model_practice: "down",
      decision_model_reason: "not_started",
    }));
    await waitFor(() => expect(useOperatorSignalStore.getState().layaRoute).toBeNull());
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down");
    expect(useOperatorSignalStore.getState().layaManaged).toBe(false);
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
    expect(screen.getByRole("button", { name: "Start decision model" })).toBeInTheDocument();
  });

  it.each(["unverified", "download_failed"])("settles Start when the next terminal heartbeat is still %s", async (reason) => {
    await renderHeartbeat(true, reason);
    fireEvent.click(screen.getByRole("button", { name: "Start decision model" }));
    await waitFor(() => expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Checking"));
    if (reason === "download_failed") {
      await nextHeartbeat(() => pingResponse({
        ...ollamaHeartbeat(true, "still_loading"),
        decision_model_checking: true,
      }));
      expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Checking");
    }
    await nextHeartbeat(() => pingResponse(ollamaHeartbeat(true, reason)));
    await waitFor(() => expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down"));
    expect(screen.getByTestId("mirrored-laya-status")).toHaveTextContent("Down");
    expect(screen.getByRole("button", { name: "Start decision model" })).toBeInTheDocument();
    expect(screen.queryByTestId("laya-start-docs")).not.toBeInTheDocument();
  });

  it("does not settle Start from an older in-flight heartbeat", async () => {
    await renderHeartbeat(true, "unverified");
    let resolveStale: (response: Response) => void = () => { throw new Error("No pending heartbeat"); };
    heartbeat = () => new Promise<Response>((resolve) => { resolveStale = resolve; });
    let staleQuery: Promise<void>;
    act(() => {
      staleQuery = client.refetchQueries({ queryKey: ["operator", "ping"], exact: true });
    });
    await waitFor(() => expect(client.isFetching({ queryKey: ["operator", "ping"], exact: true })).toBe(1));
    fireEvent.click(screen.getByRole("button", { name: "Start decision model" }));
    await waitFor(() => expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Checking"));
    await act(async () => {
      resolveStale(pingResponse(ollamaHeartbeat(true, "download_failed")));
      await staleQuery;
    });
    expect(useOperatorSignalStore.getState()).toMatchObject({
      layaChecking: true,
      layaReason: "unverified",
    });
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Checking");
    expect(screen.queryByRole("button", { name: "Start decision model" })).not.toBeInTheDocument();
    await nextHeartbeat(() => pingResponse(ollamaHeartbeat(true, "unverified")));
    await waitFor(() => expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down"));
    expect(screen.getByRole("button", { name: "Start decision model" })).toBeInTheDocument();
  });

  it("preserves a newer Down decision against an older Ready heartbeat", async () => {
    await renderHeartbeat(true);
    let resolveStale: (response: Response) => void = () => { throw new Error("No pending heartbeat"); };
    heartbeat = () => new Promise<Response>((resolve) => { resolveStale = resolve; });
    let staleQuery: Promise<void>;
    act(() => {
      staleQuery = client.refetchQueries({ queryKey: ["operator", "ping"], exact: true });
    });
    await waitFor(() => expect(client.isFetching({ queryKey: ["operator", "ping"], exact: true })).toBe(1));
    act(() => { useOperatorSignalStore.getState().noteLayaDown(); });
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down");
    await act(async () => {
      resolveStale(pingResponse({
        ...ollamaHeartbeat(true),
        decision_model: "down",
        decision_model_live_qualified: false,
      }));
      await staleQuery;
    });
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Down");
    expect(useOperatorSignalStore.getState().layaPracticeStatus).toBe("down");
  });

  it.each([
    { status: "down", reason: "download_failed", label: "Down" },
    { status: "ready", reason: null, label: "Ready" },
    { status: "degraded", reason: null, label: "Degraded" },
  ])("settles accepted Start on $status without another unrelated render", async ({ status, reason, label }) => {
    await renderHeartbeat(true, "not_started");
    fireEvent.click(screen.getByRole("button", { name: "Start decision model" }));
    await waitFor(() => expect(screen.getByTestId("laya-surface")).toHaveTextContent("Decision model Checking"));
    expect(screen.queryByRole("button", { name: "Start decision model" })).not.toBeInTheDocument();
    await nextHeartbeat(() => pingResponse({
      ...ollamaHeartbeat(true, reason),
      decision_model: status,
      decision_model_practice: status,
    }));
    await waitFor(() => expect(screen.getByTestId("laya-surface")).toHaveTextContent(`Decision model ${label}`));
    expect(screen.getByTestId("mirrored-laya-status")).toHaveTextContent(label);
    if (status === "down") {
      expect(screen.getByTestId("laya-reason")).toHaveTextContent("Can't download the model");
      expect(screen.getByRole("button", { name: "Start decision model" })).toBeInTheDocument();
    } else {
      expect(screen.queryByRole("button", { name: "Start decision model" })).not.toBeInTheDocument();
    }
    expect(screen.queryByTestId("laya-start-docs")).not.toBeInTheDocument();
  });
});
