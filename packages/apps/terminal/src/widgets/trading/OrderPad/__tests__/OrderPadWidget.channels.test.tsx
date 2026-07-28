/**
 * OrderPadWidget.channels.test.tsx
 *
 * FDC3 channel behaviour for the OrderPad (Phase 2 migration). The pad's
 * prefill chain is params.symbol ?? channel instrument ?? NIFTY: an
 * unpinned pad joins its params channel (red by default), follows fresh
 * broadcasts, and a pad pinned by an explicit symbol param (a CreateOrder
 * intent) ignores the channels entirely. These tests run against REAL
 * jotai — a Provider with a private store per test — unlike the sibling
 * suite, which mocks useAtomValue to control the tick plane.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { createStore, Provider } from "jotai";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import { broadcastInstrument, DEFAULT_CHANNEL_ID } from "@/services/fdc3/channels";

// ---------------------------------------------------------------------------
// Mocks (jotai deliberately NOT mocked — the channel bus is the real thing)
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn().mockResolvedValue([]),
  placeOrder: vi.fn().mockResolvedValue({ orderId: "TEST001" }),
  getSymbol: vi.fn().mockResolvedValue({ symbol: "NIFTY", exchange: "NSE", lotsize: 1, tick_size: 0.05 }),
}));

vi.mock("@/hooks/useMargin", () => ({
  useMargin: () => ({ data: null, isFetching: false }),
}));

vi.mock("@/hooks/useBrokerCapabilities", () => ({
  useBrokerCapabilities: () => ({ data: null }),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => selector({ mode: "practice" }),
}));

vi.mock("@/lib/market", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/market")>()),
  isMarketHours: () => false,
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import OrderPadWidget from "../OrderPadWidget";
import { searchSymbol } from "@/services/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Store = ReturnType<typeof createStore>;

const RELIANCE = { symbol: "RELIANCE", exchange: "NSE" };
const TCS = { symbol: "TCS", exchange: "NSE" };

function renderPad(store: Store, params?: Record<string, unknown>): void {
  render(
    <Provider store={store}>
      <OrderPadWidget {...makeWidgetPanelProps(params ? { params } : undefined)} />
    </Provider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OrderPadWidget FDC3 channels", () => {
  beforeEach(() => {
    vi.mocked(searchSymbol).mockResolvedValue([]);
  });

  it("follows a fresh broadcast on its default (red) channel", async () => {
    const store = createStore();
    renderPad(store);

    // Prefill falls through to the NIFTY default — nothing on the channel yet.
    expect(screen.getByDisplayValue("NIFTY")).toBeInTheDocument();

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, RELIANCE));

    // Both the search field and the order summary retarget.
    expect(await screen.findByDisplayValue("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });

  it("seeds the prefill from an instrument already on the channel at mount", () => {
    const store = createStore();
    broadcastInstrument(store, DEFAULT_CHANNEL_ID, RELIANCE);
    renderPad(store);

    expect(screen.getByDisplayValue("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });

  it("ignores broadcasts when joined to no channel (channel: 'none')", () => {
    const store = createStore();
    renderPad(store, { channel: "none" });

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, RELIANCE));

    // Still the NIFTY default — the pad is joined to nothing.
    expect(screen.getByDisplayValue("NIFTY")).toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();
  });

  it("follows only the channel it is joined to", async () => {
    const store = createStore();
    renderPad(store, { channel: "fdc3.channel.green" });

    // A red-channel broadcast is someone else's context.
    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, RELIANCE));
    expect(screen.getByDisplayValue("NIFTY")).toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();

    // A green-channel broadcast retargets the pad.
    act(() => broadcastInstrument(store, "fdc3.channel.green", TCS));
    expect(await screen.findByDisplayValue("TCS")).toBeInTheDocument();
  });

  it("a pad pinned by explicit params (CreateOrder intent) ignores every broadcast", () => {
    const store = createStore();
    broadcastInstrument(store, DEFAULT_CHANNEL_ID, RELIANCE);
    renderPad(store, { symbol: "TCS", exchange: "NSE", action: "SELL" });

    // Params win outright — the RELIANCE already on the channel is ignored.
    expect(screen.getByDisplayValue("TCS")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /practice sell/i })).toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();

    // And a later broadcast never retargets a pinned pad.
    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "INFY", exchange: "NSE" }));
    expect(screen.getByDisplayValue("TCS")).toBeInTheDocument();
    expect(screen.queryByText("INFY")).not.toBeInTheDocument();
  });

  it("a local pick from the search dropdown beats the stale channel instrument", async () => {
    vi.mocked(searchSymbol).mockResolvedValue([{ symbol: "INFY", exchange: "NSE" }]);
    const store = createStore();
    broadcastInstrument(store, DEFAULT_CHANNEL_ID, RELIANCE);
    renderPad(store);
    expect(screen.getByDisplayValue("RELIANCE")).toBeInTheDocument();

    // Type a query and pick from the dropdown — a local, deliberate choice.
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "INF" } });
    const suggestion = await screen.findByRole("button", { name: /INFY/ }, { timeout: 3000 });
    fireEvent.click(suggestion);

    // The stale RELIANCE still sitting on the channel does not re-assert.
    expect(screen.getByDisplayValue("INFY")).toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();

    // ...but a FRESH broadcast still retargets the pad.
    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, TCS));
    expect(await screen.findByDisplayValue("TCS")).toBeInTheDocument();
  });
});
