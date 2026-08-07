/** Real TanStack Query state regressions for PositionsWidget. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

const mockGetPositionbook = vi.hoisted(() => vi.fn());
const brokerState = vi.hoisted(() => ({ connected: false }));

vi.mock("@/services/api", () => ({
  getPositionbook: mockGetPositionbook,
  placeOrder: vi.fn(),
}));
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => brokerState.connected,
}));
vi.mock("@/hooks/useDataScope", () => ({
  useDataScope: () => "test:account",
}));
vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useModeStore } from "@/stores/modeStore";
import PositionsWidget from "../PositionsWidget";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

function renderWidget() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <PositionsWidget {...makeWidgetPanelProps()} />
    </QueryClientProvider>,
  );
  return { client, ...view };
}

describe("PositionsWidget real query states", () => {
  beforeEach(() => {
    brokerState.connected = false;
    mockGetPositionbook.mockReset();
    useModeStore.setState({ mode: "live" });
  });

  afterEach(() => {
    useModeStore.setState({ mode: "live" });
  });

  it("shows the disconnected state instead of loading for a disabled uncached query", () => {
    renderWidget();

    expect(screen.getByText("Connect a broker to load positions")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading positions")).not.toBeInTheDocument();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
  });

  it("shows sample positions instead of loading in Explore for a disabled uncached query", () => {
    useModeStore.setState({ mode: "explore" });
    renderWidget();

    expect(screen.getByText("Sample")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading positions")).not.toBeInTheDocument();
    expect(mockGetPositionbook).not.toHaveBeenCalled();
  });

  it("keeps retained rows visible with frozen status after a real-query refetch error", async () => {
    brokerState.connected = true;
    mockGetPositionbook
      .mockResolvedValueOnce([{
        symbol: "RELIANCE",
        exchange: "NSE",
        product: "MIS",
        quantity: 10,
        ltp: 105,
        average_price: 100,
        pnl: 50,
      }])
      .mockRejectedValueOnce(new Error("broker offline"));
    const { client } = renderWidget();
    expect(await screen.findByText("RELIANCE")).toBeInTheDocument();

    await act(async () => {
      await client.refetchQueries({ queryKey: ["positions"] });
    });

    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(/frozen/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeEnabled();
  });
});
