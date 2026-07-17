/**
 * useNotificationFeed — the central wiring that turns real app events into
 * Notification Centre entries. Mounted ONCE in the app shell (AppLayout).
 *
 * Sources:
 *   1. Broker-gateway connection transitions (connected / disconnected / error)
 *   2. Trading-mode transitions (explore / practice / live)
 *   3. A global `flinttrade:notify` CustomEvent bus, so any part of the app —
 *      including non-React code (order helpers, kill switch, error handlers) —
 *      can raise a notification without importing the store. Dispatch via
 *      {@link emitNotification}.
 *
 * Transitions are detected against a ref so the first observed value never
 * fires a notification (no spurious "disconnected" toast on cold start).
 */

import { useEffect, useRef } from "react";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import type { ConnectionStatus } from "@/types/stores";
import {
  addNotification,
  type CreateNotificationPayload,
  type NotificationCategory,
} from "./notificationStore";

const VALID_CATEGORIES: NotificationCategory[] = ["alert", "order", "system", "ai"];

const MODE_NOTIFICATIONS: Record<AppMode, { title: string; body: string }> = {
  explore: {
    title: "Explore mode",
    body: "Showing sample data only — no broker connection or live orders.",
  },
  practice: {
    title: "Practice mode active",
    body: "Orders run against the native sandbox with virtual capital. No real money is at risk.",
  },
  live: {
    title: "Live trading active",
    body: "Orders are now routed to your broker with REAL money. Trade carefully.",
  },
};

/**
 * Dispatch a notification from anywhere (React or not).
 *
 * @example emitNotification({ category: "order", title: "Order rejected", body: msg })
 */
export function emitNotification(payload: CreateNotificationPayload): void {
  window.dispatchEvent(
    new CustomEvent<CreateNotificationPayload>("flinttrade:notify", { detail: payload }),
  );
}

export function useNotificationFeed(): void {
  const status = useConnectionStore((s) => s.status);
  const mode = useModeStore((s) => s.mode);

  const prevStatus = useRef<ConnectionStatus | null>(null);
  const prevMode = useRef<AppMode | null>(null);

  // 1. Connection transitions ------------------------------------------------
  useEffect(() => {
    const prev = prevStatus.current;
    prevStatus.current = status;
    if (prev === null || prev === status) return;
    // Explore mode has no broker gateway, so a status change there is never a
    // real broker connect/disconnect worth notifying — suppress it.
    if (mode === "explore") return;

    if (status === "connected") {
      addNotification({
        category: "system",
        title: "Broker gateway connected",
        body: "Live market data and order routing are available.",
      });
    } else if (status === "disconnected" || status === "error") {
      addNotification({
        category: "system",
        title:
          status === "error"
            ? "Broker gateway error"
            : "Broker gateway disconnected",
        body: "Live data and order routing are paused until the connection is restored.",
        action: { label: "Reconnect", href: "/settings#api" },
      });
    }
  }, [status]);

  // 2. Mode transitions ------------------------------------------------------
  useEffect(() => {
    const prev = prevMode.current;
    prevMode.current = mode;
    if (prev === null || prev === mode) return;

    const meta = MODE_NOTIFICATIONS[mode];
    addNotification({ category: "system", title: meta.title, body: meta.body });
  }, [mode]);

  // 3. Global event bus ------------------------------------------------------
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<Partial<CreateNotificationPayload>>).detail;
      if (!detail || typeof detail.title !== "string" || typeof detail.body !== "string") {
        return;
      }
      const category: NotificationCategory =
        detail.category && VALID_CATEGORIES.includes(detail.category)
          ? detail.category
          : "system";
      // Forward the remediation CTA so emitted notifications keep their action
      // (e.g. the kill-switch "Reset kill switch" and order-failure "Back to
      // terminal" links). Guard against a malformed bus payload by requiring a
      // string label before passing it to the (unvalidated) store.
      const action =
        detail.action && typeof detail.action === "object" && typeof detail.action.label === "string"
          ? detail.action
          : undefined;
      addNotification({
        category,
        title: detail.title,
        body: detail.body,
        ...(action ? { action } : {}),
      });
    };
    window.addEventListener("flinttrade:notify", handler);
    return () => window.removeEventListener("flinttrade:notify", handler);
  }, []);
}
