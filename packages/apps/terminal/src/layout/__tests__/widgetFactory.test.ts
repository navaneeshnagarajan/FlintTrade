import { describe, expect, it } from "vitest";

import { ICON_MAP } from "@/chrome/WidgetPicker";
import { widgetCatalog, widgetComponents } from "../widgetFactory";

describe("widgetFactory catalogue wiring", () => {
  it("keeps the public widget catalogue and Dockview component map in sync", () => {
    const catalogIds = widgetCatalog.map((widget) => widget.id);
    const componentIds = Object.keys(widgetComponents).sort();

    expect(new Set(catalogIds).size).toBe(catalogIds.length);
    expect([...catalogIds].sort()).toEqual(componentIds);
  });

  it("documents the current terminal widget category split", () => {
    const counts = widgetCatalog.reduce<Record<string, number>>((acc, widget) => {
      acc[widget.category] = (acc[widget.category] ?? 0) + 1;
      return acc;
    }, {});

    expect(widgetCatalog).toHaveLength(100);
    expect(counts).toEqual({
      Analysis: 48,
      Trading: 26,
      Utility: 26,
    });
  });

  it("resolves every catalogue icon in the WidgetPicker ICON_MAP", () => {
    // A name missing from ICON_MAP silently renders the generic Box icon in
    // the picker — at one point 38 of 64 catalogue icons were missing.
    const missing = widgetCatalog
      .map((w) => w.icon)
      .filter((icon) => !(icon in ICON_MAP));
    expect(missing).toEqual([]);
  });
});
