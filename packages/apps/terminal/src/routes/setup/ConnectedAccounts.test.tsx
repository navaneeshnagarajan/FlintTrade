import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BrokerAccount } from "@/types/broker";

const mocks = vi.hoisted(() => ({
  accounts: [] as BrokerAccount[],
  refetch: vi.fn(),
  removeBroker: vi.fn(),
  reconnectBroker: vi.fn(),
  setPrimaryBroker: vi.fn(),
}));

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: () => ({ refetch: mocks.refetch }),
}));

import { useBrokerStore } from "@/stores/brokerStore";

vi.mock("@/services/brokerAccountsApi", () => ({
  removeBrokerAccount: mocks.removeBroker,
  reconnectBrokerAccount: mocks.reconnectBroker,
  setPrimaryBrokerAccount: mocks.setPrimaryBroker,
}));

import { ConnectedAccounts } from "./ConnectedAccounts";

describe("ConnectedAccounts", () => {
  beforeEach(() => {
    mocks.accounts = [];
    mocks.refetch.mockReset().mockResolvedValue({});
    mocks.removeBroker.mockReset().mockResolvedValue(undefined);
    mocks.reconnectBroker.mockReset().mockResolvedValue({ has_session: true });
    mocks.setPrimaryBroker.mockReset().mockResolvedValue(undefined);
  });

  it("routes native account actions through the native broker API", async () => {
    mocks.accounts = [{
      account_id: "UPX-1",
      broker: "upstox",
      label: "Upstox main",
      status: "token_expired",
      connected_at: null,
      error_message: "needs fresh login",
      is_primary: false,
      source: "native",
    }];

    useBrokerStore.setState({ accounts: mocks.accounts, activeAccountId: null });
    render(<ConnectedAccounts />);

    expect(screen.queryByLabelText(/Set Upstox main as primary account/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Reconnect Upstox main/i));
    await waitFor(() => expect(mocks.reconnectBroker).toHaveBeenCalledWith(mocks.accounts[0], expect.any(String)));

    fireEvent.click(screen.getByLabelText(/Remove Upstox main/i));
    await waitFor(() => expect(mocks.removeBroker).toHaveBeenCalledWith(mocks.accounts[0], expect.any(String)));
    expect(mocks.refetch).toHaveBeenCalledTimes(2);
  });

  it("can promote a connected native account to primary", async () => {
    mocks.accounts = [{
      account_id: "UPX-1",
      broker: "upstox",
      label: "Upstox main",
      status: "connected",
      connected_at: null,
      error_message: null,
      is_primary: false,
      source: "native",
    }];

    useBrokerStore.setState({ accounts: mocks.accounts, activeAccountId: null });
    render(<ConnectedAccounts />);

    fireEvent.click(screen.getByLabelText(/Set Upstox main as primary account/i));

    await waitFor(() => expect(mocks.setPrimaryBroker).toHaveBeenCalledWith(mocks.accounts[0], expect.any(String)));
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
  });

  it("does not offer Set primary on a stale (disconnected) gateway account", () => {
    // Shared canPromotePrimaryAccount rule: setup must match Settings ›
    // Brokers — a dead gateway row must never be promotable to the live
    // write default (execution.default) from the wizard either.
    mocks.accounts = [{
      account_id: "GW-1",
      broker: "zerodha",
      label: "Zerodha gateway",
      status: "token_expired",
      connected_at: null,
      error_message: "token expired",
      is_primary: false,
      source: "gateway",
    }];

    useBrokerStore.setState({ accounts: mocks.accounts, activeAccountId: null });
    render(<ConnectedAccounts />);

    expect(screen.queryByLabelText(/Set Zerodha gateway as primary account/i)).not.toBeInTheDocument();
  });

  it("does not offer Set primary on a read-only gateway account", () => {
    mocks.accounts = [{
      account_id: "GW-2",
      broker: "zerodha",
      label: "Zerodha analytics",
      status: "connected",
      connected_at: null,
      error_message: null,
      is_primary: false,
      source: "gateway",
      read_only: true,
    }];

    useBrokerStore.setState({ accounts: mocks.accounts, activeAccountId: null });
    render(<ConnectedAccounts />);

    expect(screen.queryByLabelText(/Set Zerodha analytics as primary account/i)).not.toBeInTheDocument();
  });

  it("offers Set primary on a connected write-capable gateway account", () => {
    mocks.accounts = [{
      account_id: "GW-3",
      broker: "zerodha",
      label: "Zerodha main",
      status: "connected",
      connected_at: null,
      error_message: null,
      is_primary: false,
      source: "gateway",
    }];

    useBrokerStore.setState({ accounts: mocks.accounts, activeAccountId: null });
    render(<ConnectedAccounts />);

    expect(screen.getByLabelText(/Set Zerodha main as primary account/i)).toBeInTheDocument();
  });

  it("does not promote a read-only native account to primary", () => {
    mocks.accounts = [{
      account_id: "UPX-1",
      broker: "upstox",
      label: "Upstox analytics",
      status: "connected",
      connected_at: null,
      error_message: null,
      is_primary: false,
      source: "native",
      read_only: true,
    }];

    useBrokerStore.setState({ accounts: mocks.accounts, activeAccountId: null });
    render(<ConnectedAccounts />);

    expect(screen.getByText(/upstox .* read-only/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Set Upstox analytics as primary account/i)).not.toBeInTheDocument();
    expect(mocks.setPrimaryBroker).not.toHaveBeenCalled();
  });
});
