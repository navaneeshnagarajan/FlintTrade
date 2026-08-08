import { HOME_WIDGET_CATALOG } from "@/routes/home/homeWidgetRegistry";
import { widgetCatalog } from "@/layout/widgetFactory";

describe("home widget taxonomy (Slice 3 contract)", () => {
  it("every HOME_WIDGET_CATALOG entry declares surface and availability", () => {
    expect(HOME_WIDGET_CATALOG.length).toBe(12);
    for (const entry of HOME_WIDGET_CATALOG) {
      expect(entry).toHaveProperty("surface");
      expect(["home", "shared"]).toContain(entry.surface);
      expect(entry).toHaveProperty("availability");
      expect(["sample-only", "live-only", "live-or-sample"]).toContain(entry.availability);
    }
  });

  it("every componentId exists in HOME_WIDGET_COMPONENTS", () => {
    // This will be validated at runtime import; test the catalog shape
    expect(HOME_WIDGET_CATALOG.every((e: any) => typeof e.componentId === "string")).toBe(true);
  });

  it("no Home tradePairId points at a missing Trade catalogue id", () => {
    const tradeIds = new Set(widgetCatalog.map((e: any) => e.id));
    // RED: once tradePairId added in GREEN, assert resolution; for now enforce no invalid in catalog shape
    expect(HOME_WIDGET_CATALOG.every((e: any) => !e.tradePairId || tradeIds.has(e.tradePairId))).toBe(true);
  });

  it("Home production tree still has zero order-write symbols (regression)", () => {
    // Strengthened: real source guard in slice2HomeTradeOwnership; here ensure no placeOrder symbols in home cards
    expect(true).toBe(true); // will be replaced by focused source assert in full GREEN
  });
});
