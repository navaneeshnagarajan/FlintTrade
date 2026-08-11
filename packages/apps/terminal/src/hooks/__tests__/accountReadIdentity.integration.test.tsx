/** Account-read identity regressions using production stores, hooks, and query keys. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Funds, Position } from "@/types/api";
import type { BrokerAccount } from "@/types/broker";

const mockGetFunds = vi.fn<(source?: unknown, signal?: AbortSignal) => Promise<Funds>>();
const mockGetPositionbook = vi.fn<(source?: unknown, signal?: AbortSignal) => Promise<Position[]>>();
const mockListBrokerAccounts = vi.fn<(previous?: BrokerAccount[]) => Promise<BrokerAccount[]>>();

vi.mock("@/services/api", () => ({
  getFunds: (source?: unknown, signal?: AbortSignal) => mockGetFunds(source, signal),
  getPositionbook: (source?: unknown, signal?: AbortSignal) => mockGetPositionbook(source, signal),
}));

vi.mock("@/services/brokerAccountsApi", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/services/brokerAccountsApi")>();
  return {
    ...original,
    listBrokerAccounts: (previous?: BrokerAccount[]) => mockListBrokerAccounts(previous),
  };
});

vi.mock("@/lib/market", () => ({ isMarketHours: () => false }));

import { usePositions } from "@/hooks/usePositions";
import { useTradingStoreSync } from "@/hooks/useTradingStoreSync";
import { queryKeys } from "@/services/queryKeys";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import { useTradingStore } from "@/stores/tradingStore";

const account = (overrides: Partial<BrokerAccount>): BrokerAccount => ({
  account_id: "A1",
  broker: "dhan",
  label: "Primary A",
  status: "connected",
  connected_at: null,
  error_message: null,
  is_primary: true,
  source: "native",
  ...overrides,
});

const A = account({});
const B = account({
  account_id: "B2",
  broker: "upstox",
  label: "Secondary B",
  is_primary: false,
});
const A_SCOPE = `live:${brokerAccountKey(A)}`;

type TransportIdentity = {
  identity?: {
    accountId?: string;
  };
};

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function createHarness() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
        refetchOnWindowFocus: false,
      },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

function setRuntime(accounts: BrokerAccount[], activeAccountId: string | null): void {
  act(() => {
    useModeStore.setState({ mode: "live" });
    useConnectionStore.setState({
      host: "",
      apiKey: "",
      status: "disconnected",
      openAlgoHydrated: true,
    });
    useBrokerStore.setState({ accounts, activeAccountId });
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useTradingStore.getState().resetSessionState();
  mockListBrokerAccounts.mockImplementation(async (previous = []) => previous);
  mockGetFunds.mockResolvedValue({ availableCash: 100_000, usedMargin: 0, totalBalance: 100_000 });
  mockGetPositionbook.mockResolvedValue([]);
});

afterEach(() => {
  useBrokerStore.getState().resetSessionState();
  useTradingStore.getState().resetSessionState();
  useModeStore.setState({ mode: "explore" });
});

describe("account query identity", () => {
  it("keeps the app-root trading sync disabled when primary A is disconnected even if B is connected", async () => {
    setRuntime([{ ...A, status: "disconnected" }, B], null);
    const { wrapper } = createHarness();

    renderHook(() => useTradingStoreSync(), { wrapper });
    await act(async () => Promise.resolve());

    expect(mockGetFunds).not.toHaveBeenCalled();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
    expect(useTradingStore.getState().totalPnl).toBe(0);
    expect(useTradingStore.getState().positionCount).toBe(0);
  });

  it("never lets a mutable A-to-B store switch write B positions into A's cache key", async () => {
    setRuntime([A, B], brokerAccountKey(A));
    const firstRead = deferred();
    let callCount = 0;
    mockGetPositionbook.mockImplementation(async (source) => {
      const thisCall = callCount;
      callCount += 1;
      if (thisCall === 0) await firstRead.promise;
      const capturedAccount = (source as TransportIdentity | undefined)?.identity?.accountId;
      const current = useBrokerStore.getState().activeAccountId;
      const accountId = capturedAccount
        ?? (current === brokerAccountKey(B) ? B.account_id : A.account_id);
      return [{
        symbol: accountId === A.account_id ? "ACCOUNT-A" : "ACCOUNT-B",
        exchange: "NSE",
        product: "MIS",
        quantity: 1,
        averagePrice: 100,
        ltp: 101,
        pnl: accountId === A.account_id ? 1 : 999,
        pnlPercent: 1,
      }];
    });
    const { client, wrapper } = createHarness();

    renderHook(() => usePositions(), { wrapper });
    await waitFor(() => expect(mockGetPositionbook).toHaveBeenCalledTimes(1));

    act(() => {
      useBrokerStore.setState({ activeAccountId: brokerAccountKey(B) });
    });
    await waitFor(() => expect(mockGetPositionbook).toHaveBeenCalledTimes(2));

    await act(async () => {
      firstRead.resolve();
      await firstRead.promise;
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(client.getQueryState(queryKeys.positions.list(A_SCOPE))?.fetchStatus).toBe("idle");
    });
    const aRows = client.getQueryData<Position[]>(queryKeys.positions.list(A_SCOPE));
    expect(aRows?.[0]?.symbol).not.toBe("ACCOUNT-B");
  });
});
