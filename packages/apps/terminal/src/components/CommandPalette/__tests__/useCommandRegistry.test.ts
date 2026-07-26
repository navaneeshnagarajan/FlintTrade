/**
 * useCommandRegistry.test.ts
 *
 * Covers the layout-preset commands that make every workspace preset
 * (including the Options Scalper desk) applicable from the Ctrl+K palette.
 */

import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ setTheme: vi.fn(), setMode: vi.fn(), mode: "dark" }),
}));

import {
  BEGINNER_WIDGET_IDS,
  INTERMEDIATE_WIDGET_IDS,
  useCommandRegistry,
} from "../useCommandRegistry";
import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";
import { widgetCatalog } from "@/layout/widgetFactory";

describe("useCommandRegistry — layout preset commands", () => {
  it("exposes one Apply-layout command per built-in workspace preset", () => {
    const { result } = renderHook(() => useCommandRegistry());
    const layoutCmds = result.current.commands.filter((c) => c.id.startsWith("layout:"));
    expect(layoutCmds).toHaveLength(WORKSPACE_PRESETS.length);
    expect(layoutCmds.every((c) => c.category === "action")).toBe(true);
  });

  it("includes the Options Scalper layout and dispatches its apply action", () => {
    const { result } = renderHook(() => useCommandRegistry());
    const cmd = result.current.commands.find((c) => c.id === "layout:options-scalper");
    const listener = vi.fn();
    window.addEventListener("flinttrade:apply-layout", listener);
    expect(cmd).toBeDefined();
    expect(cmd?.title).toBe("Apply layout: Options Scalper");

    cmd?.action();
    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0]?.[0] as CustomEvent<{ presetId?: string }>;
    expect(event.detail.presetId).toBe("options-scalper");
    window.removeEventListener("flinttrade:apply-layout", listener);
  });

  it("layout commands are discoverable by preset name via search", () => {
    const { result } = renderHook(() => useCommandRegistry());
    const hits = result.current.searchCommands("scalper");
    expect(hits.some((c) => c.id === "layout:options-scalper")).toBe(true);
  });
});

describe("useCommandRegistry — skill-tier widget gates", () => {
  // Both gates match on catalogue id, so a wrong id fails silently and
  // *subtracts* a widget from the tier. That is what happened: `depth` stayed
  // on the intermediate list after being merged into `orderladder`, and `pnl`
  // was never a catalogue id at all (`intradaypnl` is), so intermediate users
  // lost the DOM / Ladder and Intraday P&L without a single failing test.
  const catalogIds = new Set(widgetCatalog.map((widget) => widget.id));

  it.each([
    ["beginner", BEGINNER_WIDGET_IDS],
    ["intermediate", INTERMEDIATE_WIDGET_IDS],
  ])("gates the %s tier only on ids the catalogue still carries", (_tier, ids) => {
    const unknown = [...ids].filter((id) => !catalogIds.has(id)).sort();
    expect(unknown).toEqual([]);
  });

  it("keeps the beginner tier a subset of the intermediate tier", () => {
    const missing = [...BEGINNER_WIDGET_IDS]
      .filter((id) => !INTERMEDIATE_WIDGET_IDS.has(id))
      .sort();
    expect(missing).toEqual([]);
  });
});
