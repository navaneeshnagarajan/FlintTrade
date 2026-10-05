import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import useWebSocket from "../useWebSocket";
import { getWsService } from "@/services/websocket";
const infy = { symbol: "INFY", exchange: "NSE" };
const reliance = { symbol: "RELIANCE", exchange: "NSE" };
afterEach(() => vi.unstubAllGlobals());
describe("native widget tick subscriptions", () => {
  it("registers interests and releases them on unmount", () => {
    const { unmount } = renderHook(() => useWebSocket([infy], "quote"));
    expect(getWsService().getSubscriptions("quote")).toContainEqual(infy);
    unmount();
    expect(getWsService().getSubscriptions("quote")).not.toContainEqual(infy);
  });
  it("moves interests when instruments change", () => {
    const { rerender, unmount } = renderHook(({ instrument }) => useWebSocket([instrument]), { initialProps: { instrument: infy } });
    rerender({ instrument: reliance });
    expect(getWsService().getSubscriptions("ltp")).not.toContainEqual(infy);
    expect(getWsService().getSubscriptions("ltp")).toContainEqual(reliance);
    unmount();
  });
  it("stays inactive when disabled", () => {
    renderHook(() => useWebSocket([infy], "ltp", false));
    expect(getWsService().getSubscriptions("ltp")).not.toContainEqual(infy);
  });
  it("batches native polling ticks by animation frame", () => {
    let flush = () => {}; vi.stubGlobal("requestAnimationFrame", (callback: () => void) => { flush = callback; return 1; });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const { result } = renderHook(() => useWebSocket([infy, reliance]));
    act(() => { getWsService().publishTick({ ...infy, ltp: 1 }); getWsService().publishTick({ ...infy, ltp: 2 }); getWsService().publishTick({ ...reliance, ltp: 3 }); });
    expect(result.current.ticks).toEqual({});
    act(() => flush());
    expect(result.current.ticks).toMatchObject({ "NSE:INFY": { ltp: 2 }, "NSE:RELIANCE": { ltp: 3 } });
    expect(result.current.connected).toBe(false);
  });
  it("cancels a pending frame when unmounted", () => {
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 9)); const cancel = vi.fn(); vi.stubGlobal("cancelAnimationFrame", cancel);
    const { unmount } = renderHook(() => useWebSocket([infy]));
    act(() => getWsService().publishTick({ ...infy, ltp: 1 })); unmount();
    expect(cancel).toHaveBeenCalledWith(9);
  });
});
