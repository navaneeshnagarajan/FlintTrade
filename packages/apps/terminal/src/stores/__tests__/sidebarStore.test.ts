import { describe, expect, it } from "vitest";
import { useSidebarStore } from "../sidebarStore";

describe("sidebarStore", () => {
  it("routes Home to the dashboard route", () => {
    const homeItem = useSidebarStore.getState().items.find((item) => item.id === "home");

    expect(homeItem?.route).toBe("/home");
  });

  it("names every route after the page it opens", () => {
    const labels = Object.fromEntries(
      useSidebarStore
        .getState()
        .items.filter((item) => item.type === "route")
        .map((item) => [item.id, item.label]),
    );
    expect(labels).toMatchObject({
      lab: "Strategy Lab",
      ai: "AI Centre",
      ditto: "Accounts",
      settings: "Settings",
    });
    expect(Object.values(labels)).not.toContain("Ditto");
    expect(Object.values(labels)).not.toContain("AI Hub");
  });

  it("has exactly one AI entry at the canonical chat route", () => {
    const entries = useSidebarStore.getState().items.filter((item) => item.route === "/ai");
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ id: "ai", label: "AI Centre", type: "route" });
  });

  it("groups the navigation under labelled separators", () => {
    const order = useSidebarStore.getState().items.map((item) =>
      item.type === "separator" ? `[${item.label}]` : item.id,
    );
    expect(order.slice(0, 9)).toEqual([
      "home",
      "trade",
      "invest",
      "learn",
      "[Tools]",
      "lab",
      "automate",
      "ai",
      "[Manage]",
    ]);
    expect(order.at(-1)).toBe("settings");
  });

  it("keeps the phone drawer state out of persistence", () => {
    useSidebarStore.getState().setMobileOpen(true);
    expect(useSidebarStore.getState().mobileOpen).toBe(true);
    const persisted = JSON.parse(localStorage.getItem("flinttrade:sidebar") ?? "{}") as {
      state?: Record<string, unknown>;
      version?: number;
    };
    expect(persisted.version).toBe(2);
    expect(persisted.state).not.toHaveProperty("mobileOpen");
    useSidebarStore.getState().setMobileOpen(false);
  });

  it("restarts a v1 custom order from the new grouped defaults", async () => {
    localStorage.setItem(
      "flinttrade:sidebar",
      JSON.stringify({
        version: 1,
        state: {
          mode: "expanded",
          items: [
            { id: "settings", label: "Settings", icon: "Settings", route: "/settings", type: "route" },
            { id: "ditto", label: "Ditto", icon: "Copy", route: "/ditto", type: "route" },
            { id: "home", label: "Home", icon: "Home", route: "/home", type: "route" },
          ],
        },
      }),
    );
    await useSidebarStore.persist.rehydrate();
    const state = useSidebarStore.getState();
    expect(state.mode).toBe("expanded");
    expect(state.items[0]?.id).toBe("home");
    expect(state.items.find((item) => item.id === "ditto")?.label).toBe("Accounts");
  });
});
