/**
 * useNotifications — React hook that subscribes to the notification store.
 * Returns the current notifications list and action functions.
 * Uses useSyncExternalStore for correct concurrent-mode behaviour.
 */

import { useSyncExternalStore, useCallback } from "react";
import {
  subscribe,
  getSnapshot,
  addNotification,
  markRead,
  markAllRead,
  removeNotification,
  clearAll,
  unreadCount,
} from "./notificationStore";
import type { CreateNotificationPayload } from "./notificationStore";

export function useNotifications() {
  const notifications = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const add = useCallback((payload: CreateNotificationPayload) => {
    addNotification(payload);
  }, []);

  const dismiss = useCallback((id: string) => {
    removeNotification(id);
  }, []);

  const read = useCallback((id: string) => {
    markRead(id);
  }, []);

  const readAll = useCallback(() => {
    markAllRead();
  }, []);

  const clear = useCallback(() => {
    clearAll();
  }, []);

  return {
    notifications,
    unread: unreadCount(),
    add,
    dismiss,
    read,
    readAll,
    clear,
  };
}
