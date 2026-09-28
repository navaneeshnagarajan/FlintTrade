import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { DeskStatusCluster } from "../DeskStatusCluster";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { resetOperatorSignals, useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { LAYA_NOT_QUALIFIED_FOR_LIVE } from "@/lib/layaStatus";

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
});
