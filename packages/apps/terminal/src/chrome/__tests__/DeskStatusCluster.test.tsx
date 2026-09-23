import { describe, expect, it, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { DeskStatusCluster } from "../DeskStatusCluster";
import { useBrokerStore } from "@/stores/brokerStore";
import { resetOperatorSignals, useOperatorSignalStore } from "@/stores/operatorSignalStore";

describe("DeskStatusCluster", () => {
  beforeEach(() => {
    resetOperatorSignals();
    useBrokerStore.setState({ accounts: [], activeAccountId: null });
  });

  it("shows Decision Down beside a connected broker and suggest-only chat", () => {
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
    useOperatorSignalStore.setState({ decisionStatus: "down", llmChrome: "ready" });
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("broker-surface")).toHaveTextContent("Broker Connected");
    expect(screen.getByTestId("decision-surface")).toHaveTextContent("Decision Down");
    expect(screen.getByTestId("llm-surface")).toHaveTextContent("Chat Connected (suggest only)");
  });

  it("shows Decision Ready when chat is not configured", () => {
    useOperatorSignalStore.setState({ decisionStatus: "ready", llmChrome: null });
    render(<DeskStatusCluster />);
    expect(screen.getByTestId("broker-surface")).toHaveTextContent("Broker Unavailable");
    expect(screen.getByTestId("decision-surface")).toHaveTextContent("Decision Ready");
    expect(screen.getByTestId("llm-surface")).toHaveTextContent("Chat Not configured");
  });
});
