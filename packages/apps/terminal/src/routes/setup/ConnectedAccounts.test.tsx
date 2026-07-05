import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { BrokerAccount } from "@/types/broker";

const mocks = vi.hoisted(() => ({
  accounts: [] as BrokerAccount[],
  refetch: vi.fn(),
  gatewayRemove: vi.fn(),
  gatewayReconnect: vi.fn(),
  gatewaySetPrimary: vi.fn(),
  removeNative: vi.fn(),
  reloginNative: vi.fn(),
  setPrimaryNative: vi.fn(),
}));

vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: () => ({ refetch: mocks.refetch }),
}));

vi.mock("@/stores/brokerStore", () => ({
  brokerAccountKey: (account: BrokerAccount) => [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":"),
  useBrokerStore: (selector: (s: { accounts: BrokerAccount[] }) => unknown) =>
    selector({ accounts: mocks.accounts }),
}));

vi.mock("@/services/gatewayApi", () => ({
  gatewayApi: {
    removeAccount: mocks.gatewayRemove,
    reconnectAccount: mocks.gatewayReconnect,
    setPrimary: mocks.gatewaySetPrimary,
  },
}));

vi.mock("@/services/ftApi.native", () => ({
  removeNativeAccount: mocks.removeNative,
  reloginNativeAccount: mocks.reloginNative,
  setPrimaryNativeAccount: mocks.setPrimaryNative,
}));

import { ConnectedAccounts } from "./ConnectedAccounts";

describe("ConnectedAccounts", () => {
  beforeEach(() => {
    mocks.accounts = [];
    mocks.refetch.mockReset().mockResolvedValue({});
    mocks.gatewayRemove.mockReset().mockResolvedValue({});
    mocks.gatewayReconnect.mockReset().mockResolvedValue({});
    mocks.gatewaySetPrimary.mockReset().mockResolvedValue({});
    mocks.removeNative.mockReset().mockResolvedValue(undefined);
    mocks.reloginNative.mockReset().mockResolvedValue({ has_session: true });
    mocks.setPrimaryNative.mockReset().mockResolvedValue(undefined);
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

    render(<ConnectedAccounts />);

    expect(screen.queryByLabelText(/Set Upstox main as primary account/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Reconnect Upstox main/i));
    await waitFor(() => expect(mocks.reloginNative).toHaveBeenCalledWith("upstox", "UPX-1"));
    expect(mocks.gatewayReconnect).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText(/Remove Upstox main/i));
    await waitFor(() => expect(mocks.removeNative).toHaveBeenCalledWith("upstox", "UPX-1"));
    expect(mocks.gatewayRemove).not.toHaveBeenCalled();
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

    render(<ConnectedAccounts />);

    fireEvent.click(screen.getByLabelText(/Set Upstox main as primary account/i));

    await waitFor(() => expect(mocks.setPrimaryNative).toHaveBeenCalledWith("upstox", "UPX-1"));
    expect(mocks.gatewaySetPrimary).not.toHaveBeenCalled();
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
  });
});
