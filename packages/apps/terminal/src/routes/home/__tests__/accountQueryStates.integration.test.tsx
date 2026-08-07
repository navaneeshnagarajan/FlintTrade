/**
 * Real TanStack Query regressions for the Orders and Positions home cards.
 *
 * Query hooks are deliberately not mocked: these tests exercise the v5
 * disabled-query and retained-data refetch-error states seen in production.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockGetOrderbook = vi.hoisted(() => vi.fn());
const mockGetPositionbook = vi.hoisted(() => vi.fn());
const brokerState = vi.hoisted(() => ({ connected: false }));

vi.mock("@/services/api", () => ({
  getOrderbook: mockGetOrderbook,
  getPositionbook: mockGetPositionbook,
}));
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => brokerState.connected,
}));
vi.mock("@/hooks/useDataScope", () => ({
  useDataScope: () => "test:account",
}));
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: (selector: (state: { totalPnl: number }) => unknown) => selector({ totalPnl: 500 }),
}));

import { useModeStore } from "@/stores/modeStore";
import { OrdersCard } from "../OrdersCard";
import { PositionsCard } from "../PositionsCard";

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
  return { client, ...view };
}

describe("account query card states", () => {
  beforeEach(() => {
    brokerState.connected = false;
    mockGetOrderbook.mockReset();
    mockGetPositionbook.mockReset();
    useModeStore.setState({ mode: "live" });
  });

  afterEach(() => {
    useModeStore.setState({ mode: "live" });
  });

  it("shows the disconnected Orders state instead of loading for a disabled uncached query", () => {
    renderWithQueryClient(<OrdersCard />);

    expect(screen.getByText("Connect a broker to load orders")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading orders")).not.toBeInTheDocument();
    expect(mockGetOrderbook).not.toHaveBeenCalled();
  });

  it("shows the disconnected Positions state instead of loading for a disabled uncached query", () => {
    renderWithQueryClient(<PositionsCard />);

    expect(screen.getByText("Connect a broker to load positions")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading positions")).not.toBeInTheDocument();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
  });

  it("keeps last-known orders visible and exposes an accessible retry after a refetch error", async () => {
    brokerState.connected = true;
    mockGetOrderbook
      .mockResolvedValueOnce([{
        orderId: "ORDER-1",
        symbol: "NIFTY",
        action: "BUY",
        quantity: 50,
        price: 100,
        status: "COMPLETE",
      }])
      .mockRejectedValueOnce(new Error("broker offline"));
    const { client } = renderWithQueryClient(<OrdersCard />);
    expect(await screen.findByText("NIFTY")).toBeInTheDocument();

    await act(async () => {
      await client.refetchQueries({ queryKey: ["orders"] });
    });

    expect(screen.getByText("NIFTY")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/orders unavailable/i);
    expect(alert).toHaveTextContent(/last known/i);
    expect(screen.getByRole("button", { name: /retry orders/i })).toBeEnabled();
    await waitFor(() => expect(mockGetOrderbook).toHaveBeenCalledTimes(2));
  });

  it("keeps last-known positions visible and exposes an accessible retry after a refetch error", async () => {
    brokerState.connected = true;
    mockGetPositionbook
      .mockResolvedValueOnce([{
        symbol: "RELIANCE",
        exchange: "NSE",
        quantity: 10,
        pnl: 500,
        pnlPercent: 5,
      }])
      .mockRejectedValueOnce(new Error("broker offline"));
    const { client } = renderWithQueryClient(<PositionsCard />);
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();

    await act(async () => {
      await client.refetchQueries({ queryKey: ["positions"] });
    });

    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/positions unavailable/i);
    expect(alert).toHaveTextContent(/last known/i);
    expect(screen.getByRole("button", { name: /retry positions/i })).toBeEnabled();
    await waitFor(() => expect(mockGetPositionbook).toHaveBeenCalledTimes(2));
  });
});
