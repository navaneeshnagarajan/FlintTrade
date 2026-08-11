/**
 * GreeksWidget.test.tsx
 *
 * Tests for the Portfolio Greeks analysis widget.
 * Verifies rendering, empty state, and summary cards.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";
import {
  CONNECTED_NATIVE_READ_CONTEXT,
  PRACTICE_READ_CONTEXT,
  UNCONFIGURED_LIVE_READ_CONTEXT,
} from "@/test-utils/accountReadFixtures";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const apiMocks = vi.hoisted(() => ({
  getPositionbook: vi.fn(),
  getMultiOptionGreeks: vi.fn(),
}));

const accountReadState = vi.hoisted(() => {
  let current: AccountReadContext | undefined;
  const listeners = new Set<() => void>();
  return {
    get current() { return current; },
    set current(value: AccountReadContext | undefined) {
      current = value;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
});

// Mock API calls used by the widget
vi.mock("@/services/api", () => ({
  getPositionbook: apiMocks.getPositionbook,
  getMultiOptionGreeks: apiMocks.getMultiOptionGreeks,
}));

vi.mock("@/hooks/useAccountReadsEnabled", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useAccountReadContext: () => useSyncExternalStore(
      accountReadState.subscribe,
      () => accountReadState.current,
    ),
  };
});

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import GreeksWidget from "../GreeksWidget";

const ACCOUNT_B_READ_CONTEXT = Object.freeze({
  identity: Object.freeze({
    mode: "live",
    scopeKey: "live:native:upstox:B2",
    brokerType: "upstox",
    accountId: "B2",
  }),
  enabled: true,
  host: "",
  apiKey: "",
}) satisfies AccountReadContext;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const accountPosition = (symbol: string, pnl = 0) => ({
  symbol,
  exchange: "NFO",
  quantity: 1,
  ltp: 100,
  pnl,
});

const greekFor = (symbol: string) => ({
  symbol,
  exchange: "NFO",
  instrument_id: symbol,
  delta: 0.5,
  gamma: 0.01,
  theta: -1,
  vega: 2,
  iv: 15,
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GreeksWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    accountReadState.current = CONNECTED_NATIVE_READ_CONTEXT;
    apiMocks.getPositionbook.mockReset().mockResolvedValue([]);
    apiMocks.getMultiOptionGreeks.mockReset().mockResolvedValue([]);
  });

  it("renders without crashing", () => {
    const { container } = render(<GreeksWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Portfolio Greeks heading", () => {
    render(<GreeksWidget />);
    expect(screen.getByText("Portfolio Greeks")).toBeInTheDocument();
  });

  it("shows all four Greek summary cards", () => {
    render(<GreeksWidget />);
    expect(screen.getByText("Net Delta")).toBeInTheDocument();
    expect(screen.getByText("Net Gamma")).toBeInTheDocument();
    expect(screen.getByText("Net Theta")).toBeInTheDocument();
    expect(screen.getByText("Net Vega")).toBeInTheDocument();
  });

  it("shows empty state when no F&O positions", async () => {
    render(<GreeksWidget />);
    // The empty state text (with &amp; entity rendered)
    expect(await screen.findByText(/No F&O positions/)).toBeInTheDocument();
  });

  it("shows footer with refresh interval info", () => {
    render(<GreeksWidget />);
    expect(screen.getByText(/Greeks = per-leg/)).toBeInTheDocument();
  });

  it("requests native Greeks for Dhan CALL display aliases", async () => {
    apiMocks.getPositionbook.mockResolvedValue([{
      symbol: "DIVISLAB 28 JUL 3600 CALL",
      exchange: "NFO",
      quantity: 100,
      ltp: 42.5,
    }]);
    apiMocks.getMultiOptionGreeks.mockResolvedValue([{
      symbol: "DIVISLAB 28 JUL 3600 CALL",
      exchange: "NFO",
      instrument_id: "12345",
      delta: 0.52,
      gamma: 0.001,
      theta: -5,
      vega: 6.4,
      iv: 18.4,
    }]);

    render(<GreeksWidget />);

    await waitFor(() => expect(apiMocks.getMultiOptionGreeks).toHaveBeenCalledWith([{
      symbol: "DIVISLAB 28 JUL 3600 CALL",
      exchange: "NFO",
    }]));
    expect(await screen.findByText("DIVISLAB 28 JUL 3600 CALL")).toBeInTheDocument();
  });

  it("matches reordered native Greeks by contract identity", async () => {
    apiMocks.getPositionbook.mockResolvedValue([
      { symbol: "NIFTY24600CE", exchange: "NFO", quantity: 1 },
      { symbol: "NIFTY24700PE", exchange: "NFO", quantity: 1 },
    ]);
    apiMocks.getMultiOptionGreeks.mockResolvedValue([
      {
        symbol: "NIFTY24700PE", exchange: "NFO", instrument_id: "NSE_FO|PE",
        delta: -0.45, gamma: 0.003, theta: -7.1, vega: 5.4, iv: 14.2,
      },
      {
        symbol: "NIFTY24600CE", exchange: "NFO", instrument_id: "NSE_FO|CE",
        delta: 0.55, gamma: 0.002, theta: -8.1, vega: 6.4, iv: 13.2,
      },
    ]);

    render(<GreeksWidget />);

    const callRow = (await screen.findByText("NIFTY24600CE")).closest("tr");
    const putRow = screen.getByText("NIFTY24700PE").closest("tr");
    expect(callRow).not.toBeNull();
    expect(putRow).not.toBeNull();
    expect(within(callRow!).getByText("+0.55")).toBeInTheDocument();
    expect(within(putRow!).getByText("-0.45")).toBeInTheDocument();
  });

  it("surfaces a native option-Greeks read failure", async () => {
    apiMocks.getPositionbook.mockResolvedValue([{
      symbol: "NIFTY30JUL2625000CE",
      exchange: "NFO",
      quantity: 75,
    }]);
    apiMocks.getMultiOptionGreeks.mockRejectedValue(new Error("native Dhan Greek read failed"));

    render(<GreeksWidget />);

    expect(await screen.findByText("Option Greeks error: native Dhan Greek read failed")).toBeInTheDocument();
    for (const label of ["Net Delta", "Net Gamma", "Net Theta", "Net Vega"]) {
      expect(within(screen.getByText(label).parentElement!).getByText("—")).toBeInTheDocument();
    }
  });

  it("does not render blank Greek strings as zero exposure", async () => {
    apiMocks.getPositionbook.mockResolvedValue([{
      symbol: "NIFTY30JUL2625000CE",
      exchange: "NFO",
      quantity: 75,
    }]);
    apiMocks.getMultiOptionGreeks.mockResolvedValue([{
      symbol: "NIFTY30JUL2625000CE",
      exchange: "NFO",
      instrument_id: "NSE_FO|CE",
      delta: " ",
      gamma: "",
      theta: " ",
      vega: "",
      iv: " ",
    }]);

    render(<GreeksWidget />);

    await screen.findByText("NIFTY30JUL2625000CE");
    for (const label of ["Net Delta", "Net Gamma", "Net Theta", "Net Vega"]) {
      expect(within(screen.getByText(label).parentElement!).getByText("—")).toBeInTheDocument();
    }
  });

  it("makes zero position requests when Live account reads are unconfigured", async () => {
    accountReadState.current = UNCONFIGURED_LIVE_READ_CONTEXT;

    render(<GreeksWidget />);
    await act(async () => Promise.resolve());

    expect(apiMocks.getPositionbook).not.toHaveBeenCalled();
  });

  it.each([
    ["native Live", CONNECTED_NATIVE_READ_CONTEXT],
    ["Practice", PRACTICE_READ_CONTEXT],
  ])("pins %s positions to the exact account context and an AbortSignal", async (_label, context) => {
    accountReadState.current = context;

    render(<GreeksWidget />);

    await waitFor(() => expect(apiMocks.getPositionbook).toHaveBeenCalledOnce());
    expect(apiMocks.getPositionbook).toHaveBeenCalledWith(context, expect.any(AbortSignal));
  });

  it("clears account-A Greeks immediately when account B becomes active", async () => {
    const pendingB = deferred<ReturnType<typeof accountPosition>[]>();
    apiMocks.getPositionbook
      .mockResolvedValueOnce([accountPosition("NIFTY24600CE")])
      .mockImplementationOnce(() => pendingB.promise);
    apiMocks.getMultiOptionGreeks.mockResolvedValue([greekFor("NIFTY24600CE")]);
    const { rerender } = render(<GreeksWidget />);
    expect(await screen.findByText("NIFTY24600CE")).toBeInTheDocument();

    act(() => { accountReadState.current = ACCOUNT_B_READ_CONTEXT; });
    rerender(<GreeksWidget />);

    await waitFor(() => expect(screen.queryByText("NIFTY24600CE")).not.toBeInTheDocument());
  });

  it("aborts and ignores a late account-A response after switching to B", async () => {
    const pendingA = deferred<ReturnType<typeof accountPosition>[]>();
    apiMocks.getPositionbook
      .mockImplementationOnce(() => pendingA.promise)
      .mockResolvedValueOnce([accountPosition("BANKNIFTY55000CE")]);
    apiMocks.getMultiOptionGreeks.mockImplementation(async (requests: Array<{ symbol: string }>) => (
      requests.map(({ symbol }) => greekFor(symbol))
    ));
    const { rerender } = render(<GreeksWidget />);
    await waitFor(() => expect(apiMocks.getPositionbook).toHaveBeenCalledTimes(1));
    const accountASignal = apiMocks.getPositionbook.mock.calls[0]?.[1] as AbortSignal | undefined;

    act(() => { accountReadState.current = ACCOUNT_B_READ_CONTEXT; });
    rerender(<GreeksWidget />);
    expect(await screen.findByText("BANKNIFTY55000CE")).toBeInTheDocument();

    await act(async () => {
      pendingA.resolve([accountPosition("NIFTY24600CE")]);
      await pendingA.promise;
    });
    expect(screen.getByText("BANKNIFTY55000CE")).toBeInTheDocument();
    expect(screen.queryByText("NIFTY24600CE")).not.toBeInTheDocument();
    expect(accountASignal?.aborted).toBe(true);
  });
});
