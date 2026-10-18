import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook as rtlRenderHook, waitFor, type RenderHookOptions } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  mode: "explore",
  host: "http://retired-a.test",
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

// Setup eagerly imports authority readers: seed their real store instances.
import { useModeStore, type AppMode } from "@/stores/modeStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useAuthStore } from "@/stores/authStore";

function seedRealStores() {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-capability-session" });
  useModeStore.setState({ mode: state.mode as AppMode });
  useBrokerStore.setState({
    accounts: state.accounts.map(account => ({
      ...account, label: "Synthetic capability account", status: "connected",
      connected_at: null, error_message: null, is_primary: account.is_primary ?? false,
    })),
    activeAccountId: state.activeAccountId,
  });
  // The retired host key is deliberately injected as stale legacy state; it
  // must not participate in today's account/broker authority.
  const legacyTransport = { host: state.host, apiKey: state.apiKey };
  useConnectionStore.setState(legacyTransport);
}

// Keep the original scenarios intact, synchronising each existing boundary.
function renderHook<Result, Props>(callback: (props: Props) => Result, options: RenderHookOptions<Props>) {
  act(seedRealStores);
  const hook = rtlRenderHook(callback, options);
  return { ...hook, rerender: (props?: Props) => {
    act(() => { seedRealStores(); hook.rerender(props); });
  } };
}

import { useBrokerCapabilities } from "../useBrokerCapabilities";


function makeWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useBrokerCapabilities cache authority", () => {
  beforeEach(() => {
    state.mode = "explore";
    state.host = "http://retired-a.test";
    state.apiKey = "";
    state.accounts = [];
    state.activeAccountId = null;
    mocks.getBrokerCapabilities.mockClear();
  });

  it("refetches for native brokers while stale transport settings never retarget authority", async () => {
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

    state.apiKey = "stale-key";
    rerender();
    expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(3);

    state.host = "http://retired-b.test";
    state.apiKey = "different-configured-key";
    rerender();
    expect(mocks.getBrokerCapabilities).toHaveBeenCalledTimes(3);
    for (const [signal] of mocks.getBrokerCapabilities.mock.calls) {
      expect(signal).toBeInstanceOf(AbortSignal);
    }
    expect(mocks.getBrokerCapabilities.mock.calls.map(([, scope]) => scope)).toEqual([
      "explore:mock",
      "live:native:upstox",
      "live:native:dhan",
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
