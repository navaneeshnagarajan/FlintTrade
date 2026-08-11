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
  getBrokerCapabilities: vi.fn(async () => ({
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
  });
});
