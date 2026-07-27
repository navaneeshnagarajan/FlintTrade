/**
 * fdc3.test.tsx — the in-process FDC3 bus: contexts, channels, intents,
 * and the React bindings.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createStore, Provider } from "jotai";
import type { ReactNode } from "react";

import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import {
  INSTRUMENT_CONTEXT_TYPE,
  instrumentContext,
  instrumentFromContext,
} from "../contexts";
import {
  broadcastInstrument,
  broadcastToChannel,
  channelFromParams,
  channelInstrumentAtoms,
  DEFAULT_CHANNEL_ID,
  getChannelContext,
  isUserChannelId,
  subscribeChannelInstrument,
  USER_CHANNELS,
} from "../channels";
import { raiseIntent } from "../intents";
import { useBroadcastInstrument, useChannelInstrument } from "../hooks";

const NIFTY = { symbol: "NIFTY", exchange: "NSE_INDEX" };

describe("fdc3 contexts", () => {
  it("builds a standard-conformant fdc3.instrument with the venue extension", () => {
    const ctx = instrumentContext(NIFTY);
    expect(ctx.type).toBe(INSTRUMENT_CONTEXT_TYPE);
    expect(ctx.id.ticker).toBe("NIFTY");
    expect(ctx.market).toEqual({ MIC: "XNSE", COUNTRY_ISOCODE: "IN" });
    expect(ctx.exchange).toBe("NSE_INDEX");
  });

  it("round-trips instrument → context → instrument", () => {
    expect(instrumentFromContext(instrumentContext(NIFTY))).toEqual(NIFTY);
    expect(instrumentFromContext(instrumentContext({ symbol: "GOLD", exchange: "MCX" })))
      .toEqual({ symbol: "GOLD", exchange: "MCX" });
  });

  it("falls back to NSE for an external instrument context without the extension", () => {
    expect(
      instrumentFromContext({ type: "fdc3.instrument", id: { ticker: "RELIANCE" } }),
    ).toEqual({ symbol: "RELIANCE", exchange: "NSE" });
  });

  it("rejects non-instrument and unusable contexts", () => {
    expect(instrumentFromContext(null)).toBeNull();
    expect(instrumentFromContext({ type: "fdc3.contact", id: {} })).toBeNull();
    expect(
      instrumentFromContext({ type: "fdc3.instrument", id: { ticker: "  " } }),
    ).toBeNull();
  });
});

describe("fdc3 channels", () => {
  it("defines four colour channels with red as the default", () => {
    expect(USER_CHANNELS).toHaveLength(4);
    expect(DEFAULT_CHANNEL_ID).toBe("fdc3.channel.red");
    expect(isUserChannelId("fdc3.channel.blue")).toBe(true);
    expect(isUserChannelId("none")).toBe(false);
  });

  it("resolves channel membership from panel params", () => {
    expect(channelFromParams(undefined)).toBe(DEFAULT_CHANNEL_ID);
    expect(channelFromParams({})).toBe(DEFAULT_CHANNEL_ID);
    expect(channelFromParams({ channel: "fdc3.channel.green" })).toBe("fdc3.channel.green");
    expect(channelFromParams({ channel: "none" })).toBeNull();
    expect(channelFromParams({ channel: 42 })).toBeNull();
  });

  it("broadcast/subscribe round-trips an instrument on a channel", () => {
    const store = createStore();
    const seen: Array<unknown> = [];
    const unsubscribe = subscribeChannelInstrument(store, "fdc3.channel.blue", (i) => seen.push(i));

    broadcastInstrument(store, "fdc3.channel.blue", NIFTY);
    expect(seen).toEqual([NIFTY]);
    expect(getChannelContext(store, "fdc3.channel.blue")?.id).toEqual({ ticker: "NIFTY" });

    unsubscribe();
    broadcastInstrument(store, "fdc3.channel.blue", { symbol: "GOLD", exchange: "MCX" });
    expect(seen).toHaveLength(1);
  });

  it("keeps channels independent", () => {
    const store = createStore();
    broadcastInstrument(store, "fdc3.channel.green", NIFTY);
    expect(store.get(channelInstrumentAtoms["fdc3.channel.blue"])).toBeNull();
    expect(store.get(channelInstrumentAtoms["fdc3.channel.green"])).toEqual(NIFTY);
  });

  it("the red channel aliases the legacy selectedSymbolAtom", () => {
    const store = createStore();
    broadcastInstrument(store, DEFAULT_CHANNEL_ID, NIFTY);
    expect(store.get(selectedSymbolAtom)).toEqual(NIFTY);
  });

  it("ignores non-instrument broadcasts", () => {
    const store = createStore();
    broadcastToChannel(store, "fdc3.channel.blue", { type: "fdc3.contact", id: {} });
    expect(store.get(channelInstrumentAtoms["fdc3.channel.blue"])).toBeNull();
  });
});

describe("fdc3 intents", () => {
  afterEach(() => vi.restoreAllMocks());

  function captureAddWidget(): Array<Record<string, unknown>> {
    const events: Array<Record<string, unknown>> = [];
    window.addEventListener("flinttrade:addWidget", ((e: Event) => {
      events.push((e as CustomEvent<Record<string, unknown>>).detail);
    }) as EventListener);
    return events;
  }

  it("ViewChart resolves to a chart panel for the instrument", () => {
    const events = captureAddWidget();
    expect(raiseIntent("ViewChart", instrumentContext(NIFTY))).toBe(true);
    expect(events).toEqual([
      { widgetId: "chart", props: { symbol: "NIFTY", exchange: "NSE_INDEX" } },
    ]);
  });

  it("CreateOrder resolves to a prefilled order pad with side and title", () => {
    const events = captureAddWidget();
    expect(raiseIntent("CreateOrder", instrumentContext(NIFTY), { side: "SELL" })).toBe(true);
    expect(events).toEqual([
      {
        widgetId: "orderpad",
        props: { symbol: "NIFTY", exchange: "NSE_INDEX", action: "SELL" },
        title: "Order — NIFTY",
      },
    ]);
  });

  it("returns false (and dispatches nothing) for a context it cannot act on", () => {
    const events = captureAddWidget();
    expect(raiseIntent("ViewChart", { type: "fdc3.contact", id: {} })).toBe(false);
    expect(events).toHaveLength(0);
  });
});

describe("fdc3 hooks", () => {
  function wrapperFor(store: ReturnType<typeof createStore>) {
    return ({ children }: { children: ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
  }

  it("useChannelInstrument follows broadcasts on its channel", () => {
    const store = createStore();
    const { result } = renderHook(() => useChannelInstrument("fdc3.channel.yellow"), {
      wrapper: wrapperFor(store),
    });
    expect(result.current).toBeNull();

    act(() => broadcastInstrument(store, "fdc3.channel.yellow", NIFTY));
    expect(result.current).toEqual(NIFTY);
  });

  it("useChannelInstrument on no channel reads null regardless of broadcasts", () => {
    const store = createStore();
    const { result } = renderHook(() => useChannelInstrument(null), {
      wrapper: wrapperFor(store),
    });
    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, NIFTY));
    expect(result.current).toBeNull();
  });

  it("useBroadcastInstrument writes through the provider's store", () => {
    const store = createStore();
    const { result } = renderHook(() => useBroadcastInstrument("fdc3.channel.green"), {
      wrapper: wrapperFor(store),
    });
    act(() => result.current(NIFTY));
    expect(store.get(channelInstrumentAtoms["fdc3.channel.green"])).toEqual(NIFTY);
  });
});
