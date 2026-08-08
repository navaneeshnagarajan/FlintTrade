import { widgetCatalog } from "@/layout/widgetFactory";
import { RETIRED_WIDGET_IDS } from "@/layout/widgetFactory";

describe("widget taxonomy (Slice 3 contract)", () => {
  it("every widgetCatalog entry declares surface and availability", () => {
    expect(widgetCatalog.length).toBe(71);
    for (const entry of widgetCatalog) {
      expect(entry).toHaveProperty("surface");
      expect(["trade", "shared"]).toContain(entry.surface);
      expect(entry).toHaveProperty("availability");
      expect(["sample-only", "live-only", "live-or-sample"]).toContain(entry.availability);
    }
  });

  it("no catalogue id has surface: \"home\"", () => {
    const homeOnTrade = widgetCatalog.filter((e: any) => e.surface === "home");
    expect(homeOnTrade.length).toBe(0);
  });

  it("widgetCatalog length still 71; category split unchanged", () => {
    const trading = widgetCatalog.filter((e: any) => e.category === "Trading").length;
    const analysis = widgetCatalog.filter((e: any) => e.category === "Analysis").length;
    const utility = widgetCatalog.filter((e: any) => e.category === "Utility").length;
    expect(trading).toBe(18);
    expect(analysis).toBe(31);
    expect(utility).toBe(22);
    expect(widgetCatalog.length).toBe(71);
  });

  it("every RETIRED_WIDGET_IDS key still resolvable; none appear in catalogue", () => {
    const retiredKeys = Object.keys(RETIRED_WIDGET_IDS);
    expect(retiredKeys.length).toBeGreaterThan(0);
    for (const id of retiredKeys) {
      const inCatalog = widgetCatalog.some((e: any) => e.id === id);
      expect(inCatalog).toBe(false);
    }
  });
});
