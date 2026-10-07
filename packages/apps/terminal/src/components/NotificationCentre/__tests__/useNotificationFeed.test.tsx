/**
 * useNotificationFeed.test — verifies the central feed turns real app events
 * into Notification Centre entries and relays the global event bus.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, act, cleanup } from "@testing-library/react";
import { useNotificationFeed, emitNotification } from "../useNotificationFeed";
import * as store from "../notificationStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

describe("useNotificationFeed", () => {
  beforeEach(() => {
    store.clearAll();
    act(() => {
      useConnectionStore.setState({ status: "disconnected" });
      useModeStore.setState({ mode: "explore" });
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("does not notify on initial mount", () => {
    renderHook(() => useNotificationFeed());
    expect(store.getSnapshot()).toHaveLength(0);
  });

  it("notifies when the broker gateway connects (real mode)", () => {
    act(() => useModeStore.setState({ mode: "live" }));
    renderHook(() => useNotificationFeed());
    act(() => useConnectionStore.setState({ status: "connected" }));
    const snap = store.getSnapshot();
    expect(snap.some((n) => /connected/i.test(n.title) && n.category === "system")).toBe(true);
  });

  it.each(["practice", "live"] as const)(
    "does not promote gateway connectivity into market-data or broker readiness in %s mode",
    (mode) => {
      act(() => useModeStore.setState({ mode }));
      renderHook(() => useNotificationFeed());
      act(() => useConnectionStore.setState({ status: "connected", wsConnected: false }));

      const notice = store.getSnapshot().find((n) => n.title === "Broker gateway connected");
      expect(notice).toMatchObject({
        category: "system",
        body: "Gateway connection restored. Check market-data and broker readiness before trading.",
      });
      expect(useConnectionStore.getState().wsConnected).toBe(false);
      expect(notice?.body).not.toMatch(/(?:market data|order routing) are available/i);
    },
  );

  it("notifies when the broker gateway disconnects after being connected (real mode)", () => {
    act(() => useModeStore.setState({ mode: "live" }));
    renderHook(() => useNotificationFeed());
    act(() => useConnectionStore.setState({ status: "connected" }));
    act(() => useConnectionStore.setState({ status: "disconnected" }));
    expect(store.getSnapshot().some((n) => /disconnected/i.test(n.title))).toBe(true);
  });

  it.each(["disconnected", "error"] as const)(
    "a gateway %s does not claim existing broker orders stopped executing",
    (status) => {
      act(() => useModeStore.setState({ mode: "live" }));
      renderHook(() => useNotificationFeed());
      act(() => useConnectionStore.setState({ status: "connected" }));
      act(() => useConnectionStore.setState({ status }));

      expect(store.getSnapshot()[0]).toMatchObject({
        category: "system",
        body: "Gateway unavailable. Broker orders may still be active; reconnect and reconcile positions and orders.",
        action: { label: "Reconnect", href: "/settings#brokers" },
      });
      expect(store.getSnapshot()[0].body).not.toMatch(/routing (?:is|are) paused/i);
    },
  );

  it("does NOT notify broker gateway transitions in Explore mode", () => {
    // Explore has no broker; ping there returns a demo mock so status can be
    // set to connected/disconnected without a real broker event.
    renderHook(() => useNotificationFeed());
    act(() => useConnectionStore.setState({ status: "connected" }));
    act(() => useConnectionStore.setState({ status: "disconnected" }));
    expect(store.getSnapshot().some((n) => /gateway (connected|disconnected)/i.test(n.title))).toBe(false);
  });

  it("notifies when switching to live mode", () => {
    renderHook(() => useNotificationFeed());
    act(() => useModeStore.setState({ mode: "live" }));
    expect(store.getSnapshot().some((n) => /live trading/i.test(n.title))).toBe(true);
  });

  it("selecting Live mode warns about real-money capability without claiming an eligible broker or dispatch", () => {
    renderHook(() => useNotificationFeed());
    act(() => useModeStore.setState({ mode: "live" }));

    expect(store.getSnapshot()[0]).toMatchObject({
      category: "system",
      title: "Live trading mode selected",
      body: "Live mode is real-money capable. Broker readiness and safety checks still apply.",
    });
    expect(useConnectionStore.getState().status).toBe("disconnected");
  });

  it("relays a flinttrade:notify event raised via emitNotification", () => {
    renderHook(() => useNotificationFeed());
    act(() =>
      emitNotification({
        category: "order",
        title: "Order rejected",
        body: "Insufficient margin",
      }),
    );
    expect(store.getSnapshot()[0]).toMatchObject({
      category: "order",
      title: "Order rejected",
    });
  });

  it("forwards the remediation action through the event bus", () => {
    // The bus handler must preserve detail.action so emitted notifications keep
    // their CTA (kill-switch reset, order-failure "Back to terminal", etc.).
    renderHook(() => useNotificationFeed());
    act(() =>
      emitNotification({
        category: "system",
        title: "Kill switch ACTIVATED",
        body: "All live order routing is halted.",
        action: { label: "Reset kill switch", href: "/automate" },
      }),
    );
    expect(store.getSnapshot()[0].action).toEqual({
      label: "Reset kill switch",
      href: "/automate",
    });
  });

  it("drops a malformed action (no string label) from the event bus", () => {
    renderHook(() => useNotificationFeed());
    act(() =>
      window.dispatchEvent(
        new CustomEvent("flinttrade:notify", {
          detail: { title: "T", body: "B", action: { href: "/x" } },
        }),
      ),
    );
    expect(store.getSnapshot()[0].action).toBeUndefined();
  });

  it("coerces an invalid event-bus category to 'system'", () => {
    renderHook(() => useNotificationFeed());
    act(() =>
      window.dispatchEvent(
        new CustomEvent("flinttrade:notify", {
          detail: { category: "bogus", title: "X", body: "Y" },
        }),
      ),
    );
    expect(store.getSnapshot()[0].category).toBe("system");
  });

  it("ignores malformed event-bus payloads", () => {
    renderHook(() => useNotificationFeed());
    act(() =>
      window.dispatchEvent(
        new CustomEvent("flinttrade:notify", { detail: { title: "no body" } }),
      ),
    );
    expect(store.getSnapshot()).toHaveLength(0);
  });
});
