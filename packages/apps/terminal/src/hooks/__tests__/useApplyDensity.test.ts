import { describe, expect, it, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { DENSITY_ATTRIBUTE } from "@/lib/applyDensity";
import { useSettingsStore } from "@/stores/settingsStore";
import { useApplyDensity } from "../useApplyDensity";

describe("useApplyDensity", () => {
  afterEach(() => {
    document.documentElement.removeAttribute(DENSITY_ATTRIBUTE);
    document.documentElement.classList.remove("density-compact", "density-comfortable");
    useSettingsStore.setState({ density: "comfortable" });
  });

  it("applies the persisted density on mount and when it changes", () => {
    useSettingsStore.setState({ density: "comfortable" });
    const { rerender } = renderHook(() => useApplyDensity());
    expect(document.documentElement.getAttribute(DENSITY_ATTRIBUTE)).toBe("comfortable");

    useSettingsStore.setState({ density: "compact" });
    rerender();
    expect(document.documentElement.getAttribute(DENSITY_ATTRIBUTE)).toBe("compact");
    expect(document.documentElement.classList.contains("density-compact")).toBe(true);
  });
});
