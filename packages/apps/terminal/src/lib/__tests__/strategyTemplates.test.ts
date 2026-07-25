/**
 * strategyTemplates.test.ts
 *
 * Guards the single option-strategy catalogue.
 *
 * The headline guard is the direction inversion: three catalogues used to key a
 * template as `straddle` / `strangle`, and two of them meant BUY-both-legs
 * (defined-risk debit) while the third — the panel that places REAL gated
 * basket orders — meant SELL-both-legs (undefined-risk credit). A bare
 * `straddle` id must never reappear, and the long/short pairs must stay exact
 * mirrors of each other.
 */

import { describe, it, expect } from "vitest";

import {
  builderLegsFor,
  isLoadable,
  getStrategyTemplate,
  CUSTOM_TEMPLATE,
  CUSTOM_TEMPLATE_ID,
  LOADABLE_STRATEGY_TEMPLATES,
  STRATEGY_TEMPLATES,
  type StrategyTemplate,
} from "../strategyTemplates";

/** Entries that carry stock or multi-expiry legs — reference-only, by design. */
const REFERENCE_ONLY_IDS = ["covered-call", "protective-put", "collar", "calendar-spread"];

function byId(id: string): StrategyTemplate {
  const tmpl = STRATEGY_TEMPLATES.find((t) => t.id === id);
  if (!tmpl) throw new Error(`missing template: ${id}`);
  return tmpl;
}

describe("strategyTemplates — direction inversion guard", () => {
  it("has no bare straddle or strangle id", () => {
    const ids = STRATEGY_TEMPLATES.map((t) => t.id);
    expect(ids).not.toContain("straddle");
    expect(ids).not.toContain("strangle");
    // Nor the snake_case / display-name spellings the old catalogues used.
    for (const id of ids) {
      expect(id).not.toMatch(/^(straddle|strangle|short_straddle)$/);
    }
  });

  it("names the direction on every straddle/strangle entry", () => {
    const volatilityIds = STRATEGY_TEMPLATES
      .map((t) => t.id)
      .filter((id) => id.includes("straddle") || id.includes("strangle"));
    expect(volatilityIds.sort()).toEqual([
      "long-straddle",
      "long-strangle",
      "short-straddle",
      "short-strangle",
    ]);
    for (const id of volatilityIds) {
      expect(id.startsWith("long-") || id.startsWith("short-")).toBe(true);
    }
  });

  it.each([
    ["long-straddle", "short-straddle"],
    ["long-strangle", "short-strangle"],
  ])("%s and %s are exact mirrors with opposite leg actions", (longId, shortId) => {
    const long = byId(longId);
    const short = byId(shortId);

    expect(long.legs).toHaveLength(short.legs.length);
    long.legs.forEach((leg, i) => {
      const other = short.legs[i];
      // Same contract, opposite side — that is the whole point of the split.
      expect(other.optionType).toBe(leg.optionType);
      expect(other.strikeOffset).toBe(leg.strikeOffset);
      expect(other.lots).toBe(leg.lots);
      expect(other.action).not.toBe(leg.action);
    });

    expect(long.legs.every((l) => l.action === "BUY")).toBe(true);
    expect(short.legs.every((l) => l.action === "SELL")).toBe(true);
  });

  it("labels the undefined-risk short entries honestly", () => {
    for (const id of ["short-straddle", "short-strangle"]) {
      const tmpl = byId(id);
      expect(tmpl.name).toMatch(/^Short /);
      expect(tmpl.maxLoss).toBe("Unlimited");
    }
    for (const id of ["long-straddle", "long-strangle"]) {
      const tmpl = byId(id);
      expect(tmpl.name).toMatch(/^Long /);
      expect(tmpl.maxLoss).toMatch(/premium/i);
    }
  });
});

describe("strategyTemplates — catalogue shape", () => {
  it("holds 14 strategy concepts plus custom", () => {
    expect(STRATEGY_TEMPLATES).toHaveLength(14);
    expect(CUSTOM_TEMPLATE.id).toBe(CUSTOM_TEMPLATE_ID);
    expect(STRATEGY_TEMPLATES.map((t) => t.id)).not.toContain(CUSTOM_TEMPLATE_ID);
  });

  it("uses unique kebab-case ids and unique short names", () => {
    const ids = STRATEGY_TEMPLATES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z]+(-[a-z]+)*$/);

    const shortNames = [...STRATEGY_TEMPLATES, CUSTOM_TEMPLATE].map((t) => t.shortName);
    expect(new Set(shortNames).size).toBe(shortNames.length);
  });

  it("gives every entry the full metadata union", () => {
    for (const tmpl of STRATEGY_TEMPLATES) {
      expect(tmpl.name).toBeTruthy();
      expect(tmpl.shortName).toBeTruthy();
      expect(tmpl.description).toBeTruthy();
      expect(tmpl.maxProfit).toBeTruthy();
      expect(tmpl.maxLoss).toBeTruthy();
      expect(tmpl.breakeven).toBeTruthy();
      expect(["bullish", "bearish", "neutral", "volatile"]).toContain(tmpl.outlook);
      expect(tmpl.legs.length).toBeGreaterThan(0);
    }
  });

  it("resolves ids (including custom) through getStrategyTemplate", () => {
    expect(getStrategyTemplate("iron-condor")?.name).toBe("Iron Condor");
    expect(getStrategyTemplate(CUSTOM_TEMPLATE_ID)).toBe(CUSTOM_TEMPLATE);
    expect(getStrategyTemplate("straddle")).toBeUndefined();
    expect(getStrategyTemplate("nope")).toBeUndefined();
  });
});

describe("strategyTemplates — loadability gate", () => {
  it("marks exactly the stock-leg and multi-expiry entries as reference-only", () => {
    const referenceOnly = STRATEGY_TEMPLATES.filter((t) => !isLoadable(t)).map((t) => t.id);
    expect(referenceOnly.sort()).toEqual([...REFERENCE_ONLY_IDS].sort());
    expect(LOADABLE_STRATEGY_TEMPLATES).toHaveLength(10);
  });

  it("returns null builder legs for every reference-only entry", () => {
    for (const id of REFERENCE_ONLY_IDS) {
      expect(builderLegsFor(byId(id))).toBeNull();
    }
  });

  it("treats custom as not loadable (it has no legs)", () => {
    expect(builderLegsFor(CUSTOM_TEMPLATE)).toBeNull();
    expect(isLoadable(CUSTOM_TEMPLATE)).toBe(false);
  });

  it("emits bridge-valid legs for every loadable entry", () => {
    for (const tmpl of LOADABLE_STRATEGY_TEMPLATES) {
      const legs = builderLegsFor(tmpl);
      expect(legs).not.toBeNull();
      // Mirrors templateBridge.isValidLeg — a leg that fails this is dropped
      // silently by readAndClearPendingTemplate.
      for (const leg of legs!) {
        expect(["BUY", "SELL"]).toContain(leg.action);
        expect(["CE", "PE"]).toContain(leg.optionType);
        expect(Number.isFinite(leg.strikeOffset)).toBe(true);
        expect(leg.lots).toBeGreaterThanOrEqual(1);
      }
      // Every loadable strategy fits the Lab builder's 6-leg cap and the
      // OptionChain LegBuilder's 4-leg cap.
      expect(legs!.length).toBeLessThanOrEqual(4);
    }
  });
});

describe("strategyTemplates — resolved leg-shape conflicts", () => {
  it("normalises the butterfly to 3 legs with a double-lot body", () => {
    const legs = builderLegsFor(byId("butterfly"))!;
    expect(legs).toHaveLength(3);
    expect(legs.map((l) => l.lots)).toEqual([1, 2, 1]);
    expect(legs.map((l) => l.strikeOffset)).toEqual([-1, 0, 1]);
    expect(legs[1].action).toBe("SELL");
    // Net lots must still balance — 1 + 1 bought against 2 sold.
    const bought = legs.filter((l) => l.action === "BUY").reduce((s, l) => s + l.lots, 0);
    const sold = legs.filter((l) => l.action === "SELL").reduce((s, l) => s + l.lots, 0);
    expect(bought).toBe(sold);
  });

  it("orders the iron condor by ascending strike offset with four distinct wings", () => {
    const legs = builderLegsFor(byId("iron-condor"))!;
    expect(legs.map((l) => l.strikeOffset)).toEqual([-2, -1, 1, 2]);
    expect(legs).toContainEqual({ action: "BUY", optionType: "PE", strikeOffset: -2, lots: 1 });
    expect(legs).toContainEqual({ action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1 });
    expect(legs).toContainEqual({ action: "SELL", optionType: "CE", strikeOffset: 1, lots: 1 });
    expect(legs).toContainEqual({ action: "BUY", optionType: "CE", strikeOffset: 2, lots: 1 });
  });
});
