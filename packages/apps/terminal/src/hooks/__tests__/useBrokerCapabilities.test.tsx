import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  mode: "explore",
  host: "http://openalgo-a.test",
  apiKey: "",
  accounts: [] as Array<{
    account_id: string;
    broker: string;
    source: "gateway" | "native";
    is_primary?: boolean;
  }>,
  activeAccountId: null as string | null,
}));

const mocks = vi.hoisted(() => ({
  getBrokerCapabilities: vi.fn(async (_signal?: AbortSignal, _expectedDataScope?: string) => ({
    broker_name: "test",
    broker_type: "equity" as const,
    supported_exchanges: ["NSE"],
    features: {
      market_protection: false,
      leverage: false,
      bracket_orders: false,
      cover_orders: false,
    },
  })),
}));

vi.mock("@/services/api", () => ({
  getBrokerCapabilities: mocks.getBrokerCapabilities,
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (value: { mode: string }) => unknown) =>
    selector({ mode: state.mode }),
}));

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (value: { host: string; apiKey: string }) => unknown) =>
    selector({ host: state.host, apiKey: state.apiKey }),
}));

vi.mock("@/stores/brokerStore", () => ({
  brokerAccountKey: (account: (typeof state.accounts)[number]) =>
    `${account.source}:${account.broker}:${account.account_id}`,
  findBrokerAccountMatch: (
    accounts: typeof state.accounts,
    selector: string | null,
  ) => accounts.find((account) => (
    `${account.source}:${account.broker}:${account.account_id}` === selector
  )),
  useBrokerStore: (
    selector: (value: {
      accounts: typeof state.accounts;
      activeAccountId: string | null;
    }) => unknown,
  ) => selector({ accounts: state.accounts, activeAccountId: state.activeAccountId }),
}));

import { useBrokerCapabilities } from "../useBrokerCapabilities";
import { connectionScopeFingerprint } from "../useDataScope";

function makeWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useBrokerCapabilities cache authority", () => {
  beforeEach(() => {
    state.mode = "explore";
    state.host = "http://openalgo-a.test";
    state.apiKey = "";
    state.accounts = [];
    state.activeAccountId = null;
    mocks.getBrokerCapabilities.mockClear();
  });

  it("refetches across mode, native broker, and OpenAlgo authority changes", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { rerender } = renderHook(() => useBrokerCapabilities(), {
      wrapper: makeWrapper(queryClient),
    });
    await waitFor(() => expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(1));

    state.mode = "live";
    state.accounts = [{ account_id: "U1", broker: "upstox", source: "native" }];
    state.activeAccountId = "native:upstox:U1";
    rerender();
    await waitFor(() => expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(2));

    state.accounts = [{ account_id: "D1", broker: "dhan", source: "native" }];
    state.activeAccountId = "native:dhan:D1";
    rerender();
    await waitFor(() => expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(3));

    state.apiKey = "configured-openalgo-key";
    rerender();
    await waitFor(() => expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(4));

    state.host = "http://openalgo-b.test";
    state.apiKey = "different-configured-key";
    rerender();
    await waitFor(() => expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(5));
    for (const [signal] of mocks.getBrokerCapabilities.mock.calls) {
      expect(signal).toBeInstanceOf(AbortSignal);
    }
    expect(mocks.getBrokerCapabilities.mock.calls.map(([, scope]) => scope)).toEqual([
      "explore:mock",
      "live:native:upstox",
      "live:native:dhan",
      `live:openalgo:${connectionScopeFingerprint("http://openalgo-a.test", "configured-openalgo-key")}`,
      `live:openalgo:${connectionScopeFingerprint("http://openalgo-b.test", "different-configured-key")}`,
    ]);
  });

  it("keys the native broker even when a gateway row precedes it", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    state.mode = "live";
    state.accounts = [
      { account_id: "GW1", broker: "zerodha", source: "gateway", is_primary: true },
      { account_id: "D1", broker: "dhan", source: "native", is_primary: true },
    ];
    const { rerender } = renderHook(() => useBrokerCapabilities(), {
      wrapper: makeWrapper(queryClient),
    });
    await waitFor(() => expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(1));

    state.accounts = [
      { account_id: "GW1", broker: "zerodha", source: "gateway", is_primary: true },
      { account_id: "U1", broker: "upstox", source: "native", is_primary: true },
    ];
    rerender();

    await waitFor(() => expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(2));
  });

  it("keeps an in-flight broker-wide capability read valid across same-broker account changes", async () => {
    let resolveCapabilities!: (value: {
      broker_name: string;
      broker_type: "equity";
      supported_exchanges: string[];
      features: {
        market_protection: boolean;
        leverage: boolean;
        bracket_orders: boolean;
        cover_orders: boolean;
      };
    }) => void;
    mocks.getBrokerCapabilities.mockImplementationOnce((_signal, expectedScope) => {
      expect(expectedScope).toBe("live:native:upstox");
      return new Promise((resolve) => { resolveCapabilities = resolve; });
    });
    state.mode = "live";
    state.accounts = [{ account_id: "U1", broker: "upstox", source: "native" }];
    state.activeAccountId = "native:upstox:U1";
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result, rerender } = renderHook(() => useBrokerCapabilities(), {
      wrapper: makeWrapper(queryClient),
    });
    await waitFor(() => expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(1));

    state.accounts = [{ account_id: "U2", broker: "upstox", source: "native" }];
    state.activeAccountId = "native:upstox:U2";
    rerender();
    expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(1);

    resolveCapabilities({
      broker_name: "Upstox",
      broker_type: "equity",
      supported_exchanges: ["NSE"],
      features: {
        market_protection: false,
        leverage: false,
        bracket_orders: false,
        cover_orders: false,
      },
    });
    await waitFor(() => expect(result.current.data?.broker_name).toBe("Upstox"));
  });
});
