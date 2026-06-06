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

  it("notifies when the broker gateway connects", () => {
    renderHook(() => useNotificationFeed());
    act(() => useConnectionStore.setState({ status: "connected" }));
    const snap = store.getSnapshot();
    expect(snap.length).toBeGreaterThanOrEqual(1);
    expect(snap[0].title).toMatch(/connected/i);
    expect(snap[0].category).toBe("system");
  });

  it("notifies when the broker gateway disconnects after being connected", () => {
    renderHook(() => useNotificationFeed());
    act(() => useConnectionStore.setState({ status: "connected" }));
    act(() => useConnectionStore.setState({ status: "disconnected" }));
    const snap = store.getSnapshot();
    expect(snap[0].title).toMatch(/disconnected/i);
  });

  it("notifies when switching to live mode", () => {
    renderHook(() => useNotificationFeed());
    act(() => useModeStore.setState({ mode: "live" }));
    expect(store.getSnapshot().some((n) => /live trading/i.test(n.title))).toBe(true);
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
