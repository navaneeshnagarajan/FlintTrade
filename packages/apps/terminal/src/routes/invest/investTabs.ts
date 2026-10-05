/**
 * Invest navigation — five groups over the previous flat tab row.
 *
 * Old leaf hashes (`#sip`, `#networth`, …) and group hashes (`#overview`)
 * resolve to a group plus a sub-view. Tabs that were not in the sixteen-tab
 * row stay inside Analyse or Discover so those links keep working.
 */

import type { SkillLevel } from "@/types/skill";

export type InvestTabId =
  | "dashboard"
  | "holdings"
  | "sip"
  | "networth"
  | "social"
  | "sector"
  | "overlap"
  | "etf"
  | "stocks"
  | "ipo"
  | "tax"
  | "mf-optimizer"
  | "mutual-funds"
  | "benchmark"
  | "basket"
  | "goals"
  | "etf-screener"
  | "shareholding"
  | "sector-rotation"
  | "risk-return"
  | "correlation";

export interface InvestGroup {
  id: "overview" | "holdings" | "analyse" | "discover" | "tax";
  label: string;
  tabs: readonly InvestTabId[];
}

export const INVEST_GROUPS: readonly InvestGroup[] = [
  { id: "overview", label: "Overview", tabs: ["dashboard", "networth", "goals"] },
  { id: "holdings", label: "Holdings", tabs: ["holdings", "mutual-funds", "sip", "basket"] },
  {
    id: "analyse",
    label: "Analyse",
    tabs: ["sector", "sector-rotation", "overlap", "benchmark", "shareholding", "risk-return", "correlation"],
  },
  {
    id: "discover",
    label: "Discover",
    tabs: ["etf-screener", "mf-optimizer", "social", "etf", "stocks", "ipo"],
  },
  { id: "tax", label: "Tax", tabs: ["tax"] },
];

const ALL_TABS: InvestTabId[] = INVEST_GROUPS.flatMap((group) => [...group.tabs]);

const BEGINNER_TABS: readonly InvestTabId[] = [
  "dashboard",
  "holdings",
  "sip",
  "networth",
  "goals",
  "mf-optimizer",
  "mutual-funds",
];

const INTERMEDIATE_HIDDEN: readonly InvestTabId[] = ["etf", "stocks", "ipo", "risk-return", "correlation"];

export function tabsForSkill(level: SkillLevel): InvestTabId[] {
  if (level === "advanced") return [...ALL_TABS];
  if (level === "beginner") return ALL_TABS.filter((id) => BEGINNER_TABS.includes(id));
  return ALL_TABS.filter((id) => !INTERMEDIATE_HIDDEN.includes(id));
}

/** Skill-visible tabs, plus the active deep link when skill would otherwise hide it. */
export function visibleInvestTabs(level: SkillLevel, activeTab: InvestTabId): InvestTabId[] {
  const allowed = tabsForSkill(level);
  return allowed.includes(activeTab) ? allowed : [...allowed, activeTab];
}

export function groupForTab(tabId: InvestTabId): InvestGroup {
  const group = INVEST_GROUPS.find((candidate) => candidate.tabs.includes(tabId));
  return group ?? INVEST_GROUPS[0];
}

export interface InvestLocation {
  groupId: InvestGroup["id"];
  tabId: InvestTabId;
}

/**
 * Map an Invest hash to a group and sub-view.
 *
 * Unknown hashes open Overview → Dashboard. A group id opens that group's
 * first sub-view.
 */
export function resolveInvestLocation(hash: string): InvestLocation {
  const raw = hash.replace(/^#/, "").trim();
  for (const group of INVEST_GROUPS) {
    if ((group.tabs as readonly string[]).includes(raw)) {
      return { groupId: group.id, tabId: raw as InvestTabId };
    }
  }
  const group = INVEST_GROUPS.find((candidate) => candidate.id === raw);
  if (group) {
    return { groupId: group.id, tabId: group.tabs[0] };
  }
  return { groupId: "overview", tabId: "dashboard" };
}
