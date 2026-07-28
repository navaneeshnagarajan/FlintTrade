/**
 * NotificationCentre — slide-in panel from the right side.
 *
 * Features:
 *   - Bell icon trigger with unread count badge (rendered in TopBar)
 *   - Right-side slide-in panel (Framer Motion AnimatePresence)
 *   - Four categories: Alerts, Orders, System, AI
 *   - Per-notification read/dismiss, mark-all-read, clear-all
 *   - Persisted to localStorage via notificationStore
 *   - Category filter tabs
 *   - Accessible: focus-trap, keyboard close (Escape), ARIA live region
 */

import { useState, useEffect, useRef, useCallback, memo } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router";
import { motion, AnimatePresence } from "framer-motion";
import { layerClassNames } from "@flinttrade/design-system";
import {
  Bell,
  X,
  CheckCheck,
  Trash2,
  AlertTriangle,
  ClipboardList,
  Wifi,
  Bot,
  Circle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useNotifications } from "./useNotifications";
import type { Notification, NotificationCategory } from "./notificationStore";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelativeTime(isoTimestamp: string): string {
  const diff = Date.now() - new Date(isoTimestamp).getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

const CATEGORY_META: Record<
  NotificationCategory,
  { label: string; Icon: typeof Bell; iconClass: string }
> = {
  alert: { label: "Alerts", Icon: AlertTriangle, iconClass: "text-amber-400" },
  order: { label: "Orders", Icon: ClipboardList, iconClass: "text-accent" },
  system: { label: "System", Icon: Wifi, iconClass: "text-text-muted" },
  ai: { label: "AI", Icon: Bot, iconClass: "text-profit" },
};

type FilterTab = "all" | NotificationCategory;

// ---------------------------------------------------------------------------
// Single notification row
// ---------------------------------------------------------------------------

interface NotificationRowProps {
  notification: Notification;
  onRead: (id: string) => void;
  onDismiss: (id: string) => void;
  onAction: (notification: Notification) => void;
}

function NotificationRow({ notification, onRead, onDismiss, onAction }: NotificationRowProps) {
  const { Icon, iconClass } = CATEGORY_META[notification.category];

  const handleClick = useCallback(() => {
    if (!notification.read) onRead(notification.id);
  }, [notification.id, notification.read, onRead]);

  const handleDismiss = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onDismiss(notification.id);
    },
    [notification.id, onDismiss],
  );

  const handleAction = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onAction(notification);
    },
    [notification, onAction],
  );

  return (
    <div
      className={`group relative flex items-start gap-3 px-3 py-2.5 cursor-pointer transition-colors hover:bg-surface-hover/60 ${
        notification.read ? "opacity-60" : ""
      }`}
      onClick={handleClick}
      role="article"
      aria-label={`${notification.title}: ${notification.body}${notification.read ? " (read)" : " (unread)"}`}
    >
      {/* Unread dot */}
      {!notification.read && (
        <div
          className="absolute left-1 top-3 w-1.5 h-1.5 rounded-full bg-accent"
          aria-hidden="true"
        />
      )}

      {/* Category icon */}
      <div className={`mt-0.5 shrink-0 ${iconClass}`}>
        <Icon size={14} aria-hidden="true" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <span className="text-xs font-semibold text-text-primary truncate">
            {notification.title}
          </span>
          <span className="text-xxs text-text-muted whitespace-nowrap shrink-0">
            {formatRelativeTime(notification.timestamp)}
          </span>
        </div>
        <p className="text-xs text-text-secondary mt-0.5 line-clamp-2">
          {notification.body}
        </p>
        {notification.action && (
          <Button
            variant="outline"
            size="sm"
            className="mt-1.5 h-6 px-2 text-xxs"
            onClick={handleAction}
          >
            {notification.action.label}
          </Button>
        )}
      </div>

      {/* Dismiss button — shown on hover */}
      <button
        className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 p-0.5 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-all"
        onClick={handleDismiss}
        aria-label={`Dismiss notification: ${notification.title}`}
      >
        <X size={11} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Notification panel
// ---------------------------------------------------------------------------

interface NotificationPanelProps {
  onClose: () => void;
}

function NotificationPanel({ onClose }: NotificationPanelProps) {
  const { notifications, read, readAll, clear, dismiss } = useNotifications();
  const [activeFilter, setActiveFilter] = useState<FilterTab>("all");
  const panelRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // A notification CTA drives a real action: navigate to the remediation route
  // or dispatch its event, mark it read, and close the panel so the operator
  // lands on the fix.
  const handleAction = useCallback(
    (n: Notification) => {
      if (!n.action) return;
      if (n.action.event) {
        window.dispatchEvent(new CustomEvent(n.action.event));
      }
      if (n.action.href) {
        navigate(n.action.href);
      }
      read(n.id);
      onClose();
    },
    [navigate, read, onClose],
  );

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  // Focus trap — focus panel on mount and trap Tab within the panel
  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  const handleFocusTrap = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const panel = panelRef.current;
    if (!panel) return;
    const focusable = Array.from(
      panel.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => !el.hasAttribute("disabled"));
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }, []);

  const filtered = notifications.filter(
    (n) => activeFilter === "all" || n.category === activeFilter,
  );

  const categories: FilterTab[] = ["all", "alert", "order", "system", "ai"];

  const countForTab = useCallback(
    (tab: FilterTab): number => {
      if (tab === "all") return notifications.filter((n) => !n.read).length;
      return notifications.filter((n) => n.category === tab && !n.read).length;
    },
    [notifications],
  );

  const activeTabId = `notif-tab-${activeFilter}`;

  return (
    <div
      ref={panelRef}
      className="flex flex-col h-full bg-surface-card border-l border-border-default"
      role="dialog"
      aria-label="Notification Centre"
      aria-modal="true"
      tabIndex={-1}
      style={{ outline: "none" }}
      onKeyDown={handleFocusTrap}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border-default shrink-0">
        <div className="flex items-center gap-2">
          <Bell size={14} className="text-text-secondary" aria-hidden="true" />
          <span className="text-sm font-semibold text-text-primary">Notifications</span>
          {notifications.filter((n) => !n.read).length > 0 && (
            <span className="text-xxs font-bold px-1.5 py-0.5 rounded-full bg-accent/20 text-accent">
              {notifications.filter((n) => !n.read).length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xxs text-text-muted hover:text-text-primary"
            onClick={readAll}
            disabled={notifications.every((n) => n.read)}
            title="Mark all as read"
          >
            <CheckCheck size={12} className="mr-1" aria-hidden="true" />
            All read
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xxs text-text-muted hover:text-loss"
            onClick={clear}
            disabled={notifications.length === 0}
            title="Clear all notifications"
          >
            <Trash2 size={12} aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-text-muted hover:text-text-primary"
            onClick={onClose}
            aria-label="Close notification centre"
          >
            <X size={14} aria-hidden="true" />
          </Button>
        </div>
      </div>

      {/* Category filter tabs */}
      <div
        className="flex items-center border-b border-border-subtle bg-surface-base shrink-0 overflow-x-auto"
        role="tablist"
        aria-label="Notification categories"
      >
        {categories.map((tab) => {
          const count = countForTab(tab);
          const isActive = tab === activeFilter;
          const label =
            tab === "all" ? "All" : CATEGORY_META[tab as NotificationCategory].label;

          return (
            <button
              key={tab}
              id={`notif-tab-${tab}`}
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveFilter(tab)}
              className={`flex items-center gap-1 px-3 py-2 text-xs font-medium whitespace-nowrap transition-colors border-b-2 ${
                isActive
                  ? "border-accent text-accent"
                  : "border-transparent text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {label}
              {count > 0 && (
                <span
                  className={`text-xxs font-bold px-1 rounded-full ${
                    isActive ? "bg-accent/20 text-accent" : "bg-surface-hover text-text-muted"
                  }`}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Notification list */}
      <div
        className="flex-1 overflow-y-auto divide-y divide-border-subtle"
        role="tabpanel"
        aria-labelledby={activeTabId}
        aria-live="polite"
        aria-label={`${filtered.length} notification${filtered.length !== 1 ? "s" : ""}`}
      >
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-12 px-4 text-center">
            <Circle
              size={32}
              className="text-border-default"
              aria-hidden="true"
            />
            <div>
              <p className="text-sm font-medium text-text-secondary">No notifications</p>
              <p className="text-xs text-text-muted mt-1">
                {activeFilter === "all"
                  ? "You are all caught up."
                  : `No ${CATEGORY_META[activeFilter as NotificationCategory]?.label.toLowerCase()} notifications.`}
              </p>
            </div>
          </div>
        ) : (
          filtered.map((n) => (
            <NotificationRow
              key={n.id}
              notification={n}
              onRead={read}
              onDismiss={dismiss}
              onAction={handleAction}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Bell trigger button (used in TopBar)
// ---------------------------------------------------------------------------

interface NotificationBellProps {
  /** CSS class overrides for the trigger button. */
  className?: string;
}

export function NotificationBell({ className }: NotificationBellProps) {
  const [open, setOpen] = useState(false);
  const { unread } = useNotifications();

  const handleClose = useCallback(() => setOpen(false), []);

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className={`h-7 w-7 p-0 relative ${className ?? ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={
          unread > 0
            ? `Notifications — ${unread} unread`
            : "Notifications — no unread"
        }
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <Bell className="h-3.5 w-3.5" aria-hidden="true" />
        {/* Unread badge */}
        {unread > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-4 h-4 flex items-center justify-center rounded-full bg-accent text-white text-xxs font-bold px-1 leading-none"
            aria-hidden="true"
          >
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </Button>

      {/* Slide-in panel — portal-rendered to escape TopBar stacking context */}
      {createPortal(
        <AnimatePresence>
          {open && (
            <>
              {/* Backdrop */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className={cn(
                  "fixed inset-0 bg-black/20",
                  layerClassNames.overlayBackdrop,
                )}
                onClick={handleClose}
                aria-hidden="true"
              />

              {/* Panel */}
              <motion.div
                initial={{ x: "100%" }}
                animate={{ x: 0 }}
                exit={{ x: "100%" }}
                transition={{ type: "spring", stiffness: 380, damping: 38 }}
                className={cn(
                  "fixed top-0 right-0 h-full w-80 max-w-full shadow-2xl",
                  layerClassNames.floatingPanel,
                )}
              >
                <NotificationPanel onClose={handleClose} />
              </motion.div>
            </>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}

// Export the panel separately for use in other contexts
export { NotificationPanel };

// Default export is the bell trigger
export default memo(NotificationBell);
