import { describe, expect, it } from "vitest";

import { ICON_MAP } from "@/chrome/WidgetPicker";
import { widgetCatalog, widgetComponents, RETIRED_WIDGET_IDS } from "../widgetFactory";

describe("widgetFactory catalogue wiring", () => {
  it("resolves every catalogue widget, and every extra component is a documented retirement", () => {
    // This used to assert a strict bijection. Merged widgets break that by
    // design: a retired id leaves the picker but MUST keep resolving, because
    // Dockview looks a saved panel's component up in this map alone and
    // TerminalRoute discards the operator's entire saved tab when one fails.
    const catalogIds = widgetCatalog.map((widget) => widget.id);
    const componentIds = Object.keys(widgetComponents);

    expect(new Set(catalogIds).size).toBe(catalogIds.length);
    // Every catalogue widget resolves.
    for (const id of catalogIds) {
      expect(componentIds).toContain(id);
    }
    // Every extra resolvable id is an intentional, documented retirement.
    const extras = componentIds.filter((id) => !catalogIds.includes(id)).sort();
    expect(extras).toEqual(Object.keys(RETIRED_WIDGET_IDS).sort());
  });

  it("keeps every retired widget id loadable so saved layouts survive", () => {
    // A retired id that stopped resolving would not degrade one panel — it
    // would wipe the whole workspace tab (TerminalRoute's fromJSON catch).
    for (const [retiredId, spec] of Object.entries(RETIRED_WIDGET_IDS)) {
      expect(widgetComponents[retiredId], `${retiredId} must stay resolvable`).toBeTruthy();
      // Its canonical target must itself be a live widget.
      expect(widgetComponents[spec.component], `${retiredId} → ${spec.component}`).toBeTruthy();
      expect(widgetCatalog.map((w) => w.id)).toContain(spec.component);
      expect(spec.note.length).toBeGreaterThan(0);
    }
  });

  it("documents the current terminal widget category split", () => {
    const counts = widgetCatalog.reduce<Record<string, number>>((acc, widget) => {
      acc[widget.category] = (acc[widget.category] ?? 0) + 1;
      return acc;
    }, {});

    // Counts drop as widgets merge. docs/ARCHITECTURE.md, docs/USER_GUIDE.md
    // and the site's capabilities test pin these same numbers — update all
    // four together.
    expect(widgetCatalog).toHaveLength(82);
    expect(counts).toEqual({
      Analysis: 35,
      Trading: 23,
      Utility: 24,
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

  it("keeps Spread View out of the catalogue after its demotion to template data", () => {
    // It was four hardcoded two-leg spreads with no data source and a
    // permanently disabled execute button. The spreads are now entries in
    // lib/strategyTemplates.ts and its economic validator — the one thing it
    // uniquely owned — moved into the options builder.
    expect(widgetCatalog.find((widget) => widget.id === "spreadview")).toBeUndefined();
    expect(Object.keys(RETIRED_WIDGET_IDS)).toContain("spreadview");
  });
});
