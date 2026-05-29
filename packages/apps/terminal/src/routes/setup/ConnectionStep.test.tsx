import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ConnectionStep } from "./ConnectionStep";

vi.mock("@/hooks/useBrokerAuth", () => ({
  useBrokerAuth: () => ({
    flowState: { step: "idle" },
    startFlow: vi.fn(),
    submitCredentials: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("@/stores/brokerStore", () => ({
  useBrokerStore: (selector: (state: { accounts: unknown[] }) => unknown) => selector({ accounts: [] }),
}));

vi.mock("./ConnectedAccounts", () => ({
  ConnectedAccounts: () => <div>Connected accounts</div>,
}));

vi.mock("./BrokerPicker", () => ({
  BrokerPicker: () => <div>Broker picker</div>,
}));

vi.mock("./AuthFlowAPIKey", () => ({
  AuthFlowAPIKey: () => <div>API key auth</div>,
}));

vi.mock("./AuthFlowTOTP", () => ({
  AuthFlowTOTP: () => <div>TOTP auth</div>,
}));

describe("ConnectionStep", () => {
  it("defaults to FlintTrade's direct broker gateway", () => {
    render(<ConnectionStep onComplete={vi.fn()} />);

    expect(screen.getByRole("button", { name: /flinttrade gateway/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(/No separate OpenAlgo setup needed/i)).toBeInTheDocument();
  });
});
