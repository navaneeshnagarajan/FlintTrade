import { widgetCatalog, RETIRED_WIDGET_IDS } from "@/layout/widgetFactory";
import { describe, expect, it } from "vitest";

/** Exact CORRECTION-v3 override sets — fail if missing, extra, or totals drift. */
const SHARED_IDS = [
  "positions",
  "orders",
  "holdings",
  "watchlist",
  "news",
  "marketoverview",
] as const;

const LIVE_ONLY_IDS = [
  "actioncenter",
  "tradecopier",
  "smartorder",
  "foreverorders",
  "superorders",
  "conditionaltriggers",
  "reconciliation",
  "indexstrip",
] as const;

const SAMPLE_ONLY_IDS = [
  "pcrtrend",
  "instrumentcompare",
  "gapanalysis",
  "deliverydata",
  "news",
  "currencyconverter",
] as const;

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
    const homeOnTrade = widgetCatalog.filter((e) => e.surface === "home");
    expect(homeOnTrade.length).toBe(0);
  });

  it("widgetCatalog length still 71; category split unchanged", () => {
    const trading = widgetCatalog.filter((e) => e.category === "Trading").length;
    const analysis = widgetCatalog.filter((e) => e.category === "Analysis").length;
    const utility = widgetCatalog.filter((e) => e.category === "Utility").length;
    expect(trading).toBe(18);
    expect(analysis).toBe(31);
    expect(utility).toBe(22);
    expect(widgetCatalog.length).toBe(71);
  });

  it("exact surface:shared set (six cross-surface pairs)", () => {
    const shared = widgetCatalog.filter((e) => e.surface === "shared").map((e) => e.id).sort();
    expect(shared).toEqual([...SHARED_IDS].sort());
    for (const id of SHARED_IDS) {
      const entry = widgetCatalog.find((e) => e.id === id);
      expect(entry, `missing shared id ${id}`).toBeDefined();
      expect(entry!.surface).toBe("shared");
    }
  });

  it("exact availability:live-only set", () => {
    const liveOnly = widgetCatalog.filter((e) => e.availability === "live-only").map((e) => e.id).sort();
    expect(liveOnly).toEqual([...LIVE_ONLY_IDS].sort());
    for (const id of LIVE_ONLY_IDS) {
      const entry = widgetCatalog.find((e) => e.id === id);
      expect(entry, `missing live-only id ${id}`).toBeDefined();
      expect(entry!.availability).toBe("live-only");
    }
  });

  it("exact availability:sample-only set", () => {
    const sampleOnly = widgetCatalog
      .filter((e) => e.availability === "sample-only")
      .map((e) => e.id)
      .sort();
    expect(sampleOnly).toEqual([...SAMPLE_ONLY_IDS].sort());
    for (const id of SAMPLE_ONLY_IDS) {
      const entry = widgetCatalog.find((e) => e.id === id);
      expect(entry, `missing sample-only id ${id}`).toBeDefined();
      expect(entry!.availability).toBe("sample-only");
    }
  });

  it("no extra ids leak into shared/live-only/sample-only classifications", () => {
    const catalogIds = new Set(widgetCatalog.map((e) => e.id));
    for (const id of [...SHARED_IDS, ...LIVE_ONLY_IDS, ...SAMPLE_ONLY_IDS]) {
      expect(catalogIds.has(id)).toBe(true);
    }
    const sharedExtra = widgetCatalog.filter(
      (e) => e.surface === "shared" && !(SHARED_IDS as readonly string[]).includes(e.id),
    );
    const liveExtra = widgetCatalog.filter(
      (e) => e.availability === "live-only" && !(LIVE_ONLY_IDS as readonly string[]).includes(e.id),
    );
    const sampleExtra = widgetCatalog.filter(
      (e) => e.availability === "sample-only" && !(SAMPLE_ONLY_IDS as readonly string[]).includes(e.id),
    );
    expect(sharedExtra).toEqual([]);
    expect(liveExtra).toEqual([]);
    expect(sampleExtra).toEqual([]);
  });

  it("every RETIRED_WIDGET_IDS key still resolvable; none appear in catalogue", () => {
    const retiredKeys = Object.keys(RETIRED_WIDGET_IDS);
    expect(retiredKeys.length).toBeGreaterThan(0);
    expect(retiredKeys.length).toBe(38);
    for (const id of retiredKeys) {
      const inCatalog = widgetCatalog.some((e) => e.id === id);
      expect(inCatalog).toBe(false);
    }
  });
});
