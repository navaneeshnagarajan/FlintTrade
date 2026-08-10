import {
  QueryClient,
  QueryClientProvider,
  QueryObserver,
  type QueryKey,
} from "@tanstack/react-query";
import {
  act,
  render,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { resolveDataScope } from "@/hooks/useDataScope";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";

export const PRIMARY_NATIVE_ACCOUNT: BrokerAccount = {
  account_id: "A1",
  broker: "dhan",
  label: "Primary Dhan",
  status: "connected",
  connected_at: null,
  error_message: null,
  is_primary: true,
  source: "native",
};

export const SECONDARY_NATIVE_ACCOUNT: BrokerAccount = {
  account_id: "B2",
  broker: "upstox",
  label: "Secondary Upstox",
  status: "connected",
  connected_at: null,
  error_message: null,
  is_primary: false,
  source: "native",
};

export const PRIMARY_SCOPE = `live:${brokerAccountKey(PRIMARY_NATIVE_ACCOUNT)}`;

export function setAccountRuntime({
  accounts = [PRIMARY_NATIVE_ACCOUNT],
  activeAccountId = null,
  mode = "live",
}: {
  accounts?: BrokerAccount[];
  activeAccountId?: string | null;
  mode?: AppMode;
} = {}): void {
  act(() => {
    useModeStore.setState({ mode });
    useConnectionStore.setState({
      host: "",
      apiKey: "",
      wsUrl: "",
      status: "disconnected",
      wsConnected: false,
      wsFailure: null,
      lastPing: null,
      demo: false,
      openAlgoHydrated: true,
    });
    useBrokerStore.setState({ accounts, activeAccountId });
  });
}

export function setNativeAccountStatus(
  account: BrokerAccount,
  status: BrokerAccount["status"],
): void {
  act(() => {
    useBrokerStore.getState().updateAccount(brokerAccountKey(account), { status });
  });
}

export function currentDataScope(): string {
  const mode = useModeStore.getState().mode;
  const connection = useConnectionStore.getState();
  const broker = useBrokerStore.getState();
  return resolveDataScope({
    mode,
    host: connection.host,
    apiKey: connection.apiKey,
    accounts: broker.accounts,
    activeAccountId: broker.activeAccountId,
  });
}

export function renderAccountSurface(factory: () => ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={client}>{factory()}</QueryClientProvider>,
  );
  return { client, ...view };
}

export function currentQueryResult(
  client: QueryClient,
  queryKey: QueryKey,
  enabled: boolean,
) {
  const observer = new QueryObserver(client, { queryKey, enabled });
  const result = observer.getCurrentResult();
  observer.destroy();
  return result;
}

export async function forceExactRefetch(
  client: QueryClient,
  queryKey: QueryKey,
): Promise<void> {
  await act(async () => {
    await client.refetchQueries({ queryKey, exact: true });
  });
}

export function resetAccountRuntime(): void {
  setAccountRuntime({ accounts: [], activeAccountId: null, mode: "live" });
}
