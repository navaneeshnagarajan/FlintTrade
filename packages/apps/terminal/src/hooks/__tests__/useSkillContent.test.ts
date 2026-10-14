import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSkillStore } from "@/stores/skillStore";
import { useSkillContent } from "../useSkillContent";
import { widgetCatalog, RETIRED_WIDGET_IDS } from "@/layout/widgetFactory";
beforeEach(() => useSkillStore.getState().resetToDefaults());
for (const level of ["beginner", "intermediate", "advanced"] as const) describe(`retired ${level} preference`, () => {
  beforeEach(() => useSkillStore.getState().setGlobalLevel(level));
  it("cannot hide any active widget", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(new Set(result.current.availableWidgets)).toEqual(new Set(widgetCatalog.map(w => w.id)));
  });
  it("retains all tools and advanced content", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.availableTools).toEqual(["trade-journal", "settings"]);
    expect(result.current.showAdvanced).toBe(true);
  });
  it("does not resurrect retired widget aliases in the picker", () => {
    const { result } = renderHook(() => useSkillContent());
    for (const id of Object.keys(RETIRED_WIDGET_IDS)) expect(result.current.availableWidgets).not.toContain(id);
  });
  it("keeps a single neutral default and detailed hints", () => {
    const { result } = renderHook(() => useSkillContent());
    expect(result.current.defaultPreset).toBe("market-watch"); expect(result.current.tooltipLevel).toBe("detailed");
  });
});
it("legacy global or per-route preferences cannot change discovery", () => {
  const { result, rerender } = renderHook(() => useSkillContent()); const before = result.current;
  act(() => { useSkillStore.getState().setGlobalLevel("advanced"); useSkillStore.getState().setRouteOverride("trade", "beginner"); });
  rerender(); expect(result.current).toBe(before);
});
