import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ConnectionStep } from "./ConnectionStep";
import { listNativeAccounts } from "@/services/ftApi.native";
import { gatewayApi } from "@/services/gatewayApi";
import type { BrokerInfo } from "@/types/broker";

// The direct tab now reuses the native Settings → Brokers connect. Stub it so
// this test covers the ConnectionStep shell (tabs, coming-soon roster, continue
// gate) without pulling in the full native connect UI + its network calls.
vi.mock("@/tools/Settings/BrokersSection", () => ({
  BrokersSection: () => <div>Native broker connect</div>,
}));

vi.mock("@/services/ftApi.native", () => ({
  listNativeAccounts: vi.fn(),
}));

vi.mock("@/services/gatewayApi", () => ({
  gatewayApi: { listBrokers: vi.fn() },
}));

const mockAccounts = vi.mocked(listNativeAccounts);
const mockBrokers = vi.mocked(gatewayApi.listBrokers);

function bridgeBroker(name: string, display_name: string): BrokerInfo {
  return {
    name,
    display_name,
    auth_flow: "oauth_redirect",
    exchanges: [],
    max_symbols_per_ws: 0,
    supports_streaming: false,
    oauth_url_template: null,
    is_sandbox: false,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockAccounts.mockResolvedValue([]);
  mockBrokers.mockResolvedValue([]);
});

function renderStep(onComplete = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ConnectionStep onComplete={onComplete} />
    </QueryClientProvider>,
  );
  return onComplete;
}

describe("ConnectionStep", () => {
  it("defaults to FlintTrade's direct broker gateway", () => {
    renderStep();

    expect(screen.getByRole("button", { name: /flinttrade gateway/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(/No separate OpenAlgo setup needed/i)).toBeInTheDocument();
  });

  it("shows the native broker connect in the direct tab", () => {
    renderStep();

    expect(screen.getByText("Native broker connect")).toBeInTheDocument();
  });

  it("keeps Continue disabled with no connected account", () => {
    renderStep();

    expect(
      screen.getByRole("button", { name: /connect at least one broker to continue/i }),
    ).toBeDisabled();
  });

  it("counts only a LIVE session for Continue, not a stale/needs-relogin row", async () => {
    mockAccounts.mockResolvedValue([
      { adapter_id: "upstox", account_id: "x", has_session: false, needs_relogin: true },
    ]);
    renderStep();

    await waitFor(() => expect(mockAccounts).toHaveBeenCalled());
    // Let the resolved query re-render, then confirm the dead row did NOT
    // satisfy the gate (no enabled "Continue" appears).
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByRole("button", { name: /^continue$/i })).toBeNull();
    expect(
      screen.getByRole("button", { name: /connect at least one broker to continue/i }),
    ).toBeDisabled();
  });

  it("enables Continue and completes once a live account exists", async () => {
    mockAccounts.mockResolvedValue([{ adapter_id: "upstox", account_id: "x", has_session: true }]);
    const onComplete = renderStep();

    const continueBtn = await screen.findByRole("button", { name: /^continue$/i });
    expect(continueBtn).not.toBeDisabled();

    fireEvent.click(continueBtn);
    expect(onComplete).toHaveBeenCalledWith({
      host: "http://127.0.0.1:5100",
      apiKey: "direct-connect",
      wsPort: "8765",
    });
  });

  it("lists only bridge-only brokers as coming soon, excluding native ones", async () => {
    mockBrokers.mockResolvedValue([bridgeBroker("dhan", "Dhan"), bridgeBroker("zerodha", "Zerodha")]);
    renderStep();

    await screen.findByText("Zerodha"); // bridge-only → shown as coming soon
    expect(screen.getByText(/More brokers — coming soon/i)).toBeInTheDocument();
    // "Dhan" IS a native adapter — it must not appear in the coming-soon roster.
    expect(screen.queryByText("Dhan")).not.toBeInTheDocument();
  });
});
