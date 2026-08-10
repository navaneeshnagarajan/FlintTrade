import {
  HOME_WIDGET_CATALOG,
  HOME_WIDGET_COMPONENTS,
} from "@/routes/home/homeWidgetRegistry";
import { widgetCatalog } from "@/layout/widgetFactory";
import { readdirSync, readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const EXACT_SHARED_PAIRS: Record<string, string> = {
  PositionsCard: "positions",
  PortfolioCard: "holdings",
  WatchlistCard: "watchlist",
  NewsCard: "news",
  BreadthCard: "marketoverview",
  OrdersCard: "orders",
};

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

function walkProductionTs(dir: string, out: string[] = []): string[] {
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, ent.name);
    if (ent.isDirectory()) {
      if (ent.name === "__tests__" || ent.name === "node_modules") continue;
      walkProductionTs(full, out);
      continue;
    }
    if (!/\.(ts|tsx)$/.test(ent.name)) continue;
    if (/\.(test|spec)\.(ts|tsx)$/.test(ent.name)) continue;
    out.push(full);
  }
  return out;
}

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

  it("exact six-pair shared map with tradePairId", () => {
    const shared = HOME_WIDGET_CATALOG.filter((e) => e.surface === "shared");
    expect(shared.map((e) => e.componentId).sort()).toEqual(Object.keys(EXACT_SHARED_PAIRS).sort());
    for (const entry of shared) {
      expect(entry.tradePairId).toBe(EXACT_SHARED_PAIRS[entry.componentId]);
    }
    for (const entry of HOME_WIDGET_CATALOG.filter((e) => e.surface === "home")) {
      expect(entry.tradePairId).toBeUndefined();
    }
  });

  it("every componentId is an own key of HOME_WIDGET_COMPONENTS with a component value", () => {
    for (const entry of HOME_WIDGET_CATALOG) {
      expect(Object.prototype.hasOwnProperty.call(HOME_WIDGET_COMPONENTS, entry.componentId)).toBe(
        true,
      );
      const comp = HOME_WIDGET_COMPONENTS[entry.componentId];
      expect(comp === null || comp === undefined).toBe(false);
      expect(typeof comp === "function" || typeof comp === "object").toBe(true);
    }
  });

  it("no Home tradePairId points at a missing Trade catalogue id", () => {
    const tradeIds = new Set(widgetCatalog.map((e) => e.id));
    expect(
      HOME_WIDGET_CATALOG.every((e) => !e.tradePairId || tradeIds.has(e.tradePairId)),
    ).toBe(true);
  });

  it("Home production tree still has zero order-write symbols (regression)", () => {
    const homeDir = join(process.cwd(), "src", "routes", "home");
    const offenders: string[] = [];
    // Cover Slice 2 guard vocabulary plus common order-write hooks/calls.
    const ORDER_WRITE =
      /placeOrder|assertNativeWriteTargetReadyOrThrow|cancelOrder|modifyOrder|usePlaceOrder|useCancelOrder|useModifyOrder|gate_order|BrokerRouter\.place/;
    for (const full of walkProductionTs(homeDir)) {
      const text = stripComments(readFileSync(full, "utf8"));
      if (ORDER_WRITE.test(text)) {
        offenders.push(full.replace(/\\/g, "/"));
      }
    }
    expect(offenders).toEqual([]);
  });
});
