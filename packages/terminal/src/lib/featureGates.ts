import type { SkillLevel } from "@/types/skill";

export type GateStatus = "visible" | "preview" | "locked";

export const FEATURE_GATES: Record<string, Record<SkillLevel, GateStatus>> = {
  // ---------------------------------------------------------------
  // Core widgets — always visible at every skill level
  // ---------------------------------------------------------------
  "widget:dashboard":   { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:chart":       { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:watchlist":   { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:orderpad":    { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:positions":   { beginner: "visible", intermediate: "visible", advanced: "visible" },

  // ---------------------------------------------------------------
  // Intermediate-unlock widgets
  // ---------------------------------------------------------------
  "widget:orders":      { beginner: "preview", intermediate: "visible", advanced: "visible" },
  "widget:holdings":    { beginner: "preview", intermediate: "visible", advanced: "visible" },
  "widget:tradebook":   { beginner: "preview", intermediate: "visible", advanced: "visible" },
  "widget:scalper":     { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:optionchain": { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:oichart":     { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:straddle":    { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:depth":       { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:news":        { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:ticker":      { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:calculator":  { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:aiadvisor":   { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "widget:mtmmonitor":  { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:riskpanel":   { beginner: "locked",  intermediate: "visible", advanced: "visible" },
  "widget:actioncenter":{ beginner: "locked",  intermediate: "preview", advanced: "visible" },

  // ---------------------------------------------------------------
  // Analysis widgets — advanced-only or advanced-unlock
  // ---------------------------------------------------------------
  "widget:sectormap":   { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "widget:greeks":      { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "widget:gex":         { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "widget:volsurface":  { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "widget:ivsmile":     { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "widget:straddlepnl": { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "widget:oiprofile":   { beginner: "locked",  intermediate: "locked",  advanced: "visible" },

  // ---------------------------------------------------------------
  // Route-level gates
  // ---------------------------------------------------------------
  "route:trade":        { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "route:invest":       { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "route:learn":        { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "route:lab":          { beginner: "preview", intermediate: "visible", advanced: "visible" },
  "route:automate":     { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "route:ai":           { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "route:settings":     { beginner: "visible", intermediate: "visible", advanced: "visible" },

  // ---------------------------------------------------------------
  // Feature-level gates (within routes)
  // ---------------------------------------------------------------
  "feature:order-confirm":       { beginner: "visible", intermediate: "visible", advanced: "visible" },
  "feature:basket-orders":       { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "feature:split-orders":        { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "feature:options-multi-order": { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "feature:python-strategy":     { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "feature:multi-account":       { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "feature:monte-carlo":         { beginner: "locked",  intermediate: "locked",  advanced: "visible" },
  "feature:rag-pipeline":        { beginner: "locked",  intermediate: "preview", advanced: "visible" },
  "feature:keyboard-shortcuts":  { beginner: "preview", intermediate: "visible", advanced: "visible" },
};
