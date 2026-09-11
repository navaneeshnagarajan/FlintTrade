import { describe, expect, it } from "vitest";
import {
  COMPACT_DESK_COLLAPSED_WIDGETS,
  COMPACT_DESK_PRESET_ID,
  COMPACT_DESK_PRIMARY_WIDGETS,
  DESK_COMPACT_FOCUS_MAX_WIDTH,
  DESK_MIN_WIDTH,
  applyCompactDeskToolsDisclosure,
  collectWorkspaceComponents,
  defaultTradePresetId,
  isTradePath,
  resolveDockMode,
  showFullToolRibbon,
  showTickerChrome,
  usesCompactProgressiveDisclosure,
} from "../tradeDeskDensity";

describe("FT-UX-001 Compact Trade disclosure", () => {
  it("applies progressive disclosure at 1280 Compact and widescreen Compact", () => {
    expect(usesCompactProgressiveDisclosure("compact", DESK_MIN_WIDTH)).toBe(true);
    expect(usesCompactProgressiveDisclosure("compact", DESK_COMPACT_FOCUS_MAX_WIDTH)).toBe(true);
    expect(usesCompactProgressiveDisclosure("compact", 1920)).toBe(true);
    expect(usesCompactProgressiveDisclosure("comfortable", 1280)).toBe(false);
    expect(usesCompactProgressiveDisclosure("compact", 1024)).toBe(false);
    expect(usesCompactProgressiveDisclosure("compact", 1280, false)).toBe(false);
    expect(isTradePath("/trade")).toBe(true);
    expect(isTradePath("/home")).toBe(false);
    expect(isTradePath("/settings")).toBe(false);
  });

  it("defaults Compact desk to chart + order pad + positions", () => {
    expect(defaultTradePresetId("beginner", "compact", 1280)).toBe(COMPACT_DESK_PRESET_ID);
    expect([...COMPACT_DESK_PRIMARY_WIDGETS]).toEqual(["chart", "orderpad", "positions"]);
    expect([...COMPACT_DESK_COLLAPSED_WIDGETS]).toEqual(
      expect.arrayContaining(["watchlist", "orderladder", "ticker"]),
    );
  });

  it("Comfortable restores the skill-level default layout", () => {
    expect(defaultTradePresetId("beginner", "comfortable", 1280)).toBe("beginner-core");
    expect(defaultTradePresetId("intermediate", "comfortable", 1440)).toBe("market-watch");
    expect(defaultTradePresetId("advanced", "compact", 1280, true)).toBe("scalper-zone");
  });

  it("Compact desk forces icon rail; Comfortable desk restores labels", () => {
    expect(resolveDockMode("compact", "expanded", 1280)).toBe("icons");
    expect(resolveDockMode("comfortable", "icons", 1280)).toBe("expanded");
    expect(resolveDockMode("comfortable", "hidden", 1280)).toBe("hidden");
  });

  it("hides ticker and the full tool ribbon until the desk-tools toggle opens", () => {
    expect(showTickerChrome("compact", 1280)).toBe(false);
    expect(showFullToolRibbon("compact", 1280)).toBe(false);
    expect(showTickerChrome("compact", 1280, true)).toBe(true);
    expect(showFullToolRibbon("comfortable", 1280)).toBe(true);
    expect(showTickerChrome("comfortable", 1280)).toBe(true);
    expect(showTickerChrome("compact", 1280, false, false)).toBe(true);
    expect(showFullToolRibbon("compact", 1280, false, false)).toBe(true);
    expect(resolveDockMode("compact", "expanded", 1280, false)).toBe("expanded");
  });

  it("desk-tools expand adds Watchlist; collapse restores compact-desk when safe", () => {
    const compactJson = {
      layout: {
        children: [
          { component: "chart" },
          { component: "orderpad" },
          { component: "positions" },
        ],
      },
    };
    const withWatchlist = {
      layout: {
        children: [
          { component: "chart" },
          { component: "orderpad" },
          { component: "positions" },
          { component: "watchlist" },
        ],
      },
    };
    expect(collectWorkspaceComponents(compactJson)).toEqual(["chart", "orderpad", "positions"]);

    let current = compactJson as Record<string, unknown>;
    const added: Array<{ component: string; title: string }> = [];
    const loaded: Array<Record<string, unknown>> = [];
    const api = {
      addPanel: (panel: { component: string; title: string }) => {
        added.push(panel);
        current = withWatchlist;
      },
      toJSON: () => current,
      loadModelJson: (json: Record<string, unknown>) => {
        loaded.push(json);
        current = json;
      },
    };

    applyCompactDeskToolsDisclosure(api, true, () => ({ restored: true }));
    expect(added).toEqual([{ component: "watchlist", title: "Watchlist" }]);

    applyCompactDeskToolsDisclosure(api, false, () => ({ restored: true }));
    expect(loaded).toEqual([{ restored: true }]);
  });

  it("does not wipe a customised desk when collapsing desk tools", () => {
    const custom = {
      layout: {
        children: [
          { component: "chart" },
          { component: "orderpad" },
          { component: "positions" },
          { component: "watchlist" },
          { component: "news" },
        ],
      },
    };
    const loaded: unknown[] = [];
    applyCompactDeskToolsDisclosure(
      {
        addPanel: () => undefined,
        toJSON: () => custom,
        loadModelJson: (json) => {
          loaded.push(json);
        },
      },
      false,
      () => ({ restored: true }),
    );
    expect(loaded).toEqual([]);
  });
});
