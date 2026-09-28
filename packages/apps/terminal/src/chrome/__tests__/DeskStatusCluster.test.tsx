import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { DeskStatusCluster } from "../DeskStatusCluster";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { resetOperatorSignals, useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { LAYA_NOT_QUALIFIED_FOR_LIVE, LAYA_START_COMMAND, LAYA_START_DOCS_HREF } from "@/lib/layaStatus";

describe("DeskStatusCluster", () => {
  beforeEach(() => {
    resetOperatorSignals();
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
    useModeStore.setState({ mode: "explore" });
  });

  it("shows Laya Down beside a connected broker and suggest-only LLM", () => {
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
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Laya Down");
    expect(screen.getByTestId("llm-surface")).toHaveTextContent("LLM Connected (suggest only)");
    expect(screen.getByTestId("desk-status").textContent).not.toMatch(/Decision/);
    expect(screen.getByTestId("desk-status").textContent).toMatch(
      /Broker Connected\s*·\s*Laya Down\s*·\s*LLM Connected \(suggest only\)/,
    );
  });

  it("shows Laya Down until a heartbeat reports otherwise", () => {
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Laya Down");
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
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Laya Degraded");
    expect(screen.getByTestId("laya-degraded-limits")).toHaveTextContent("Laya Degraded — tighter limits");
    expect(screen.getByTestId("desk-status").textContent).not.toMatch(/Blocked/);
    expect(screen.getByTestId("laya-degraded-limits").className).not.toMatch(/text-loss/);
  });

  it("shows Laya Ready when the LLM is not configured", () => {
    useModeStore.setState({ mode: "practice" });
    useOperatorSignalStore.setState({
      decisionStatus: "ready",
      layaPracticeStatus: "ready",
      layaLiveQualified: true,
      llmChrome: null,
    });
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("broker-surface")).toHaveTextContent("Broker Unavailable");
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Laya Ready");
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
    expect(chip).toHaveTextContent("Laya Ready");
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
    expect(chip).toHaveTextContent("Laya Down");
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
    expect(screen.getByTestId("laya-surface")).toHaveTextContent("Laya Down");
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
    expect(chip).toHaveTextContent("Laya Still loading");
    expect(chip.textContent).not.toMatch(/Down/);
    expect(chip).toHaveAttribute("title", `Still loading. Next: ${LAYA_START_COMMAND}`);
    expect(chip).toHaveAttribute(
      "aria-label",
      `Laya Still loading. Still loading. Next: ${LAYA_START_COMMAND}`,
    );
    expect(chip).toHaveAttribute("data-laya-live-reason", "");
    fireEvent.click(chip);
    expect(screen.getByRole("dialog", { name: "Laya Still loading" })).toHaveTextContent("Still loading");
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
    expect(screen.getByRole("button", { name: "Start Laya" })).toBeInTheDocument();
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
    expect(chip).toHaveTextContent("Laya Down");
    expect(chip).toHaveAttribute("title", `Port 8123 in use. Next: ${LAYA_START_COMMAND}`);
    fireEvent.click(chip);
    expect(screen.getByRole("dialog", { name: "Laya Down" })).toHaveTextContent("Port 8123 in use");
    expect(screen.getByTestId("laya-start-docs")).toHaveAttribute("href", LAYA_START_DOCS_HREF);
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
    expect(chip).toHaveTextContent("Laya Ready");
    expect(chip.className).not.toMatch(/text-loss/);
    fireEvent.click(chip);
    expect(screen.getByRole("dialog", { name: "Laya Ready" })).toHaveTextContent(LAYA_NOT_QUALIFIED_FOR_LIVE);
    expect(screen.queryByRole("button", { name: "Start Laya" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("laya-start-docs")).not.toBeInTheDocument();
  });

  it("starts the sidecar from the Down reason", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );
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
    expect(chip).toHaveAttribute("title", `Stopped. Next: ${LAYA_START_COMMAND}`);
    fireEvent.click(chip);
    fireEvent.click(screen.getByRole("button", { name: "Start Laya" }));
    await screen.findByText("Start requested.");
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/api/v1/laya/start");
    const init = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    fetchSpy.mockRestore();
  });
});
