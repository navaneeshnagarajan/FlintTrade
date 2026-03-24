/**
 * Three-level skill scale. Deliberately simple — not a 1-10 scale,
 * not per-widget granularity. The coarser the model, the easier it
 * is for users to understand and for developers to maintain.
 */
export type SkillLevel = "beginner" | "intermediate" | "advanced";

/**
 * The six route domains that have independent skill tracking.
 * Maps 1:1 to the six app routes: /trade, /invest, /learn, /lab,
 * /automate, /ai.
 */
export type Domain = "trade" | "invest" | "learn" | "lab" | "automate" | "ai";

/**
 * Per-domain behavior counters. All numbers, all incrementing,
 * never decrementing. Stored as a flat object for easy persistence.
 *
 * trade.lastActiveDate is an ISO date string used for daysActive dedup.
 */
export interface DomainMetrics {
  trade: {
    ordersPlaced: number;
    widgetsUsed: number;
    daysActive: number;
    lastActiveDate: string;
  };
  invest: {
    holdingsViewed: number;
    sipsCreated: number;
    goalsSet: number;
  };
  learn: {
    lessonsCompleted: number;
    quizzesPassed: number;
    articlesRead: number;
  };
  lab: {
    backtestsRun: number;
    strategiesCreated: number;
    optimizationsRun: number;
  };
  automate: {
    flowsCreated: number;
    alertsSet: number;
    strategiesUploaded: number;
  };
  ai: {
    questionsAsked: number;
    strategiesGenerated: number;
    signalsActedOn: number;
  };
}

export interface HelpPrefs {
  /** "?" tooltips on form fields */
  inlineHints: boolean;
  /** Per-route guided tours */
  spotlightTours: boolean;
  /** Floating AI tutor pill */
  aiTutor: boolean;
}

export interface UpgradeSuggestion {
  domain: Domain;
  fromLevel: SkillLevel;
  toLevel: SkillLevel;
  /** Human-readable reason, e.g. "20 trades placed" */
  reason: string;
  timestamp: number;
}
