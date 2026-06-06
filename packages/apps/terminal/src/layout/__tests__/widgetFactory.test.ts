import { describe, expect, it } from "vitest";

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

    expect(widgetCatalog).toHaveLength(84);
    expect(counts).toEqual({
      Analysis: 39,
      Trading: 22,
      Utility: 23,
    });
  });
});
