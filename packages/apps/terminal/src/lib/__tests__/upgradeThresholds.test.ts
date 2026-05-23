/**
 * upgradeThresholds.test.ts
 *
 * Behavioural tests for evaluateThresholds() and the UPGRADE_THRESHOLDS
 * constant in upgradeThresholds.ts.
 *
 * Key invariants under test:
 *   1. Returns nothing when the current level does not match a threshold's
 *      `from` level — even if all metric conditions are met.
 *   2. Returns a threshold only when ALL conditions in it pass (AND logic).
 *      Partially-met conditions must NOT trigger a suggestion.
 *   3. Metrics at exactly the threshold value (>=) are considered passing.
 *   4. Multiple thresholds can fire simultaneously when their conditions are
 *      all met across different domains.
 */

import { describe, it, expect } from "vitest";
import type { DomainMetrics } from "@/types/skill";
import type { Domain, SkillLevel } from "@/types/skill";
import { evaluateThresholds, UPGRADE_THRESHOLDS } from "../upgradeThresholds";

// ---------------------------------------------------------------------------
// Test-data helpers
// ---------------------------------------------------------------------------

/** Minimal DomainMetrics with every counter at zero. */
function zeroMetrics(): DomainMetrics {
  return {
    trade:    { ordersPlaced: 0, widgetsUsed: 0, daysActive: 0, lastActiveDate: "" },
    invest:   { holdingsViewed: 0, sipsCreated: 0, goalsSet: 0 },
    learn:    { lessonsCompleted: 0, quizzesPassed: 0, articlesRead: 0 },
    lab:      { backtestsRun: 0, strategiesCreated: 0, optimizationsRun: 0 },
    automate: { flowsCreated: 0, alertsSet: 0, strategiesUploaded: 0 },
    ai:       { questionsAsked: 0, strategiesGenerated: 0, signalsActedOn: 0 },
  };
}

/** All domains set to "beginner" — the baseline starting state. */
function beginnerLevels(): Record<Domain, SkillLevel> {
  return {
    trade:    "beginner",
    invest:   "beginner",
    learn:    "beginner",
    lab:      "beginner",
    automate: "beginner",
    ai:       "beginner",
  };
}

// ---------------------------------------------------------------------------
// Empty result cases
// ---------------------------------------------------------------------------

describe("returns no suggestions when conditions are not met", () => {
  it("returns an empty array when every metric is zero", () => {
    // Arrange
    const metrics = zeroMetrics();
    const levels  = beginnerLevels();
    // Act
    const result = evaluateThresholds(metrics, levels);
    // Assert
    expect(result).toHaveLength(0);
  });

  it("returns an empty array when metrics meet conditions but skill level has already advanced past 'from'", () => {
    // Arrange — trade metrics fully satisfy beginner→intermediate, but the
    // current level is already "intermediate" so the threshold no longer applies.
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 20;
    metrics.trade.daysActive   = 7;

    const levels = beginnerLevels();
    levels.trade = "intermediate"; // already advanced

    // Act
    const result = evaluateThresholds(metrics, levels);
    // Assert
    expect(result.some((t) => t.domain === "trade" && t.from === "beginner")).toBe(false);
  });

  it("returns an empty array when current level is 'advanced' and there is no further threshold", () => {
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 9999;
    metrics.trade.widgetsUsed  = 9999;
    metrics.trade.daysActive   = 9999;

    const levels = beginnerLevels();
    levels.trade = "advanced"; // no threshold defines advanced → beyond

    const result = evaluateThresholds(metrics, levels);
    expect(result.some((t) => t.domain === "trade")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AND logic — all conditions must pass
// ---------------------------------------------------------------------------

describe("AND logic: threshold fires only when every condition is met", () => {
  it("does NOT suggest trade beginner→intermediate when only ordersPlaced is met", () => {
    // Arrange — ordersPlaced met, daysActive not met
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 20; // meets condition
    metrics.trade.daysActive   = 3;  // below required 7

    const levels = beginnerLevels();

    // Act
    const result = evaluateThresholds(metrics, levels);

    // Assert
    const tradeUpgrade = result.find(
      (t) => t.domain === "trade" && t.from === "beginner",
    );
    expect(tradeUpgrade).toBeUndefined();
  });

  it("does NOT suggest trade beginner→intermediate when only daysActive is met", () => {
    // Arrange — daysActive met, ordersPlaced not met
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 5;  // below required 20
    metrics.trade.daysActive   = 7;  // meets condition

    const levels = beginnerLevels();

    // Act
    const result = evaluateThresholds(metrics, levels);

    // Assert
    const tradeUpgrade = result.find(
      (t) => t.domain === "trade" && t.from === "beginner",
    );
    expect(tradeUpgrade).toBeUndefined();
  });

  it("DOES suggest trade beginner→intermediate when all conditions are met", () => {
    // Arrange — both conditions satisfied
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 20;
    metrics.trade.daysActive   = 7;

    const levels = beginnerLevels();

    // Act
    const result = evaluateThresholds(metrics, levels);

    // Assert
    const tradeUpgrade = result.find(
      (t) => t.domain === "trade" && t.from === "beginner",
    );
    expect(tradeUpgrade).toBeDefined();
    expect(tradeUpgrade?.to).toBe("intermediate");
  });

  it("does NOT suggest learn beginner→intermediate when only lessonsCompleted is met", () => {
    const metrics = zeroMetrics();
    metrics.learn.lessonsCompleted = 5; // meets condition
    metrics.learn.quizzesPassed    = 1; // below required 3

    const levels = beginnerLevels();

    const result = evaluateThresholds(metrics, levels);
    const learnUpgrade = result.find(
      (t) => t.domain === "learn" && t.from === "beginner",
    );
    expect(learnUpgrade).toBeUndefined();
  });

  it("DOES suggest learn beginner→intermediate when all conditions are met", () => {
    const metrics = zeroMetrics();
    metrics.learn.lessonsCompleted = 5;
    metrics.learn.quizzesPassed    = 3;

    const levels = beginnerLevels();

    const result = evaluateThresholds(metrics, levels);
    const learnUpgrade = result.find(
      (t) => t.domain === "learn" && t.from === "beginner",
    );
    expect(learnUpgrade).toBeDefined();
    expect(learnUpgrade?.to).toBe("intermediate");
  });
});

// ---------------------------------------------------------------------------
// Exact threshold values (>= boundary)
// ---------------------------------------------------------------------------

describe("metrics at exactly the threshold value are treated as passing", () => {
  it("ordersPlaced === 20 (exact threshold) satisfies the condition", () => {
    // Arrange
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 20; // exactly at boundary
    metrics.trade.daysActive   = 7;

    const levels = beginnerLevels();

    // Act
    const result = evaluateThresholds(metrics, levels);

    // Assert
    expect(result.some((t) => t.domain === "trade" && t.from === "beginner")).toBe(true);
  });

  it("ordersPlaced === 19 (one below threshold) does NOT satisfy the condition", () => {
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 19; // one below
    metrics.trade.daysActive   = 7;

    const levels = beginnerLevels();

    const result = evaluateThresholds(metrics, levels);
    expect(result.some((t) => t.domain === "trade" && t.from === "beginner")).toBe(false);
  });

  it("single-condition threshold: holdingsViewed === 10 fires exactly at the boundary", () => {
    const metrics = zeroMetrics();
    metrics.invest.holdingsViewed = 10; // exactly at boundary

    const levels = beginnerLevels();

    const result = evaluateThresholds(metrics, levels);
    expect(result.some((t) => t.domain === "invest" && t.from === "beginner")).toBe(true);
  });

  it("single-condition threshold: holdingsViewed === 9 does not fire", () => {
    const metrics = zeroMetrics();
    metrics.invest.holdingsViewed = 9; // one below

    const levels = beginnerLevels();

    const result = evaluateThresholds(metrics, levels);
    expect(result.some((t) => t.domain === "invest" && t.from === "beginner")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Multi-domain: multiple thresholds can fire at once
// ---------------------------------------------------------------------------

describe("multiple thresholds fire simultaneously across different domains", () => {
  it("returns two suggestions when trade and invest conditions are both met", () => {
    // Arrange
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced    = 20;
    metrics.trade.daysActive      = 7;
    metrics.invest.holdingsViewed = 10;

    const levels = beginnerLevels();

    // Act
    const result = evaluateThresholds(metrics, levels);

    // Assert
    const tradeHit  = result.some((t) => t.domain === "trade"  && t.from === "beginner");
    const investHit = result.some((t) => t.domain === "invest" && t.from === "beginner");
    expect(tradeHit).toBe(true);
    expect(investHit).toBe(true);
    expect(result.length).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// Intermediate → advanced promotion
// ---------------------------------------------------------------------------

describe("evaluates the intermediate to advanced threshold correctly", () => {
  it("does NOT suggest trade intermediate→advanced when widgetsUsed is below threshold", () => {
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 100;
    metrics.trade.widgetsUsed  = 10; // below required 15

    const levels  = beginnerLevels();
    levels.trade  = "intermediate";

    const result = evaluateThresholds(metrics, levels);
    expect(result.some((t) => t.domain === "trade" && t.from === "intermediate")).toBe(false);
  });

  it("DOES suggest trade intermediate→advanced when both conditions exceed thresholds", () => {
    const metrics = zeroMetrics();
    metrics.trade.ordersPlaced = 100;
    metrics.trade.widgetsUsed  = 15; // exactly at boundary

    const levels  = beginnerLevels();
    levels.trade  = "intermediate";

    const result = evaluateThresholds(metrics, levels);
    const hit = result.find((t) => t.domain === "trade" && t.from === "intermediate");
    expect(hit).toBeDefined();
    expect(hit?.to).toBe("advanced");
  });
});

// ---------------------------------------------------------------------------
// UPGRADE_THRESHOLDS constant shape
// ---------------------------------------------------------------------------

describe("UPGRADE_THRESHOLDS constant defines valid threshold objects", () => {
  it("every threshold has domain, from, to, conditions, and message fields", () => {
    for (const t of UPGRADE_THRESHOLDS) {
      expect(t).toHaveProperty("domain");
      expect(t).toHaveProperty("from");
      expect(t).toHaveProperty("to");
      expect(t).toHaveProperty("conditions");
      expect(t).toHaveProperty("message");
      expect(typeof t.message).toBe("string");
      expect(t.message.length).toBeGreaterThan(0);
    }
  });

  it("every threshold conditions object has at least one entry", () => {
    for (const t of UPGRADE_THRESHOLDS) {
      expect(Object.keys(t.conditions).length).toBeGreaterThanOrEqual(1);
    }
  });
});
