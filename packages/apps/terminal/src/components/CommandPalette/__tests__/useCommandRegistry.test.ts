/**
 * useCommandRegistry.test.ts
 *
 * Covers the layout-preset commands that make every workspace preset
 * (including the Options Scalper desk) applicable from the Ctrl+K palette.
 */

import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";

const mockApplyPreset = vi.fn();

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ setTheme: vi.fn(), setMode: vi.fn(), mode: "dark" }),
}));

vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ applyPreset: mockApplyPreset }),
}));

import { useCommandRegistry } from "../useCommandRegistry";
import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";

describe("useCommandRegistry — layout preset commands", () => {
  it("exposes one Apply-layout command per built-in workspace preset", () => {
    const { result } = renderHook(() => useCommandRegistry());
    const layoutCmds = result.current.commands.filter((c) => c.id.startsWith("layout:"));
    expect(layoutCmds).toHaveLength(WORKSPACE_PRESETS.length);
    expect(layoutCmds.every((c) => c.category === "action")).toBe(true);
  });

  it("includes the Options Scalper layout and applies it on action", () => {
    const { result } = renderHook(() => useCommandRegistry());
    const cmd = result.current.commands.find((c) => c.id === "layout:options-scalper");
    expect(cmd).toBeDefined();
    expect(cmd?.title).toBe("Apply layout: Options Scalper");

    cmd?.action();
    expect(mockApplyPreset).toHaveBeenCalledWith("options-scalper");
  });

  it("layout commands are discoverable by preset name via search", () => {
    const { result } = renderHook(() => useCommandRegistry());
    const hits = result.current.searchCommands("scalper");
    expect(hits.some((c) => c.id === "layout:options-scalper")).toBe(true);
  });
});
