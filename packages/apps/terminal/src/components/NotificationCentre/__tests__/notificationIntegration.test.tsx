/**
 * Integration test for the Notification System: the full path a widget's alert
 * travels — emitNotification() -> flinttrade:notify event -> useNotificationFeed
 * -> store -> NotificationBell badge + rendered panel row. The existing tests
 * cover each link in isolation; this proves they connect end-to-end.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, act, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router";

import { emitNotification, useNotificationFeed } from "../useNotificationFeed";
import { NotificationBell } from "../NotificationCentre";
import { clearAll } from "../notificationStore";

function Harness() {
  // A child component anywhere in the tree mounts the feed listener, exactly as
  // AppLayout does in production.
  useNotificationFeed();
  return <NotificationBell />;
}

describe("Notification System — emit → feed → store → UI", () => {
  beforeEach(() => {
    localStorage.clear();
    clearAll();
  });

  it("an emitNotification() from anywhere reaches the bell badge and the panel", async () => {
    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    // Initially no unread.
    expect(screen.getByRole("button", { name: /no unread/i })).toBeInTheDocument();

    // A widget (e.g. OrderPad on a rejected order) raises an alert via the bus.
    act(() => {
      emitNotification({
        category: "order",
        title: "Order rejected",
        body: "Insufficient margin",
      });
    });

    // The badge reflects the new unread notification (emit → feed → store → bell).
    const bell = await screen.findByRole("button", { name: /1 unread/i });

    // Opening the panel renders the notification row with its title + body.
    fireEvent.click(bell);
    expect(await screen.findByText("Order rejected")).toBeInTheDocument();
    expect(screen.getByText("Insufficient margin")).toBeInTheDocument();
    expect(screen.getByRole("article")).not.toHaveTextContent("Origin:");
  });

  it("shows each acknowledgement's captured origin when account responses arrive out of order", async () => {
    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    act(() => {
      emitNotification({
        category: "order",
        title: "Order requested for current account",
        body: "Submission acknowledgement is not a fill.",
        accountScopeKey: "live:native:dhan:SYNTHETIC-B",
      });
      emitNotification({
        category: "order",
        title: "Late order acknowledgement",
        body: "Submission acknowledgement is not a fill.",
        accountScopeKey: "live:native:dhan:SYNTHETIC-A",
        skipAccountRefresh: true,
      });
    });

    fireEvent.click(await screen.findByRole("button", { name: /2 unread/i }));

    const lateRow = screen.getByRole("article", { name: /Late order acknowledgement/ });
    expect(within(lateRow).getByText("Origin: live:native:dhan:SYNTHETIC-A")).toBeInTheDocument();
    expect(lateRow).toHaveAccessibleName(/Origin: live:native:dhan:SYNTHETIC-A/);
    expect(lateRow).not.toHaveTextContent("SYNTHETIC-B");
    const currentRow = screen.getByRole("article", { name: /Order requested for current account/ });
    expect(within(currentRow).getByText("Origin: live:native:dhan:SYNTHETIC-B")).toBeInTheDocument();
  });
});
