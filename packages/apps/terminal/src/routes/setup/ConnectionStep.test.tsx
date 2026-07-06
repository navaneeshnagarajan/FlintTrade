import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { useBrokerStore } from "@/stores/brokerStore";
import { ConnectionStep } from "./ConnectionStep";

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: () => ({ isLoading: false, error: null, refetch: vi.fn() }),
}));

vi.mock("@/components/account/BrokerConnect", () => ({
  BrokerConnect: () => <div>Native brokers section</div>,
}));

describe("ConnectionStep", () => {
  beforeEach(() => {
    act(() => {
      useBrokerStore.setState({ accounts: [], activeAccountId: null });
    });
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
    expect(screen.getByRole("button", { name: /connect a write-capable broker/i })).toBeDisabled();
  });

  it("allows continuing when a native broker has a live session", () => {
    act(() => {
      useBrokerStore.setState({
        activeAccountId: null,
        accounts: [
          {
            account_id: "U1",
            broker: "upstox",
            label: "Upstox",
            status: "connected",
            connected_at: null,
            error_message: null,
            is_primary: true,
            source: "native",
            read_only: false,
          },
        ],
      });
    });

    render(<ConnectionStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));

    expect(screen.getByRole("button", { name: /^continue$/i })).toBeEnabled();
  });

  it("keeps continuing disabled when the only connected native session is read-only", () => {
    const onComplete = vi.fn();
    act(() => {
      useBrokerStore.setState({
        activeAccountId: null,
        accounts: [
          {
            account_id: "U1",
            broker: "upstox",
            label: "Upstox Analytics",
            status: "connected",
            connected_at: null,
            error_message: null,
            is_primary: false,
            source: "native",
            read_only: true,
          },
        ],
      });
    });

    render(<ConnectionStep onComplete={onComplete} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));
    const continueButton = screen.getByRole("button", { name: /connect a write-capable broker/i });

    expect(continueButton).toBeDisabled();
    fireEvent.click(continueButton);
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("allows continuing when a gateway broker account is connected", () => {
    act(() => {
      useBrokerStore.setState({
        activeAccountId: null,
        accounts: [
          {
            account_id: "OA1",
            broker: "zerodha",
            label: "OpenAlgo Zerodha",
            status: "connected",
            connected_at: null,
            error_message: null,
            is_primary: true,
            source: "gateway",
          },
        ],
      });
    });

    render(<ConnectionStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));

    expect(screen.getByRole("button", { name: /^continue$/i })).toBeEnabled();
  });

  it("keeps continuing disabled for stale broker accounts", () => {
    act(() => {
      useBrokerStore.setState({
        activeAccountId: null,
        accounts: [
          {
            account_id: "U1",
            broker: "upstox",
            label: "Upstox",
            status: "token_expired",
            connected_at: null,
            error_message: "Needs fresh login",
            is_primary: true,
            source: "native",
          },
        ],
      });
    });

    render(<ConnectionStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));

    expect(screen.getByRole("button", { name: /connect a write-capable broker/i })).toBeDisabled();
  });
});
