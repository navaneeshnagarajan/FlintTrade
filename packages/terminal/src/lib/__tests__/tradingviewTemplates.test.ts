/**
 * tradingviewTemplates.test.ts
 *
 * Unit tests for the TradingView alert template library.
 * Covers:
 *  - Template count and required fields
 *  - JSON validity of each webhookMessage
 *  - Placeholder presence
 *  - Category filtering utility
 *  - getTemplateById lookup
 */

import { describe, it, expect } from "vitest";
import {
  TV_ALERT_TEMPLATES,
  TV_TEMPLATE_CATEGORIES,
  filterTemplatesByCategory,
  getTemplateById,
  type TVAlertTemplate,
} from "../tradingviewTemplates";

// ---------------------------------------------------------------------------
// Catalogue shape
// ---------------------------------------------------------------------------

describe("TV_ALERT_TEMPLATES catalogue", () => {
  it("exports exactly 10 templates", () => {
    expect(TV_ALERT_TEMPLATES).toHaveLength(10);
  });

  it("every template has a non-empty id, name, description, category and webhookMessage", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      expect(t.id.length, `id missing on template ${t.name}`).toBeGreaterThan(0);
      expect(t.name.length, `name missing on ${t.id}`).toBeGreaterThan(0);
      expect(t.description.length, `description missing on ${t.id}`).toBeGreaterThan(0);
      expect(t.category.length, `category missing on ${t.id}`).toBeGreaterThan(0);
      expect(t.webhookMessage.length, `webhookMessage missing on ${t.id}`).toBeGreaterThan(0);
    }
  });

  it("all ids are unique", () => {
    const ids = TV_ALERT_TEMPLATES.map((t) => t.id);
    const unique = new Set(ids);
    expect(unique.size).toBe(ids.length);
  });

  it("every template's category is one of the allowed values", () => {
    const allowed: TVAlertTemplate["category"][] = [
      "trend",
      "momentum",
      "volatility",
      "options",
      "custom",
    ];
    for (const t of TV_ALERT_TEMPLATES) {
      expect(allowed).toContain(t.category);
    }
  });
});

// ---------------------------------------------------------------------------
// webhookMessage validity
// ---------------------------------------------------------------------------

describe("webhookMessage JSON validity", () => {
  it("every webhookMessage is valid JSON", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      // TradingView placeholders like {{ticker}} appear inside JSON string values
      // as "{{ticker}}". We replace the entire quoted placeholder string with a
      // plain quoted string so JSON.parse succeeds.
      const sanitised = t.webhookMessage.replace(/"?\{\{[^}]+\}\}"?/g, '"__TV__"');
      expect(
        () => JSON.parse(sanitised),
        `Invalid JSON in template "${t.id}"`
      ).not.toThrow();
    }
  });

  it("every webhookMessage contains an 'action' key", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      expect(t.webhookMessage, `action missing in "${t.id}"`).toContain(
        '"action"'
      );
    }
  });

  it("every webhookMessage contains a 'symbol' key", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      expect(t.webhookMessage, `symbol missing in "${t.id}"`).toContain(
        '"symbol"'
      );
    }
  });

  it("every webhookMessage contains a 'strategy' key", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      expect(t.webhookMessage, `strategy missing in "${t.id}"`).toContain(
        '"strategy"'
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Placeholders
// ---------------------------------------------------------------------------

describe("placeholders array", () => {
  it("every template has a non-empty placeholders array", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      expect(
        t.placeholders.length,
        `placeholders empty on "${t.id}"`
      ).toBeGreaterThan(0);
    }
  });

  it("all declared placeholders are actually present in the webhookMessage", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      for (const ph of t.placeholders) {
        expect(
          t.webhookMessage,
          `Placeholder ${ph} declared but missing in "${t.id}"`
        ).toContain(ph);
      }
    }
  });

  it("{{ticker}} appears in every template's placeholders", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      expect(t.placeholders).toContain("{{ticker}}");
    }
  });

  it("{{exchange}} appears in most templates (straddle hardcodes NFO — excluded)", () => {
    const excluded = new Set(["straddle-atm-entry"]);
    for (const t of TV_ALERT_TEMPLATES) {
      if (!excluded.has(t.id)) {
        expect(t.placeholders).toContain("{{exchange}}");
      }
    }
  });
});

// ---------------------------------------------------------------------------
// filterTemplatesByCategory
// ---------------------------------------------------------------------------

describe("filterTemplatesByCategory", () => {
  it("returns all templates when called with no argument", () => {
    const result = filterTemplatesByCategory();
    expect(result).toHaveLength(TV_ALERT_TEMPLATES.length);
  });

  it("returns all templates when called with undefined", () => {
    const result = filterTemplatesByCategory(undefined);
    expect(result).toHaveLength(TV_ALERT_TEMPLATES.length);
  });

  it("returns only trend templates", () => {
    const result = filterTemplatesByCategory("trend");
    expect(result.length).toBeGreaterThan(0);
    result.forEach((t) => expect(t.category).toBe("trend"));
  });

  it("returns only momentum templates", () => {
    const result = filterTemplatesByCategory("momentum");
    expect(result.length).toBeGreaterThan(0);
    result.forEach((t) => expect(t.category).toBe("momentum"));
  });

  it("returns only options templates", () => {
    const result = filterTemplatesByCategory("options");
    expect(result.length).toBeGreaterThan(0);
    result.forEach((t) => expect(t.category).toBe("options"));
  });

  it("filtered subsets together cover all templates", () => {
    const all = TV_TEMPLATE_CATEGORIES.flatMap((cat) =>
      filterTemplatesByCategory(cat)
    );
    expect(all).toHaveLength(TV_ALERT_TEMPLATES.length);
  });
});

// ---------------------------------------------------------------------------
// getTemplateById
// ---------------------------------------------------------------------------

describe("getTemplateById", () => {
  it("returns the correct template for a known id", () => {
    const t = getTemplateById("supertrend-buy-sell");
    expect(t).toBeDefined();
    expect(t?.name).toBe("SuperTrend BUY / SELL");
  });

  it("returns undefined for an unknown id", () => {
    expect(getTemplateById("does-not-exist")).toBeUndefined();
  });

  it("each template can be looked up by its own id", () => {
    for (const t of TV_ALERT_TEMPLATES) {
      const found = getTemplateById(t.id);
      expect(found).toBe(t);
    }
  });
});

// ---------------------------------------------------------------------------
// TV_TEMPLATE_CATEGORIES
// ---------------------------------------------------------------------------

describe("TV_TEMPLATE_CATEGORIES", () => {
  it("contains no duplicate entries", () => {
    const unique = new Set(TV_TEMPLATE_CATEGORIES);
    expect(unique.size).toBe(TV_TEMPLATE_CATEGORIES.length);
  });

  it("includes all five expected categories", () => {
    const expected: TVAlertTemplate["category"][] = [
      "trend",
      "momentum",
      "volatility",
      "options",
      "custom",
    ];
    for (const cat of expected) {
      expect(TV_TEMPLATE_CATEGORIES).toContain(cat);
    }
  });
});

// ---------------------------------------------------------------------------
// Specific template content spot-checks
// ---------------------------------------------------------------------------

describe("SuperTrend template", () => {
  const t = TV_ALERT_TEMPLATES.find((x) => x.id === "supertrend-buy-sell")!;

  it("exists", () => expect(t).toBeDefined());
  it("is in the trend category", () => expect(t.category).toBe("trend"));
  it("has a Pine Script snippet", () => expect(t.pineSnippet).toBeTruthy());
  it("Pine snippet references ta.supertrend", () =>
    expect(t.pineSnippet).toContain("ta.supertrend"));
  it("webhookMessage uses MARKET pricetype", () =>
    expect(t.webhookMessage).toContain("MARKET"));
  it("webhookMessage product is MIS", () =>
    expect(t.webhookMessage).toContain("MIS"));
});

describe("Straddle ATM template", () => {
  const t = TV_ALERT_TEMPLATES.find((x) => x.id === "straddle-atm-entry")!;

  it("exists", () => expect(t).toBeDefined());
  it("is in the options category", () => expect(t.category).toBe("options"));
  it("exchange is NFO for options", () => expect(t.webhookMessage).toContain("NFO"));
  it("includes strike ATM", () => expect(t.webhookMessage).toContain("ATM"));
});

describe("Custom JSON template", () => {
  const t = TV_ALERT_TEMPLATES.find((x) => x.id === "custom-json")!;

  it("exists", () => expect(t).toBeDefined());
  it("is in the custom category", () => expect(t.category).toBe("custom"));
  it("has no Pine snippet (scaffold only)", () =>
    expect(t.pineSnippet).toBeUndefined());
  it("contains the most placeholders of all templates", () => {
    const maxLen = Math.max(...TV_ALERT_TEMPLATES.map((x) => x.placeholders.length));
    expect(t.placeholders.length).toBe(maxLen);
  });
});
