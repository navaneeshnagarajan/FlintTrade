import { describe, expect, it, vi } from "vitest";
import { createStore } from "jotai";
import type { Channel, Context, DesktopAgent } from "@finos/fdc3";
import { createWidgetAgent } from "../widgetAgent";
import { instrumentContext } from "../contexts";
import { broadcastInstrument } from "../channels";

const context = instrumentContext({ symbol: "RELIANCE", exchange: "NSE" });
describe("FDC3 2.2 widget agent contract", () => {
  it("distinguishes Channel listeners from joined initial delivery; suppresses origin echo and disposes", async () => {
    const store = createStore();
    const sender = createWidgetAgent(store, { appId: "flinttrade.terminal", instanceId: "watchlist-1" });
    const receiver = createWidgetAgent(store, { appId: "flinttrade.terminal", instanceId: "chart-1" });
    const channel: Channel = (await sender.getUserChannels())[0];
    const viaChannel = vi.fn();
    await channel.broadcast(context);
    const handle = await channel.addContextListener("fdc3.instrument", viaChannel);
    expect(viaChannel).not.toHaveBeenCalled();
    expect(await channel.getCurrentContext()).toEqual(context);
    const seen = vi.fn();
    const listener = await receiver.addContextListener("fdc3.instrument", seen);
    await receiver.joinUserChannel(channel.id);
    expect(seen).toHaveBeenCalledTimes(1);
    await sender.joinUserChannel(channel.id);
    const echo = vi.fn(); await sender.addContextListener("fdc3.instrument", echo); echo.mockClear();
    await sender.broadcast(instrumentContext({ symbol: "TCS", exchange: "NSE" }));
    expect(echo).not.toHaveBeenCalled();
    expect(seen.mock.lastCall?.[1]).toEqual({ source: { appId: "flinttrade.terminal", instanceId: "watchlist-1" } });
    await receiver.leaveCurrentChannel();
    broadcastInstrument(store, "fdc3.channel.red", { symbol: "INFY", exchange: "NSE" });
    expect(seen).toHaveBeenCalledTimes(2);
    listener.unsubscribe(); handle.unsubscribe(); sender.dispose(); receiver.dispose();
  });
  it("deduplicates an identical selection returned by another widget instead of ping-ponging", async () => {
    const store = createStore();
    const a = createWidgetAgent(store, { appId: "flinttrade.terminal", instanceId: "a" });
    const b = createWidgetAgent(store, { appId: "flinttrade.testing", instanceId: "b" });
    await a.joinUserChannel("fdc3.channel.red"); await b.joinUserChannel("fdc3.channel.red");
    const back = vi.fn(); await a.addContextListener("fdc3.instrument", back);
    await b.addContextListener("fdc3.instrument", c => { void b.broadcast(c); });
    await a.broadcast(context);
    expect(back).not.toHaveBeenCalled();
    a.dispose(); b.dispose();
  });
  it("resolves CreateOrder only to an explicit Terminal preparation, never a broker write", async () => {
    const open = vi.fn();
    const agent = createWidgetAgent(createStore(), { appId: "flinttrade.testing", instanceId: "research" }, open);
    const raise: DesktopAgent["raiseIntent"] = agent.raiseIntent;
    await expect(raise("CreateOrder", context)).rejects.toThrow();
    await expect(raise("CreateOrder", context, { appId: "flinttrade.testing" })).rejects.toThrow();
    const result = await raise("CreateOrder", context, { appId: "flinttrade.terminal" });
    expect(result.source.appId).toBe("flinttrade.terminal");
    expect(await result.getResult()).toEqual({ type: "flinttrade.workflow", status: "prepared", widgetId: "orderpad" });
    expect(open).toHaveBeenCalledWith(expect.objectContaining({ widgetId: "orderpad", props: { symbol: "RELIANCE", exchange: "NSE" } }));
    expect(open).toHaveBeenCalledTimes(1);
    await expect(raise("ViewChart", { type: "fdc3.instrument", id: { ticker: "A" } } as Context)).rejects.toThrow();
    agent.dispose();
  });
});
