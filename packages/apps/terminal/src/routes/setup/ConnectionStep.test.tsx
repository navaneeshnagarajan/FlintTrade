import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { ConnectionStep } from "./ConnectionStep";

const setupMocks = vi.hoisted(() => ({
  useBrokerAccounts: vi.fn(() => ({ isLoading: false, error: null, refetch: vi.fn() })),
  brokerConnectProps: null as null | Record<string, unknown>,
}));

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: setupMocks.useBrokerAccounts,
}));

vi.mock("@/components/account/BrokerConnect", () => ({
  BrokerConnect: (props: Record<string, unknown>) => {
    setupMocks.brokerConnectProps = props;
    return <div>Native brokers section</div>;
  },
}));

describe("ConnectionStep", () => {
  beforeEach(() => {
    setupMocks.useBrokerAccounts.mockClear();
    setupMocks.brokerConnectProps = null;
    act(() => {
      useBrokerStore.setState({ accounts: [], activeAccountId: null });
      useConnectionStore.setState({ apiKey: "" });
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps brokerless Practice as the primary connect CTA", () => {
    const onComplete = vi.fn();
    render(<ConnectionStep onComplete={onComplete} />);

    const skip = screen.getByRole("button", { name: /continue without a broker/i });
    expect(skip).toBeEnabled();
    expect(screen.getByText(/simulated fills, no real money/i)).toBeInTheDocument();
    expect(screen.queryByText(/SandboxEngine/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Settings fallback/i)).toBeInTheDocument();
    expect(screen.queryByText(/Recommended/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Native brokers section")).not.toBeInTheDocument();

    fireEvent.click(skip);
    expect(onComplete).toHaveBeenCalledWith({ brokerConnected: false });
  });

  it("records brokerless continuation through its own callback", () => {
    const onComplete = vi.fn();
    const onContinueWithoutBroker = vi.fn();
    render(
      <ConnectionStep
        onComplete={onComplete}
        onContinueWithoutBroker={onContinueWithoutBroker}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /continue without a broker/i }));
    expect(onContinueWithoutBroker).toHaveBeenCalledTimes(1);
    expect(onComplete).not.toHaveBeenCalled();
  });









  it("shows the native connect (with the risk note) after selecting the FlintTrade Native tab", () => {
    render(<ConnectionStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));

    expect(screen.getByText("Native brokers section")).toBeInTheDocument();
    const nativeHelper = screen.getByText(/Native Dhan \+ Kotak Neo stays Connected \(read\)/i);
    expect(nativeHelper).toBeInTheDocument();
    expect(nativeHelper).not.toHaveTextContent(/API smoke/i);
    expect(screen.getAllByText(/Connected \(read\)/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Live read only until funded unlock/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Dhan, Upstox, INDmoney/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect dhan or neo for connected \(read\)/i })).toBeDisabled();
    // No connected accounts at all — the read-only demotion reason must not show.
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(setupMocks.useBrokerAccounts).not.toHaveBeenCalled();
    expect(setupMocks.brokerConnectProps).toEqual({});
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
    const continueButton = screen.getByRole("button", { name: /connect dhan or neo for connected \(read\)/i });

    expect(continueButton).toBeDisabled();
    fireEvent.click(continueButton);
    expect(onComplete).not.toHaveBeenCalled();

    // Item 5: the gate must explain WHY — the account came back read-only
    // (demoted from write routing), not just sit disabled with no reason.
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/read-only/i);
    expect(note).toHaveTextContent(/demoted from write routing/i);
    expect(note).toHaveTextContent(/re-authenticate/i);
  });

  it("rejects a retired account source even when marked connected", () => {
    act(() => {
      useBrokerStore.setState({
        activeAccountId: null,
        accounts: [
          {
            account_id: "retired-account",
            broker: "zerodha",
            label: "Retired account",
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

    expect(screen.getByRole("button", { name: /connect dhan or neo/i })).toBeDisabled();
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

    expect(screen.getByRole("button", { name: /connect dhan or neo for connected \(read\)/i })).toBeDisabled();
  });

  it("ignores gateway Dhan or Neo rows on the native tab", () => {
    act(() => {
      useBrokerStore.setState({
        activeAccountId: null,
        accounts: [
          {
            account_id: "N1",
            broker: "kotakneo",
            label: "Neo via native broker",
            status: "connected",
            connected_at: null,
            error_message: null,
            is_primary: false,
            source: "gateway",
            read_only: true,
            read_smoke_ok: true,
          },
        ],
      });
    });

    render(<ConnectionStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));
    expect(screen.getByRole("button", { name: /connect dhan or neo for connected \(read\)/i })).toBeDisabled();
  });

  it("allows continuing when Dhan or Neo is Connected (read)", () => {
    const onComplete = vi.fn();
    act(() => {
      useBrokerStore.setState({
        activeAccountId: null,
        accounts: [
          {
            account_id: "N1",
            broker: "kotakneo",
            label: "Neo",
            status: "connected",
            connected_at: null,
            error_message: null,
            is_primary: false,
            source: "native",
            read_only: true,
            read_smoke_ok: true,
          },
        ],
      });
    });

    render(<ConnectionStep onComplete={onComplete} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));
    const continueButton = screen.getByRole("button", { name: /^continue$/i });
    expect(continueButton).toBeEnabled();
    expect(screen.getByRole("note")).toHaveTextContent(/Connected \(read\)/i);
    expect(screen.getByRole("note")).not.toHaveTextContent(/API smoke/i);
    expect(screen.getByRole("note")).toHaveTextContent(/Live read only until funded unlock/i);
    fireEvent.click(continueButton);
    expect(onComplete).toHaveBeenCalled();
  });
});
