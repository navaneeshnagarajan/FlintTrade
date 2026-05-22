/**
 * tourDefinitions.ts
 *
 * Per-route guided tour definitions. Each tour targets elements via
 * `data-tour-target` attributes (e.g. `<div data-tour-target="watchlist">`).
 *
 * Tours are keyed by `tourId` strings that match the route + skill level
 * pattern. The SpotlightTour component uses these to drive step-by-step
 * onboarding overlays.
 *
 * To add a new tour:
 *   1. Add a new entry below with a descriptive tourId
 *   2. Ensure all target elements have matching `data-tour-target` attributes
 *   3. Register the tour in the route's component or layout
 */

// ---------------------------------------------------------------------------
// Types (re-exported from SpotlightTour for convenience)
// ---------------------------------------------------------------------------

export interface TourStep {
  /** Value of the `data-tour-target` attribute on the target element */
  target: string;
  /** Step heading shown in the spotlight card */
  title: string;
  /** Step body text explaining the feature */
  description: string;
  /** Preferred placement of the step card relative to the target */
  position?: "top" | "bottom" | "left" | "right";
}

// ---------------------------------------------------------------------------
// Definitions
// ---------------------------------------------------------------------------

export const TOUR_DEFINITIONS: Record<string, TourStep[]> = {
  "trade-beginner": [
    {
      target: "watchlist",
      title: "Your Watchlist",
      description:
        "Track your favorite stocks here. Click + to add symbols.",
      position: "right",
    },
    {
      target: "chart",
      title: "Price Chart",
      description:
        "See price movements over time. Switch timeframes with the buttons above.",
      position: "bottom",
    },
    {
      target: "order-pad",
      title: "Place Orders",
      description:
        "Buy or sell from here. Start with paper trading to practice!",
      position: "left",
    },
  ],

  "invest-beginner": [
    {
      target: "holdings",
      title: "Your Holdings",
      description: "All your investments in one place.",
      position: "right",
    },
    {
      target: "networth",
      title: "Net Worth",
      description:
        "Your total portfolio value across all brokers and asset classes.",
      position: "bottom",
    },
  ],

  "learn-beginner": [
    {
      target: "course-list",
      title: "Courses",
      description:
        "Start with the basics. Each course has bite-sized lessons you can finish in minutes.",
      position: "right",
    },
    {
      target: "glossary",
      title: "Market Glossary",
      description:
        "Look up any trading term you don't understand. Definitions are written in plain language.",
      position: "left",
    },
  ],

  "lab-beginner": [
    {
      target: "strategy-picker",
      title: "Choose a Strategy",
      description:
        "Pick a built-in strategy or create your own. Start with a simple moving average crossover.",
      position: "bottom",
    },
    {
      target: "backtest-results",
      title: "Backtest Results",
      description:
        "See how your strategy would have performed historically. Check Sharpe ratio and max drawdown.",
      position: "top",
    },
  ],

  "automate-beginner": [
    {
      target: "flow-builder",
      title: "Flow Builder",
      description:
        "Create automated trading flows with visual drag-and-drop. Connect triggers, conditions, and actions without writing code.",
      position: "bottom",
    },
    {
      target: "cron-manager",
      title: "Scheduled Tasks",
      description:
        "Set up recurring tasks like pre-market scans or end-of-day reports. Runs even when the terminal is closed.",
      position: "right",
    },
  ],

  "ai-beginner": [
    {
      target: "ai-chat",
      title: "AI Chat",
      description:
        "Ask questions about markets, strategies, or your portfolio. Powered by your local LLM — fully private.",
      position: "top",
    },
    {
      target: "ai-section-nav",
      title: "AI Suggestions",
      description:
        "Switch to suggestions when you want the advisor to draft strategy ideas from your current market context.",
      position: "bottom",
    },
  ],
};
