import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useSkillStore } from "@/stores/skillStore";
import { useFeatureGate } from "@/hooks/useFeatureGate";
import { useSkillContent } from "@/hooks/useSkillContent";
import { widgetCatalog } from "@/layout/widgetFactory";

// Experience affects neither discovery nor execution permission. The latter is
// independently enforced by the unchanged account/admission interfaces.
describe("unrestricted capability discovery", () => {
  it("offers every registered widget and tool without experience prerequisites", () => {
    useSkillStore.setState({ globalLevel: "beginner" });
    const { result } = renderHook(() => ({ content: useSkillContent(), automation: useFeatureGate("route:automate") }));
    expect(result.current.automation).toBe("visible");
    expect(new Set(result.current.content.availableWidgets)).toEqual(new Set(widgetCatalog.map(w => w.id)));
    expect(result.current.content.availableTools).toContain("trade-journal");
  });
});
