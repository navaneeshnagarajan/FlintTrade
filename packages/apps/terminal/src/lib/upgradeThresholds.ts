import type { Domain, SkillLevel, DomainMetrics } from "@/types/skill";

interface Threshold {
  domain: Domain;
  from: SkillLevel;
  to: SkillLevel;
  /**
   * Keys correspond to metric field names within the domain's metrics object.
   * A threshold is met when ALL conditions are satisfied (logical AND).
   */
  conditions: Partial<Record<string, number>>;
  /**
   * Human-readable message shown in the upgrade suggestion banner.
   * Placeholder tokens like {ordersPlaced} are interpolated at render time.
   */
  message: string;
}

export const UPGRADE_THRESHOLDS: Threshold[] = [
  {
    domain: "trade",
    from: "beginner",
    to: "intermediate",
    conditions: { ordersPlaced: 20, daysActive: 7 },
    message:
      "You've placed {ordersPlaced} trades over {daysActive} days. Ready for more tools?",
  },
  {
    domain: "trade",
    from: "intermediate",
    to: "advanced",
    conditions: { ordersPlaced: 100, widgetsUsed: 15 },
    message:
      "You're using {widgetsUsed} widgets regularly. Unlock advanced trading?",
  },
  {
    domain: "invest",
    from: "beginner",
    to: "intermediate",
    conditions: { holdingsViewed: 10 },
    message:
      "You've been tracking your holdings. Ready for portfolio analytics?",
  },
  {
    domain: "invest",
    from: "intermediate",
    to: "advanced",
    conditions: { goalsSet: 2 },
    message:
      "Your goals are set. Unlock tax optimization and rebalancing?",
  },
  {
    domain: "learn",
    from: "beginner",
    to: "intermediate",
    conditions: { lessonsCompleted: 5, quizzesPassed: 3 },
    message: "Great progress! Ready for strategy deep-dives?",
  },
  {
    domain: "lab",
    from: "beginner",
    to: "intermediate",
    conditions: { backtestsRun: 3 },
    message:
      "You've run {backtestsRun} backtests. Ready for parameter sweeps?",
  },
  {
    domain: "automate",
    from: "beginner",
    to: "intermediate",
    conditions: { alertsSet: 3 },
    message:
      "Your alerts are working. Ready to build automation flows?",
  },
  {
    domain: "ai",
    from: "beginner",
    to: "intermediate",
    conditions: { questionsAsked: 10 },
    message:
      "You're getting the hang of AI. Ready for strategy generation?",
  },
];

/**
 * Evaluates all thresholds against the current metrics and domain skill levels.
 * Returns only thresholds that are newly met (current level matches `from`
 * and all metric conditions are satisfied).
 *
 * @param metrics - Current DomainMetrics from skillStore
 * @param currentLevels - Current per-domain skill levels from skillStore
 * @returns Array of Threshold objects whose conditions are met
 */
export function evaluateThresholds(
  metrics: DomainMetrics,
  currentLevels: Record<Domain, SkillLevel>
): Threshold[] {
  return UPGRADE_THRESHOLDS.filter((t) => {
    if (currentLevels[t.domain] !== t.from) return false;
    const domainMetrics = metrics[t.domain] as Record<string, number>;
    return Object.entries(t.conditions).every(
      ([key, val]) => (domainMetrics[key] ?? 0) >= (val ?? 0)
    );
  });
}
