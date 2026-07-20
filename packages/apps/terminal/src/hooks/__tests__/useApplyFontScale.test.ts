/**
 * useApplyFontScale tests
 *
 * The font-size preference must be mirrored onto the document root as a
 * `data-font-scale` attribute — the design-system resolves that attribute
 * into the `--ft-font-scale` typography multiplier. Without the mirror the
 * setting is stored but never rendered (the original bug).
 */

import { describe, it, expect, afterEach, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  applyFontScale,
  useApplyFontScale,
  FONT_SCALE_ATTRIBUTE,
} from "../useApplyFontScale";
import { useSettingsStore } from "@/stores/settingsStore";

describe("useApplyFontScale", () => {
  beforeEach(() => {
    useSettingsStore.setState(useSettingsStore.getInitialState());
  });

  afterEach(() => {
    document.documentElement.removeAttribute(FONT_SCALE_ATTRIBUTE);
  });

  it("applyFontScale writes the setting to <html data-font-scale>", () => {
    applyFontScale("small");
    expect(document.documentElement.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("small");

    applyFontScale("large");
    expect(document.documentElement.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("large");
  });

  it("applies the persisted font scale on mount", () => {
    useSettingsStore.setState({ fontSize: "large" });

    renderHook(() => useApplyFontScale());

    expect(document.documentElement.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("large");
  });

  it("re-applies the root attribute whenever the setting changes", () => {
    renderHook(() => useApplyFontScale());
    expect(document.documentElement.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("normal");

    act(() => {
      useSettingsStore.getState().setFontSize("small");
    });
    expect(document.documentElement.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("small");

    act(() => {
      useSettingsStore.getState().setFontSize("large");
    });
    expect(document.documentElement.getAttribute(FONT_SCALE_ATTRIBUTE)).toBe("large");
  });
});
