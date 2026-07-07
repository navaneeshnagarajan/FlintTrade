import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
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
      useConnectionStore.setState({ host: "", apiKey: "", wsUrl: "" });
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
    expect(screen.getByLabelText(/REST port/i)).toHaveValue("5000");
    // The native section is behind the secondary tab, not shown by default.
    expect(screen.queryByText("Native brokers section")).not.toBeInTheDocument();
  });

  it("does not commit untested values to the connection store when Test Connection runs", async () => {
    // Item 4: the old handleTest wrote host/apiKey into connectionStore BEFORE
    // the test ran, so a failed test still repointed the app at an unverified
    // host. The test must exercise the candidate values only; the store is
    // written on explicit Continue (persistSetupChoices).
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ status: "error", message: "unreachable" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectionStep onComplete={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/openalgo-compatible url/i), {
      target: { value: "http://unverified-host:5000" },
    });
    fireEvent.change(screen.getByLabelText(/openalgo-compatible api key/i), {
      target: { value: "candidate-api-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    // The candidate values went to the backend test endpoint...
    expect(String(fetchMock.mock.calls[0][0])).toContain("/ft-api/v1/test-connection");
    // ...but the live connection store was NOT touched.
    expect(useConnectionStore.getState().host).toBe("");
    expect(useConnectionStore.getState().apiKey).toBe("");
  });

  it("shows the native connect (with the risk note) after selecting the FlintTrade Native tab", () => {
    render(<ConnectionStep onComplete={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /flinttrade native/i }));

    expect(screen.getByText("Native brokers section")).toBeInTheDocument();
    expect(screen.getByText(/availability and login fields come from the broker catalogue/i)).toBeInTheDocument();
    expect(screen.getByText(/use at your own risk/i)).toBeInTheDocument();
    expect(screen.queryByText(/Dhan, Upstox, INDmoney/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /connect a write-capable broker/i })).toBeDisabled();
    // No connected accounts at all — the read-only demotion reason must not show.
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
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

    // Item 5: the gate must explain WHY — the account came back read-only
    // (demoted from write routing), not just sit disabled with no reason.
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/read-only/i);
    expect(note).toHaveTextContent(/demoted from write routing/i);
    expect(note).toHaveTextContent(/re-authenticate/i);
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
