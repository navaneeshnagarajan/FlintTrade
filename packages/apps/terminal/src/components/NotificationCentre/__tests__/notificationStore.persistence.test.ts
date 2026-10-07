import { beforeEach, describe, expect, it, vi } from "vitest";

describe("notificationStore persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("restores the captured account scope alongside legacy unscoped notifications", async () => {
    const store = await import("../notificationStore");
    const legacy = store.addNotification({ category: "system", title: "Connected", body: "Gateway restored" });
    const scoped = store.addNotification({
      category: "order",
      title: "Order requested",
      body: "Check broker positions and orders.",
      accountScopeKey: "live:native:dhan:SYNTHETIC-A",
    });

    vi.resetModules();
    const reloadedStore = await import("../notificationStore");

    expect(reloadedStore.getSnapshot()).toEqual([
      { ...scoped, accountScopeKey: "live:native:dhan:SYNTHETIC-A" },
      legacy,
    ]);
  });
});
