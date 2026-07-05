import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ConnectionStep } from "./ConnectionStep";

let _nativeAccounts: Array<{ has_session?: boolean }> = [];

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: _nativeAccounts, isLoading: false, isError: false }),
}));

vi.mock("@/components/account/BrokerConnect", () => ({
  BrokerConnect: () => <div>Native brokers section</div>,
}));

vi.mock("@/services/ftApi.native", () => ({
  listNativeAccounts: vi.fn(),
}));

describe("ConnectionStep", () => {
  beforeEach(() => {
    _nativeAccounts = [];
  });

  it("defaults to the OpenAlgo (primary) connect tab", () => {
    // Principle 2: OpenAlgo is the recommended, community-tested path, so it is
    // the default tab; native is the secondary option behind the second tab.
    render(<ConnectionStep onComplete={vi.fn()} />);

    expect(screen.getByRole("button", { name: /openalgo bridge/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /flinttrade native/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByText(/Recommended/i)).toBeInTheDocument();
    // The native section is behind the secondary tab, not shown by default.
    expect(screen.queryByText("Native brokers section")).not.toBeInTheDocument();
  });

  it("shows the native connect (with the risk note) after selecting the FlintTrade Native tab", () => {
    render(<ConnectionStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));

    expect(screen.getByText("Native brokers section")).toBeInTheDocument();
    expect(screen.getByText(/availability and login fields come from the broker catalogue/i)).toBeInTheDocument();
    expect(screen.getByText(/use at your own risk/i)).toBeInTheDocument();
    expect(screen.queryByText(/Dhan, Upstox, INDmoney/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect at least one broker/i })).toBeDisabled();
  });

  it("allows continuing when a native broker has a live session", () => {
    _nativeAccounts = [{ has_session: true }];

    render(<ConnectionStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));

    expect(screen.getByRole("button", { name: /^continue$/i })).toBeEnabled();
  });
});
