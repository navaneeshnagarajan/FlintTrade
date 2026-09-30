import { describe, expect, it } from "vitest";
import { INVEST_GROUPS, resolveInvestLocation, tabsForSkill } from "../investTabs";

describe("Invest tab groups", () => {
  it("exposes five groups with the locked sub-views", () => {
    expect(INVEST_GROUPS.map((group) => group.label)).toEqual([
      "Overview",
      "Holdings",
      "Analyse",
      "Discover",
      "Tax",
    ]);
    expect(INVEST_GROUPS.find((group) => group.id === "overview")?.tabs).toEqual([
      "dashboard",
      "networth",
      "goals",
    ]);
    expect(INVEST_GROUPS.find((group) => group.id === "holdings")?.tabs.slice(0, 4)).toEqual([
      "holdings",
      "mutual-funds",
      "sip",
      "basket",
    ]);
    expect(INVEST_GROUPS.find((group) => group.id === "analyse")?.tabs.slice(0, 5)).toEqual([
      "sector",
      "sector-rotation",
      "overlap",
      "benchmark",
      "shareholding",
    ]);
    expect(INVEST_GROUPS.find((group) => group.id === "discover")?.tabs.slice(0, 3)).toEqual([
      "etf-screener",
      "mf-optimizer",
      "social",
    ]);
    expect(INVEST_GROUPS.find((group) => group.id === "tax")?.tabs).toEqual(["tax"]);
  });

  it("redirects old leaf hashes and group hashes onto a group and sub-view", () => {
    expect(resolveInvestLocation("#sip")).toEqual({ groupId: "holdings", tabId: "sip" });
    expect(resolveInvestLocation("#networth")).toEqual({ groupId: "overview", tabId: "networth" });
    expect(resolveInvestLocation("#sector-rotation")).toEqual({
      groupId: "analyse",
      tabId: "sector-rotation",
    });
    expect(resolveInvestLocation("#overview")).toEqual({ groupId: "overview", tabId: "dashboard" });
    expect(resolveInvestLocation("#not-a-tab")).toEqual({ groupId: "overview", tabId: "dashboard" });
    expect(resolveInvestLocation("")).toEqual({ groupId: "overview", tabId: "dashboard" });
  });

  it("keeps the sixteen-tab intermediate set inside the five groups", () => {
    const intermediate = tabsForSkill("intermediate");
    expect(intermediate).toHaveLength(16);
    expect(intermediate).not.toContain("etf");
    expect(intermediate).toContain("sector-rotation");
    expect(tabsForSkill("advanced").length).toBeGreaterThan(16);
  });
});
