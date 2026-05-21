import { describe, expect, it } from "vitest";
import { useSidebarStore } from "../sidebarStore";

describe("sidebarStore", () => {
  it("routes Home to the dashboard route", () => {
    const homeItem = useSidebarStore.getState().items.find((item) => item.id === "home");

    expect(homeItem?.route).toBe("/home");
  });
});
