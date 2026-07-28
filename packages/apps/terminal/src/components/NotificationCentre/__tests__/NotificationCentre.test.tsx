import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Minimal mocks
// ---------------------------------------------------------------------------

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement> & { children?: React.ReactNode }) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    onClick,
    disabled,
    className,
    ...rest
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { children?: React.ReactNode }) => (
    <button onClick={onClick} disabled={disabled} className={className} {...rest}>
      {children}
    </button>
  ),
}));

const mockNavigate = vi.fn();
vi.mock("react-router", () => ({ useNavigate: () => mockNavigate }));

import { NotificationBell, NotificationPanel } from "../NotificationCentre";
import * as store from "../notificationStore";

// ---------------------------------------------------------------------------
// localStorage stub
// ---------------------------------------------------------------------------

const localStorageMock = (() => {
  let storage: Record<string, string> = {};
  return {
    getItem: (k: string) => storage[k] ?? null,
    setItem: (k: string, v: string) => { storage[k] = v; },
    removeItem: (k: string) => { delete storage[k]; },
    clear: () => { storage = {}; },
  };
})();

Object.defineProperty(window, "localStorage", { value: localStorageMock });

beforeEach(() => {
  localStorageMock.clear();
  // Reset the in-memory store by clearing all
  store.clearAll();
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// NotificationBell tests
// ---------------------------------------------------------------------------

describe("NotificationBell", () => {
  it("renders bell icon with no badge when no notifications", () => {
    render(<NotificationBell />);

    const btn = screen.getByRole("button", { name: /notifications/i });
    expect(btn).toBeTruthy();
    // No badge
    expect(screen.queryByText("9+")).toBeNull();
  });

  it("shows unread badge when there are unread notifications", () => {
    act(() => {
      store.addNotification({
        category: "system",
        title: "Connected",
        body: "Broker connected successfully",
      });
    });

    render(<NotificationBell />);

    // Badge "1" should be visible
    const btn = screen.getByRole("button", { name: /1 unread/i });
    expect(btn).toBeTruthy();
  });

  it("shows 9+ badge for more than 9 unread notifications", () => {
    act(() => {
      for (let i = 0; i < 12; i++) {
        store.addNotification({
          category: "order",
          title: `Order ${i}`,
          body: "Filled",
        });
      }
    });

    render(<NotificationBell />);

    // Badge should show "9+"
    const badges = screen.getAllByText("9+");
    expect(badges.length).toBeGreaterThan(0);
  });

  it("opens the panel when clicked", () => {
    render(<NotificationBell />);

    const btn = screen.getByRole("button", { name: /notifications/i });
    fireEvent.click(btn);

    expect(screen.getByRole("dialog", { name: /notification centre/i })).toBeTruthy();
  });

  it("closes the panel when backdrop is clicked", () => {
    render(<NotificationBell />);

    fireEvent.click(screen.getByRole("button", { name: /notifications/i }));
    expect(screen.getByRole("dialog")).toBeTruthy();

    // Click backdrop
    const backdrop = document.querySelector(".fixed.inset-0");
    expect(backdrop).toBeTruthy();
    fireEvent.click(backdrop!);

    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// NotificationPanel tests
// ---------------------------------------------------------------------------

describe("NotificationPanel", () => {
  const onClose = vi.fn();

  it("renders empty state when no notifications", () => {
    render(<NotificationPanel onClose={onClose} />);

    expect(screen.getByText("No notifications")).toBeTruthy();
    expect(screen.getByText(/you are all caught up/i)).toBeTruthy();
  });

  it("renders notification rows", () => {
    act(() => {
      store.addNotification({
        category: "alert",
        title: "NIFTY above 24000",
        body: "Price alert triggered at 24050",
      });
    });

    render(<NotificationPanel onClose={onClose} />);

    expect(screen.getByText("NIFTY above 24000")).toBeTruthy();
    expect(screen.getByText("Price alert triggered at 24050")).toBeTruthy();
  });

  it("closes on Escape key", () => {
    render(<NotificationPanel onClose={onClose} />);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("marks all as read when 'All read' button clicked", () => {
    act(() => {
      store.addNotification({ category: "order", title: "Order filled", body: "BUY 10 NIFTY" });
      store.addNotification({ category: "system", title: "Disconnected", body: "WS dropped" });
    });

    render(<NotificationPanel onClose={onClose} />);

    const btn = screen.getByTitle("Mark all as read");
    fireEvent.click(btn);

    expect(store.unreadCount()).toBe(0);
  });

  it("clears all notifications when Trash button clicked", () => {
    act(() => {
      store.addNotification({ category: "ai", title: "Signal", body: "NIFTY buy signal" });
    });

    render(<NotificationPanel onClose={onClose} />);

    const trashBtn = screen.getByTitle("Clear all notifications");
    fireEvent.click(trashBtn);

    expect(store.getSnapshot()).toHaveLength(0);
  });

  it("filters by category tab", () => {
    act(() => {
      store.addNotification({ category: "alert", title: "Price Alert", body: "BTC above 70000" });
      store.addNotification({ category: "order", title: "Order filled", body: "BUY 1 BTCUSD" });
    });

    render(<NotificationPanel onClose={onClose} />);

    // Switch to Alerts tab
    fireEvent.click(screen.getByRole("tab", { name: /alerts/i }));

    expect(screen.getByText("Price Alert")).toBeTruthy();
    expect(screen.queryByText("Order filled")).toBeNull();
  });

  it("marks notification as read on click", () => {
    act(() => {
      store.addNotification({ category: "system", title: "Connected", body: "OK" });
    });

    render(<NotificationPanel onClose={onClose} />);

    expect(store.unreadCount()).toBe(1);

    const row = screen.getByRole("article");
    fireEvent.click(row);

    expect(store.unreadCount()).toBe(0);
  });

  it("dismisses notification on X button click", () => {
    act(() => {
      store.addNotification({ category: "ai", title: "AI Signal", body: "Bullish NIFTY" });
    });

    render(<NotificationPanel onClose={onClose} />);

    expect(store.getSnapshot()).toHaveLength(1);

    // Hover to reveal dismiss button
    const dismissBtn = screen.getByLabelText(/dismiss notification/i);
    fireEvent.click(dismissBtn);

    expect(store.getSnapshot()).toHaveLength(0);
  });

  it("shows per-category unread counts in tabs", () => {
    act(() => {
      store.addNotification({ category: "order", title: "Fill", body: "Executed" });
      store.addNotification({ category: "order", title: "Reject", body: "Rejected" });
    });

    render(<NotificationPanel onClose={onClose} />);

    // "Orders" tab should show count "2"
    const ordersTab = screen.getByRole("tab", { name: /orders/i });
    expect(ordersTab.textContent).toContain("2");
  });

  it("close button calls onClose", () => {
    render(<NotificationPanel onClose={onClose} />);

    fireEvent.click(screen.getByLabelText("Close notification centre"));

    expect(onClose).toHaveBeenCalledOnce();
  });

  it("renders an action CTA that navigates, marks read, and closes the panel", () => {
    const onCloseLocal = vi.fn();
    act(() => {
      store.addNotification({
        category: "system",
        title: "Broker gateway disconnected",
        body: "Live data and order routing are paused.",
        action: { label: "Reconnect", href: "/settings#api" },
      });
    });

    render(<NotificationPanel onClose={onCloseLocal} />);

    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));

    expect(mockNavigate).toHaveBeenCalledWith("/settings#api");
    expect(store.unreadCount()).toBe(0); // marked read
    expect(onCloseLocal).toHaveBeenCalledOnce(); // panel closed so the operator lands on the fix
  });

  it("an action CTA can dispatch a window event instead of navigating", () => {
    act(() => {
      store.addNotification({
        category: "system",
        title: "Kill switch ACTIVATED",
        body: "Halted.",
        action: { label: "Reset kill switch", event: "flinttrade:reset-kill-switch" },
      });
    });

    const listener = vi.fn();
    window.addEventListener("flinttrade:reset-kill-switch", listener);
    render(<NotificationPanel onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Reset kill switch" }));

    expect(listener).toHaveBeenCalledOnce();
    window.removeEventListener("flinttrade:reset-kill-switch", listener);
  });

  it("renders no CTA when a notification has no action", () => {
    act(() => {
      store.addNotification({ category: "alert", title: "Price alert", body: "NIFTY 24000" });
    });

    render(<NotificationPanel onClose={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Reconnect" })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// notificationStore unit tests
// ---------------------------------------------------------------------------

describe("notificationStore", () => {
  it("addNotification creates notification with id and timestamp", () => {
    const n = store.addNotification({
      category: "system",
      title: "Test",
      body: "Body",
    });

    expect(n.id).toBeTruthy();
    expect(n.timestamp).toBeTruthy();
    expect(n.read).toBe(false);
    expect(n.category).toBe("system");
  });

  it("markRead sets read to true", () => {
    const n = store.addNotification({ category: "alert", title: "T", body: "B" });
    store.markRead(n.id);

    const updated = store.getSnapshot().find((x) => x.id === n.id);
    expect(updated?.read).toBe(true);
  });

  it("markAllRead marks all as read", () => {
    store.addNotification({ category: "order", title: "A", body: "1" });
    store.addNotification({ category: "order", title: "B", body: "2" });
    store.markAllRead();

    expect(store.unreadCount()).toBe(0);
  });

  it("removeNotification deletes by id", () => {
    const n = store.addNotification({ category: "ai", title: "Signal", body: "X" });
    store.removeNotification(n.id);

    expect(store.getSnapshot().find((x) => x.id === n.id)).toBeUndefined();
  });

  it("clearAll empties the store", () => {
    store.addNotification({ category: "system", title: "T1", body: "B1" });
    store.addNotification({ category: "system", title: "T2", body: "B2" });
    store.clearAll();

    expect(store.getSnapshot()).toHaveLength(0);
  });

  it("unreadCount returns correct count", () => {
    store.addNotification({ category: "system", title: "A", body: "1" });
    store.addNotification({ category: "system", title: "B", body: "2" });
    expect(store.unreadCount()).toBe(2);

    const n = store.getSnapshot()[0];
    store.markRead(n.id);
    expect(store.unreadCount()).toBe(1);
  });

  it("notifications are ordered newest first", () => {
    store.addNotification({ category: "alert", title: "First", body: "1" });
    store.addNotification({ category: "order", title: "Second", body: "2" });

    const snapshot = store.getSnapshot();
    expect(snapshot[0].title).toBe("Second");
    expect(snapshot[1].title).toBe("First");
  });

  it("subscribe fires callback on state change", () => {
    const cb = vi.fn();
    const unsub = store.subscribe(cb);

    store.addNotification({ category: "ai", title: "X", body: "Y" });

    expect(cb).toHaveBeenCalled();
    unsub();
  });

  it("unsubscribe stops callbacks from firing", () => {
    const cb = vi.fn();
    const unsub = store.subscribe(cb);
    unsub();

    store.addNotification({ category: "ai", title: "Z", body: "W" });

    expect(cb).not.toHaveBeenCalled();
  });
});
