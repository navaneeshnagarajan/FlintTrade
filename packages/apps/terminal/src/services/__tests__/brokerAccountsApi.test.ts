import { describe, expect, it, vi, beforeEach } from "vitest";
import type { BrokerAccount } from "@/types/broker";
import type { NativeAccount } from "@/services/ftApi.native";

const mocks = vi.hoisted(() => ({
  listGateway: vi.fn<(signal?: AbortSignal) => Promise<BrokerAccount[]>>(),
  listNative: vi.fn<(signal?: AbortSignal) => Promise<NativeAccount[]>>(),
  removeGateway: vi.fn(),
  reconnectGateway: vi.fn(),
  setGatewayPrimary: vi.fn(),
  removeNative: vi.fn(),
  reloginNative: vi.fn(),
  setNativePrimary: vi.fn(),
}));

vi.mock("@/services/gatewayApi", () => ({
  gatewayApi: {
    listAccounts: mocks.listGateway,
    removeAccount: mocks.removeGateway,
    reconnectAccount: mocks.reconnectGateway,
    setPrimary: mocks.setGatewayPrimary,
  },
}));

vi.mock("@/services/ftApi.native", () => ({
  listNativeAccounts: mocks.listNative,
  removeNativeAccount: mocks.removeNative,
  reloginNativeAccount: mocks.reloginNative,
  setPrimaryNativeAccount: mocks.setNativePrimary,
}));

import {
  listLiveNativeReadAccounts,
  listBrokerAccounts,
  listNativeBrokerAccounts,
  reconnectBrokerAccount,
  removeBrokerAccount,
  selectNativeReadAccount,
  setPrimaryBrokerAccount,
} from "../brokerAccountsApi";

const gatewayAccount: BrokerAccount = {
  account_id: "GW1",
  broker: "zerodha",
  label: "Zerodha Bridge",
  status: "connected",
  connected_at: null,
  error_message: null,
  is_primary: true,
  source: "gateway",
};

describe("brokerAccountsApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listGateway.mockResolvedValue([]);
    mocks.listNative.mockResolvedValue([]);
  });

  it("lists gateway and native accounts through one merged contract", async () => {
    mocks.listGateway.mockResolvedValue([gatewayAccount]);
    mocks.listNative.mockResolvedValue([
      {
        adapter_id: "upstox",
        account_id: "UPX1",
        label: "Upstox Native",
        has_session: true,
        read_only: true,
        is_primary: false,
      },
      {
        adapter_id: "dhan",
        account_id: "DH1",
        needs_relogin: true,
        login_error: "Needs a fresh token.",
      },
    ]);

    await expect(listBrokerAccounts()).resolves.toEqual([
      gatewayAccount,
      {
        account_id: "UPX1",
        broker: "upstox",
        label: "Upstox Native",
        status: "connected",
        connected_at: null,
        error_message: null,
        is_primary: false,
        source: "native",
        expires_at: null,
        read_only: true,
        needs_relogin: false,
        login_retryable: false,
      },
      {
        account_id: "DH1",
        broker: "dhan",
        label: "DH1",
        status: "token_expired",
        connected_at: null,
        error_message: "Needs a fresh token.",
        is_primary: false,
        source: "native",
        expires_at: null,
        read_only: false,
        needs_relogin: true,
        login_retryable: false,
      },
    ]);
  });

  it("forwards one AbortSignal through both account sources and native discovery", async () => {
    const controller = new AbortController();

    await listBrokerAccounts([], controller.signal);
    expect(mocks.listGateway).toHaveBeenCalledWith(controller.signal);
    expect(mocks.listNative).toHaveBeenCalledWith(controller.signal);

    mocks.listNative.mockClear();
    await listNativeBrokerAccounts(controller.signal);
    expect(mocks.listNative).toHaveBeenCalledWith(controller.signal);

    mocks.listNative.mockClear();
    await listLiveNativeReadAccounts(controller.signal);
    expect(mocks.listNative).toHaveBeenCalledWith(controller.signal);
  });

  it("keeps a failed source's previous rows until that source recovers", async () => {
    mocks.listGateway.mockRejectedValue(new Error("Gateway unavailable"));

    await expect(listBrokerAccounts([gatewayAccount])).resolves.toEqual([gatewayAccount]);
  });

  it("dispatches account actions by account source", async () => {
    const nativeRef = { source: "native" as const, broker: "upstox", account_id: "UPX1" };
    const gatewayRef = { source: "gateway" as const, broker: "zerodha", account_id: "GW1" };

    await removeBrokerAccount(nativeRef);
    await reconnectBrokerAccount(nativeRef);
    await setPrimaryBrokerAccount(nativeRef);
    expect(mocks.removeNative).toHaveBeenCalledWith("upstox", "UPX1");
    expect(mocks.reloginNative).toHaveBeenCalledWith("upstox", "UPX1");
    expect(mocks.setNativePrimary).toHaveBeenCalledWith("upstox", "UPX1");

    await removeBrokerAccount(gatewayRef);
    await reconnectBrokerAccount(gatewayRef);
    await setPrimaryBrokerAccount(gatewayRef);
    expect(mocks.removeGateway).toHaveBeenCalledWith("GW1");
    expect(mocks.reconnectGateway).toHaveBeenCalledWith("GW1");
    expect(mocks.setGatewayPrimary).toHaveBeenCalledWith("GW1");
  });

  it("lists only live native read accounts in the shared account client", async () => {
    mocks.listNative.mockResolvedValue([
      { adapter_id: "dhan", account_id: "DH1", has_session: false, is_primary: true },
      { adapter_id: "upstox", account_id: "UPX1", has_session: true, is_primary: false },
      { adapter_id: "kotakneo", account_id: "K1", has_session: true, is_primary: true },
    ]);

    await expect(listLiveNativeReadAccounts()).resolves.toEqual([
      { adapter_id: "upstox", account_id: "UPX1", is_primary: false },
      { adapter_id: "kotakneo", account_id: "K1", is_primary: true },
    ]);
  });

  it("selects the active native read account before the primary fallback", () => {
    const readAccounts = [
      { adapter_id: "dhan", account_id: "SHARED", is_primary: true },
      { adapter_id: "upstox", account_id: "SHARED", is_primary: false },
    ];
    const brokerAccounts: BrokerAccount[] = [
      { ...gatewayAccount, account_id: "SHARED", broker: "zerodha", source: "gateway" },
      {
        account_id: "SHARED",
        broker: "upstox",
        label: "Upstox",
        status: "connected",
        connected_at: null,
        error_message: null,
        is_primary: false,
        source: "native",
      },
    ];

    expect(selectNativeReadAccount(readAccounts, brokerAccounts, "native:upstox:SHARED")).toEqual({
      adapter_id: "upstox",
      account_id: "SHARED",
      is_primary: false,
    });
    expect(selectNativeReadAccount(readAccounts, brokerAccounts, "gateway:zerodha:SHARED")).toBeUndefined();
    expect(selectNativeReadAccount(readAccounts, brokerAccounts, "SHARED")).toBeUndefined();
    expect(selectNativeReadAccount(readAccounts, brokerAccounts, null)).toEqual({
      adapter_id: "upstox",
      account_id: "SHARED",
      is_primary: false,
    });
  });
});
