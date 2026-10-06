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

  it("lists only native accounts and discards retired gateway rows", async () => {
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
        read_smoke_ok: false,
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
        read_smoke_ok: false,
        needs_relogin: true,
        login_retryable: false,
      },
    ]);
  });

  it("forwards the AbortSignal through native account discovery", async () => {
    const controller = new AbortController();

    await listBrokerAccounts([], controller.signal);
    expect(mocks.listGateway).not.toHaveBeenCalled();
    expect(mocks.listNative).toHaveBeenCalledWith(controller.signal);

    mocks.listNative.mockClear();
    await listNativeBrokerAccounts(controller.signal);
    expect(mocks.listNative).toHaveBeenCalledWith(controller.signal);

    mocks.listNative.mockClear();
    await listLiveNativeReadAccounts(controller.signal);
    expect(mocks.listNative).toHaveBeenCalledWith(controller.signal);
  });

  it("does not resurrect retired rows after native discovery fails", async () => {
    mocks.listNative.mockRejectedValue(new Error("Native discovery unavailable"));
    await expect(listBrokerAccounts([gatewayAccount])).rejects.toThrow("Native discovery unavailable");
  });

  it("dispatches account actions by account source", async () => {
    const nativeRef = { source: "native" as const, broker: "upstox", account_id: "UPX1" };
    const gatewayRef = { source: "gateway" as const, broker: "zerodha", account_id: "GW1" };

    const actionKey = "00000000-0000-4000-8000-000000000001";
    await removeBrokerAccount(nativeRef, actionKey);
    await reconnectBrokerAccount(nativeRef, actionKey);
    await setPrimaryBrokerAccount(nativeRef, actionKey);
    expect(mocks.removeNative).toHaveBeenCalledWith("upstox", "UPX1", actionKey);
    expect(mocks.reloginNative).toHaveBeenCalledWith("upstox", "UPX1", undefined, actionKey);
    expect(mocks.setNativePrimary).toHaveBeenCalledWith("upstox", "UPX1", actionKey);

    await expect(removeBrokerAccount(gatewayRef, actionKey)).rejects.toThrow("Only native broker accounts");
    await expect(reconnectBrokerAccount(gatewayRef, actionKey)).rejects.toThrow("Only native broker accounts");
    await expect(setPrimaryBrokerAccount(gatewayRef, actionKey)).rejects.toThrow("Only native broker accounts");
    expect(mocks.removeGateway).not.toHaveBeenCalled();
    expect(mocks.reconnectGateway).not.toHaveBeenCalled();
    expect(mocks.setGatewayPrimary).not.toHaveBeenCalled();
  });

  it("lists only live native read accounts in the shared account client", async () => {
    mocks.listNative.mockResolvedValue([
      { adapter_id: "dhan", account_id: "DH1", has_session: false, is_primary: true },
      { adapter_id: "dhan", account_id: "DH2", is_primary: false },
      { adapter_id: "upstox", account_id: "UPX1", has_session: true, is_primary: false },
      { adapter_id: "kotakneo", account_id: "K1", has_session: true, is_primary: true },
    ]);

    await expect(listLiveNativeReadAccounts()).resolves.toEqual([
      { adapter_id: "upstox", account_id: "UPX1", is_primary: false },
      { adapter_id: "kotakneo", account_id: "K1", is_primary: true },
    ]);
  });

  it.each([null, "native:upstox:SHARED"])(
    "does not substitute another live session when the chosen identity %s has none",
    (activeAccountId) => {
      const brokerAccounts: BrokerAccount[] = [
        { ...gatewayAccount, source: "native", broker: "dhan", account_id: "SHARED", is_primary: false },
        { ...gatewayAccount, source: "native", broker: "upstox", account_id: "SHARED", is_primary: true },
      ];
      const readAccounts = [{ adapter_id: "dhan", account_id: "SHARED", is_primary: true }];

      expect(selectNativeReadAccount(readAccounts, brokerAccounts, activeAccountId)).toBeUndefined();
    },
  );

  it("keeps the store-selected primary identity when live discovery has a different primary", () => {
    const brokerAccounts: BrokerAccount[] = [
      { ...gatewayAccount, source: "native", broker: "dhan", account_id: "D1", status: "disconnected" },
      { ...gatewayAccount, source: "native", broker: "upstox", account_id: "U1", is_primary: false },
    ];
    const readAccounts = [
      { adapter_id: "upstox", account_id: "U1", is_primary: true },
      { adapter_id: "dhan", account_id: "D1", is_primary: false },
    ];

    expect(selectNativeReadAccount(readAccounts, brokerAccounts, null)).toEqual({
      adapter_id: "dhan", account_id: "D1", is_primary: false,
    });
  });

  it("does not resolve ambiguous store identities from the live-session subset", () => {
    const brokerAccounts: BrokerAccount[] = [
      { ...gatewayAccount, source: "native", broker: "dhan", account_id: "D1", is_primary: false },
      { ...gatewayAccount, source: "native", broker: "upstox", account_id: "U1", is_primary: false },
    ];
    const readAccounts = [{ adapter_id: "upstox", account_id: "U1", is_primary: true }];

    expect(selectNativeReadAccount(readAccounts, brokerAccounts, null)).toBeUndefined();
    expect(selectNativeReadAccount(readAccounts, brokerAccounts, "native:upstox:MISSING")).toBeUndefined();
  });

  it("preserves encoded composite selectors without conflating same-id broker accounts", () => {
    const brokerAccounts: BrokerAccount[] = [
      { ...gatewayAccount, source: "native", broker: "dhan", account_id: "A:B/1" },
      { ...gatewayAccount, source: "native", broker: "upstox", account_id: "A:B/1", is_primary: false },
    ];
    const readAccounts = [
      { adapter_id: "dhan", account_id: "A:B/1", is_primary: true },
      { adapter_id: "upstox", account_id: "A:B/1", is_primary: false },
    ];

    expect(selectNativeReadAccount(readAccounts, brokerAccounts, "native:upstox:A%3AB%2F1")).toEqual({
      adapter_id: "upstox", account_id: "A:B/1", is_primary: false,
    });
    expect(selectNativeReadAccount(readAccounts, brokerAccounts, "A:B/1")).toBeUndefined();
  });

  it("preserves an unambiguous legacy selector for the exact live native identity", () => {
    const brokerAccounts: BrokerAccount[] = [
      { ...gatewayAccount, source: "native", broker: "dhan", account_id: "D1", is_primary: false },
    ];
    const readAccounts = [
      { adapter_id: "upstox", account_id: "D1", is_primary: true },
      { adapter_id: "dhan", account_id: "D1", is_primary: false },
    ];

    expect(selectNativeReadAccount(readAccounts, brokerAccounts, "D1")).toEqual({
      adapter_id: "dhan", account_id: "D1", is_primary: false,
    });
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
