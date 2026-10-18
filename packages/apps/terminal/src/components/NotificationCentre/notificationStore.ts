/**
 * Notification Centre store — persisted to localStorage.
 *
 * Handles four notification categories:
 *   - alert:  Price alerts triggered
 *   - order:  Order fill / rejection events
 *   - system: Connection changes, errors
 *   - ai:     AI signal recommendations
 */

import { z } from "zod";
import { safeParse } from "@/lib/safeParse";

const LS_KEY = "flinttrade:notifications";
const MAX_STORED = 200;

const visibleAccount = z.string().min(1).max(1024)
  .regex(/^[^\u0000-\u001f\u007f-\u009f\p{Bidi_Control}]+$/u);
const originDisclosureSchema = z.discriminatedUnion("kind", [
  z.object({ version: z.literal(1), kind: z.literal("none") }).strict(),
  z.object({ version: z.literal(1), kind: z.literal("captured"), account: visibleAccount }).strict(),
]);
export type NotificationOriginDisclosure = z.infer<typeof originDisclosureSchema>;

function validatedDisclosure(value: unknown): NotificationOriginDisclosure {
  const parsed = originDisclosureSchema.safeParse(value);
  return parsed.success ? parsed.data : { version: 1, kind: "none" };
}

/** Absent metadata is the legacy contract; malformed/new metadata never falls back. */
export function notificationAccountOrigin(notification: Notification): string | null {
  if (Object.hasOwn(notification, "originDisclosure")) {
    const disclosure = validatedDisclosure(notification.originDisclosure);
    return disclosure.kind === "captured" ? disclosure.account : null;
  }
  const legacy = visibleAccount.safeParse(notification.accountScopeKey);
  return legacy.success ? legacy.data : null;
}

// ---------------------------------------------------------------------------
// Zod schema for persistence validation
// ---------------------------------------------------------------------------

// A one-click remediation attached to a notification. `href` navigates to an
// app route; `event` dispatches a window CustomEvent. Both optional + the whole
// action optional, so older persisted notifications still parse.
const notificationActionSchema = z.object({
  label: z.string(),
  href: z.string().optional(),
  event: z.string().optional(),
});

const notificationSchema = z.object({
  id: z.string(),
  category: z.enum(["alert", "order", "system", "ai"]),
  title: z.string(),
  body: z.string(),
  accountScopeKey: z.string().optional(),
  originDisclosure: z.unknown().optional(),
  timestamp: z.string(),
  read: z.boolean(),
  action: notificationActionSchema.optional(),
});

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type NotificationCategory = "alert" | "order" | "system" | "ai";

/** A one-click remediation that turns an alert into an action the operator can take. */
export interface NotificationAction {
  /** Button label, e.g. "Reconnect", "Reset kill switch", "Retry". */
  label: string;
  /** Navigate to this app route on click. */
  href?: string;
  /** Dispatch this window CustomEvent on click (the handler lives elsewhere). */
  event?: string;
}

export interface Notification {
  id: string;
  category: NotificationCategory;
  title: string;
  body: string;
  /** Captured origin scope; never derive a historical notification's account from current selection. */
  accountScopeKey?: string;
  /** Producer-owned presentation, separate from routing; omission preserves legacy notices. */
  originDisclosure?: NotificationOriginDisclosure;
  /** ISO timestamp string. */
  timestamp: string;
  read: boolean;
  /** Optional remediation CTA — the Notification System driving user action. */
  action?: NotificationAction;
}

export type CreateNotificationPayload = Omit<Notification, "id" | "timestamp" | "read">;

// ---------------------------------------------------------------------------
// Persistence helpers
// ---------------------------------------------------------------------------

function load(): Notification[] {
  const raw = localStorage.getItem(LS_KEY);
  const items = safeParse(raw, z.array(notificationSchema)) ?? [];
  // One-time cleanup of debris from the Explore ping bug (fixed): the demo
  // ping flapped the connection status, persisting an identical "Broker
  // gateway connected" entry every poll. Collapse those to the newest one; a
  // genuine reconnect keeps its most recent notification.
  let seenGatewayConnected = false;
  return items.map((item): Notification => {
    const { originDisclosure, ...rest } = item;
    return Object.hasOwn(item, "originDisclosure")
      ? { ...rest, originDisclosure: validatedDisclosure(originDisclosure) }
      : rest;
  }).filter((item) => {
    if (item.title !== "Broker gateway connected") return true;
    if (seenGatewayConnected) return false;
    seenGatewayConnected = true;
    return true;
  });
}

function save(items: Notification[]): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(items.slice(0, MAX_STORED)));
  } catch {
    // localStorage may be unavailable (private mode / quota exceeded)
  }
}

// ---------------------------------------------------------------------------
// In-memory store with subscriber pattern (no Zustand dependency)
// ---------------------------------------------------------------------------

let _notifications: Notification[] = load();
const _subscribers = new Set<() => void>();

function notify() {
  for (const sub of _subscribers) sub();
}

/** Subscribe to store changes. Returns unsubscribe function. */
export function subscribe(cb: () => void): () => void {
  _subscribers.add(cb);
  return () => _subscribers.delete(cb);
}

/** Read current snapshot. */
export function getSnapshot(): Notification[] {
  return _notifications;
}

/** Add a new notification and persist. */
export function addNotification(payload: CreateNotificationPayload): Notification {
  const n: Notification = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    timestamp: new Date().toISOString(),
    read: false,
    ...payload,
    ...(Object.hasOwn(payload, "originDisclosure")
      ? { originDisclosure: validatedDisclosure(payload.originDisclosure) }
      : {}),
  };
  _notifications = [n, ..._notifications].slice(0, MAX_STORED);
  save(_notifications);
  notify();
  return n;
}

/** Mark a single notification as read. */
export function markRead(id: string): void {
  _notifications = _notifications.map((n) =>
    n.id === id ? { ...n, read: true } : n,
  );
  save(_notifications);
  notify();
}

/** Mark all notifications as read. */
export function markAllRead(): void {
  _notifications = _notifications.map((n) => ({ ...n, read: true }));
  save(_notifications);
  notify();
}

/** Remove a single notification. */
export function removeNotification(id: string): void {
  _notifications = _notifications.filter((n) => n.id !== id);
  save(_notifications);
  notify();
}

/** Remove all notifications. */
export function clearAll(): void {
  _notifications = [];
  save(_notifications);
  notify();
}

/** Count of unread notifications. */
export function unreadCount(): number {
  return _notifications.filter((n) => !n.read).length;
}
