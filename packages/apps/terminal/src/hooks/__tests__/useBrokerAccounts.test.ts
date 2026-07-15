/**
 * Tests for useBrokerAccounts
 *
 * Strategy:
 *   - useBrokerAccounts uses TanStack Query to poll gateway + native account
 *     routes every 10 s, then syncs the merged result into brokerStore.
 *   - gatewayApi.listAccounts and listNativeAccounts are mocked to control the
 *     network responses independently.
 *   - useBrokerStore is mocked so we can capture calls to setAccounts without
 *     involving Zustand's persist/devtools layers.
 *   - renderHook is wrapped in a QueryClientProvider (retry: false, gcTime: 0)
 *     so queries resolve immediately and errors surface without retries.
 *   - The hook's public surface is { isLoading, error, refetch }; UI components
 *     are supposed to read accounts from the Zustand store, not from this hook.
 *
 * Arrange-Act-Assert pattern is applied to every test.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { NativeAccount } from "@/services/ftApi.native";
import type { BrokerAccount } from "@/types/broker";

// ---------------------------------------------------------------------------
// Mocks — declared BEFORE the hook import so vi.mock hoisting works correctly.
// ---------------------------------------------------------------------------

const mockListAccounts = vi.fn<() => Promise<BrokerAccount[]>>();
const mockListNativeAccounts = vi.fn<() => Promise<NativeAccount[]>>();

vi.mock("@/services/gatewayApi", () => ({
  gatewayApi: {
    listAccounts: () => mockListAccounts(),
  },
}));

vi.mock("@/services/ftApi.native", () => ({
  listNativeAccounts: () => mockListNativeAccounts(),
}));

const mockSetAccounts = vi.fn<(accounts: BrokerAccount[]) => void>();
// Last-good store state read by listBrokerAccounts on a one-sided failure.
let mockStoreAccounts: BrokerAccount[] = [];

vi.mock("@/stores/brokerStore", () => ({
  useBrokerStore: Object.assign(
    (selector: (s: { setAccounts: typeof mockSetAccounts }) => unknown) =>
      selector({ setAccounts: mockSetAccounts }),
    { getState: (): { accounts: BrokerAccount[] } => ({ accounts: mockStoreAccounts }) },
  ),
}));

// ---------------------------------------------------------------------------
// Hook import — after mocks.
// ---------------------------------------------------------------------------

import { useBrokerAccounts } from "../useBrokerAccounts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        // Disable automatic refetch so tests are deterministic
        refetchOnWindowFocus: false,
        refetchIntervalInBackground: false,
      },
    },
  });
}

function makeWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

function makeAccount(overrides: Partial<BrokerAccount> = {}): BrokerAccount {
  return {
    account_id: "acc_001",
    broker: "angel",
    label: "Angel - Main",
    status: "connected",
    connected_at: "2026-03-25T09:00:00Z",
    error_message: null,
    is_primary: true,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

let queryClient: QueryClient;

beforeEach(() => {
  queryClient = makeQueryClient();
  mockListAccounts.mockReset();
  mockListNativeAccounts.mockReset();
  mockListNativeAccounts.mockResolvedValue([]);
  mockSetAccounts.mockReset();
  mockStoreAccounts = [];
});

afterEach(() => {
  queryClient.clear();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Initial / loading state
// ---------------------------------------------------------------------------

describe("useBrokerAccounts — loading state", () => {
  it("does not start account reads while the auth session is inactive", async () => {
    renderHook(() => useBrokerAccounts(false), {
      wrapper: makeWrapper(queryClient),
    });

    await act(async () => Promise.resolve());

    expect(mockListAccounts).not.toHaveBeenCalled();
    expect(mockListNativeAccounts).not.toHaveBeenCalled();
    expect(mockSetAccounts).not.toHaveBeenCalled();
  });

  it("does not publish a late account poll after the auth session is disabled", async () => {
    let resolveAccounts!: (accounts: BrokerAccount[]) => void;
    mockListAccounts.mockReturnValue(new Promise((resolve) => {
      resolveAccounts = resolve;
    }));
    const { rerender } = renderHook(
      ({ enabled }) => useBrokerAccounts(enabled),
      { initialProps: { enabled: true }, wrapper: makeWrapper(queryClient) },
    );
    await waitFor(() => expect(mockListAccounts).toHaveBeenCalledOnce());

    rerender({ enabled: false });
    await act(async () => {
      resolveAccounts([makeAccount()]);
      await Promise.resolve();
    });

    expect(mockSetAccounts).not.toHaveBeenCalled();
  });

  it("is in loading state before the query resolves", () => {
    // Arrange — a promise we never resolve so the query stays in-flight
    let _resolve!: (v: BrokerAccount[]) => void;
    mockListAccounts.mockReturnValue(new Promise<BrokerAccount[]>((res) => { _resolve = res; }));

    // Act
    const { result } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    // Assert — isLoading is true while the fetch is pending
    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBeNull();

    // Cleanup — resolve so React doesn't warn about pending state
    act(() => { _resolve([]); });
  });

  it("exposes refetch as a function", async () => {
    // Arrange
    mockListAccounts.mockResolvedValue([]);

    // Act
    const { result } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Assert
    expect(typeof result.current.refetch).toBe("function");
  });
});

// ---------------------------------------------------------------------------
// Successful query
// ---------------------------------------------------------------------------

describe("useBrokerAccounts — successful response", () => {
  it("reports isLoading false and no error after query resolves", async () => {
    // Arrange
    mockListAccounts.mockResolvedValue([]);

    // Act
    const { result } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Assert
    expect(result.current.error).toBeNull();
  });

  it("calls both account-list routes exactly once on mount", async () => {
    // Arrange
    mockListAccounts.mockResolvedValue([]);

    // Act
    renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(mockListAccounts).toHaveBeenCalledTimes(1));
    expect(mockListNativeAccounts).toHaveBeenCalledTimes(1);
  });

  it("syncs returned accounts to brokerStore when query succeeds", async () => {
    // Arrange — two accounts returned by the API
    const accounts: BrokerAccount[] = [
      makeAccount({ account_id: "acc_001", is_primary: true }),
      makeAccount({ account_id: "acc_002", broker: "zerodha", is_primary: false }),
    ];
    mockListAccounts.mockResolvedValue(accounts);

    // Act
    renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    // Assert — setAccounts is called with the full accounts array
    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalledOnce());
    expect(mockSetAccounts).toHaveBeenCalledWith(accounts);
  });

  it("maps native accounts into brokerStore rows", async () => {
    mockListAccounts.mockResolvedValue([]);
    mockListNativeAccounts.mockResolvedValue([
      {
        adapter_id: "upstox",
        account_id: "UPX-1",
        label: "Upstox main",
        is_primary: true,
        has_session: true,
        expires_at: 9_999,
      },
      {
        adapter_id: "dhan",
        account_id: "DHAN-1",
        needs_relogin: true,
        login_error: "login-failed",
      },
      {
        adapter_id: "indmoney",
        account_id: "IND-1",
        login_retryable: true,
        login_error: "Broker login is temporarily unavailable; retry later.",
      },
    ]);

    renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalledOnce());
    expect(mockSetAccounts).toHaveBeenCalledWith([
      {
        account_id: "UPX-1",
        broker: "upstox",
        label: "Upstox main",
        status: "connected",
        connected_at: null,
        error_message: null,
        is_primary: true,
        source: "native",
        expires_at: 9_999,
        needs_relogin: false,
        login_retryable: false,
        read_only: false,
      },
      {
        account_id: "DHAN-1",
        broker: "dhan",
        label: "DHAN-1",
        status: "token_expired",
        connected_at: null,
        error_message: "login-failed",
        is_primary: false,
        source: "native",
        expires_at: null,
        needs_relogin: true,
        login_retryable: false,
        read_only: false,
      },
      {
        account_id: "IND-1",
        broker: "indmoney",
        label: "IND-1",
        status: "disconnected",
        connected_at: null,
        error_message: "Broker login is temporarily unavailable; retry later.",
        is_primary: false,
        source: "native",
        expires_at: null,
        needs_relogin: false,
        login_retryable: true,
        read_only: false,
      },
    ]);
  });

  it("keeps native accounts visible when the gateway account route fails", async () => {
    mockListAccounts.mockRejectedValue(new Error("Gateway down"));
    mockListNativeAccounts.mockResolvedValue([
      { adapter_id: "indmoney", account_id: "IND-1", has_session: true },
    ]);

    const { result } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(mockSetAccounts).toHaveBeenCalledWith([
      {
        account_id: "IND-1",
        broker: "indmoney",
        label: "IND-1",
        status: "connected",
        connected_at: null,
        error_message: null,
        is_primary: false,
        source: "native",
        expires_at: null,
        needs_relogin: false,
        login_retryable: false,
        read_only: false,
      },
    ]);
  });

  it("preserves the failed source's last-good accounts so the active one is not dropped", async () => {
    // Finding #5: a one-sided gateway failure must not drop a gateway account
    // that is the active write target — that would null activeAccountId and
    // revert targeting to OpenAlgo. Its last-good row is retained until recovery.
    mockStoreAccounts = [
      {
        account_id: "GW1",
        broker: "zerodha",
        label: "Zerodha",
        status: "connected",
        connected_at: null,
        error_message: null,
        is_primary: true,
        source: "gateway",
      },
    ];
    mockListAccounts.mockRejectedValue(new Error("Gateway down"));
    mockListNativeAccounts.mockResolvedValue([]);

    renderHook(() => useBrokerAccounts(), { wrapper: makeWrapper(queryClient) });

    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalled());
    const [synced] = mockSetAccounts.mock.calls[0] as [BrokerAccount[]];
    expect(synced).toEqual([expect.objectContaining({ account_id: "GW1", source: "gateway" })]);
  });

  it("syncs an empty accounts array to the store when the API returns none", async () => {
    // Arrange
    mockListAccounts.mockResolvedValue([]);

    // Act
    renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalledOnce());

    // Assert — store receives empty array, not undefined or null
    expect(mockSetAccounts).toHaveBeenCalledWith([]);
  });

  it("syncs a single-account response correctly", async () => {
    // Arrange
    const account = makeAccount();
    mockListAccounts.mockResolvedValue([account]);

    // Act
    renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalledOnce());

    // Assert
    const [calledWith] = mockSetAccounts.mock.calls[0] as [BrokerAccount[]];
    expect(calledWith).toHaveLength(1);
    expect(calledWith[0].account_id).toBe("acc_001");
  });
});

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

describe("useBrokerAccounts — error state", () => {
  it("sets error when both account routes throw", async () => {
    // Arrange
    mockListAccounts.mockRejectedValue(new Error("Gateway API error: 503"));
    mockListNativeAccounts.mockRejectedValue(new Error("Native API error: 503"));

    // Act
    const { result } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());

    // Assert
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it("reports gateway error message when both account routes throw", async () => {
    // Arrange
    const networkError = new Error("Gateway API error: 503");
    mockListAccounts.mockRejectedValue(networkError);
    mockListNativeAccounts.mockRejectedValue(new Error("Native API error: 503"));

    // Act
    const { result } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());

    // Assert
    expect((result.current.error as Error).message).toBe("Gateway API error: 503");
  });

  it("does not call setAccounts when both account routes fail", async () => {
    // Arrange — the API is down
    mockListAccounts.mockRejectedValue(new Error("network error"));
    mockListNativeAccounts.mockRejectedValue(new Error("native network error"));

    // Act
    renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(mockListAccounts).toHaveBeenCalledOnce());

    // Let effects settle
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    // Assert — store must NOT be polluted with stale/empty data on failure
    expect(mockSetAccounts).not.toHaveBeenCalled();
  });

  it("recovers: isLoading becomes false and error is set (no infinite loading)", async () => {
    // Arrange
    mockListAccounts.mockRejectedValue(new Error("timeout"));
    mockListNativeAccounts.mockRejectedValue(new Error("native timeout"));

    // Act
    const { result } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    // Assert — hook settles in error state, does not hang in loading
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.error).not.toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// Store sync side-effect
// ---------------------------------------------------------------------------

describe("useBrokerAccounts — store sync side-effect", () => {
  it("calls setAccounts only once per successful fetch, not on re-renders", async () => {
    // Arrange
    const accounts = [makeAccount()];
    mockListAccounts.mockResolvedValue(accounts);

    // Act
    const { rerender } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalledOnce());

    // Trigger multiple re-renders without a new fetch
    rerender();
    rerender();
    rerender();

    // Assert — setAccounts must not be called again without new data
    expect(mockSetAccounts).toHaveBeenCalledTimes(1);
  });

  it("calls setAccounts again when refetch returns new data", async () => {
    // Arrange — first call returns 1 account, second returns 2
    const firstBatch = [makeAccount({ account_id: "acc_001" })];
    const secondBatch = [
      makeAccount({ account_id: "acc_001" }),
      makeAccount({ account_id: "acc_002", broker: "zerodha", is_primary: false }),
    ];
    mockListAccounts
      .mockResolvedValueOnce(firstBatch)
      .mockResolvedValueOnce(secondBatch);

    // Act — initial mount
    const { result } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalledTimes(1));
    expect(mockSetAccounts).toHaveBeenLastCalledWith(firstBatch);

    // Act — manually refetch
    await act(async () => {
      await result.current.refetch();
    });

    // Assert — setAccounts called again with the updated list
    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalledTimes(2));
    expect(mockSetAccounts).toHaveBeenLastCalledWith(secondBatch);
  });

  it("preserves account field fidelity when syncing to store", async () => {
    // Arrange — account with all fields populated
    const account: BrokerAccount = {
      account_id: "acc_zerodha_01",
      broker: "zerodha",
      label: "Zerodha - Trading",
      status: "connected",
      connected_at: "2026-03-25T09:15:00Z",
      error_message: null,
      is_primary: false,
    };
    mockListAccounts.mockResolvedValue([account]);

    // Act
    renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => expect(mockSetAccounts).toHaveBeenCalledOnce());

    // Assert — every field passed through without mutation
    const [synced] = mockSetAccounts.mock.calls[0] as [BrokerAccount[]];
    expect(synced[0]).toStrictEqual(account);
  });
});

// ---------------------------------------------------------------------------
// Query key and polling configuration
// ---------------------------------------------------------------------------

describe("useBrokerAccounts — query configuration", () => {
  it("uses one unified query enabling cross-component cache sharing", async () => {
    // Arrange
    mockListAccounts.mockResolvedValue([]);

    // Act — mount two hooks sharing the same QueryClient (same cache)
    const { result: r1 } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });
    const { result: r2 } = renderHook(() => useBrokerAccounts(), {
      wrapper: makeWrapper(queryClient),
    });

    await waitFor(() => {
      expect(r1.current.isLoading).toBe(false);
      expect(r2.current.isLoading).toBe(false);
    });

    // Assert — both hooks share cache: listAccounts called only once (deduplication)
    expect(mockListAccounts).toHaveBeenCalledTimes(1);
    expect(mockListNativeAccounts).toHaveBeenCalledTimes(1);
  });
});
