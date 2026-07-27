/**
 * workspacePresets.test.ts
 *
 * Structural tests for the built-in workspace presets over the FlexLayout
 * JSON documents the builders return — every preset must parse into a real
 * Model, every tab must resolve to a registered widget, and the presets
 * with per-panel pinned params keep their pins.
 */

import { describe, it, expect, vi } from "vitest";
import { Model } from "flexlayout-react";
import type { IJsonModel, IJsonRowNode, IJsonTabNode, IJsonTabSetNode } from "flexlayout-react";

import {
  WORKSPACE_PRESETS,
  applyPreset,
  buildBeginnerCore,
  buildPresetJsonById,
} from "../workspacePresets";
import { widgetComponents } from "../widgetFactory";
import type { WorkspaceApi } from "../flexLayoutAdapter";

/** Depth-first collection of every tab node in a preset document. */
function collectTabs(json: IJsonModel): IJsonTabNode[] {
  const tabs: IJsonTabNode[] = [];
  const visit = (node: IJsonRowNode | IJsonTabSetNode): void => {
    if (node.type === "tabset") {
      for (const tab of (node as IJsonTabSetNode).children ?? []) tabs.push(tab);
      return;
    }
    for (const child of (node as IJsonRowNode).children ?? []) visit(child);
  };
  visit(json.layout);
  return tabs;
}

function mockApi(): { api: WorkspaceApi; loaded: IJsonModel[] } {
  const loaded: IJsonModel[] = [];
  const api = {
    addPanel: vi.fn(),
    clear: vi.fn(),
    panelCount: vi.fn(() => 0),
    toJSON: vi.fn(() => ({})),
    fromJSON: vi.fn(),
    loadModelJson: vi.fn((json: IJsonModel) => {
      loaded.push(json);
    }),
  } satisfies WorkspaceApi;
  return { api, loaded };
}

describe("workspacePresets", () => {
  it("every preset builds a document FlexLayout can parse", () => {
    for (const preset of WORKSPACE_PRESETS) {
      const model = Model.fromJson(preset.build());
      expect(model.getRootRow(), `preset ${preset.id}`).toBeDefined();
    }
    expect(Model.fromJson(buildBeginnerCore()).getRootRow()).toBeDefined();
  });

  it("every preset tab resolves to a registered widget component", () => {
    const documents = [
      ...WORKSPACE_PRESETS.map((p) => ({ id: p.id, json: p.build() })),
      { id: "beginner-core", json: buildBeginnerCore() },
    ];
    for (const { id, json } of documents) {
      for (const tab of collectTabs(json)) {
        expect(
          tab.component !== undefined && tab.component in widgetComponents,
          `preset ${id} tab component "${tab.component}"`,
        ).toBe(true);
      }
    }
  });

  it("builds fresh panel ids on every application", () => {
    const first = collectTabs(buildPresetJsonById("multi-chart")!).map((t) => t.id);
    const second = collectTabs(buildPresetJsonById("multi-chart")!).map((t) => t.id);
    expect(first.every((id) => id !== undefined)).toBe(true);
    expect(new Set([...first, ...second]).size).toBe(first.length + second.length);
  });

  it("registers the Options Scalper preset", () => {
    const preset = WORKSPACE_PRESETS.find((p) => p.id === "options-scalper");
    expect(preset).toBeDefined();
    expect(preset?.name).toBe("Options Scalper");
  });

  it("Options Scalper lays out four independent charts + an option chain", () => {
    const tabs = collectTabs(buildPresetJsonById("options-scalper")!);

    const charts = tabs.filter((t) => t.component === "chart");
    const chains = tabs.filter((t) => t.component === "optionchain");
    expect(charts).toHaveLength(4);
    expect(chains).toHaveLength(1);

    // The four charts are titled for their role and pinned to a symbol so they
    // do not all track one global instrument.
    expect(charts.map((c) => c.name).sort()).toEqual(
      ["CE Strike", "Futures", "Index", "PE Strike"],
    );
    for (const chart of charts) {
      const params = chart.config as Record<string, unknown>;
      expect(params.symbol).toBeTruthy();
      expect(params.exchange).toBe("NSE_INDEX");
      expect(params.interval).toBe("1m"); // fast scalping interval
    }

    expect((chains[0].config as Record<string, unknown>).symbol).toBe("NIFTY");
  });

  it("registers the Multi Chart preset that replaced the chartgrid widget", () => {
    const preset = WORKSPACE_PRESETS.find((p) => p.id === "multi-chart");
    expect(preset).toBeDefined();
    expect(preset?.name).toBe("Multi Chart");
  });

  it("Multi Chart lays out four independent charts on the retired widget's default instruments", () => {
    const tabs = collectTabs(buildPresetJsonById("multi-chart")!);
    const charts = tabs.filter((t) => t.component === "chart");
    expect(tabs).toHaveLength(4);
    expect(charts).toHaveLength(4);

    // The retired ChartGrid seeded its cells with these four NSE indices and
    // gave each cell its own symbol/exchange/interval — panel params carry that
    // per-cell independence over, and pin each chart to its instrument.
    expect(charts.map((c) => c.name).sort()).toEqual(
      ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTY"],
    );
    for (const chart of charts) {
      const params = chart.config as Record<string, unknown>;
      expect(params.symbol).toBe(chart.name);
      expect(params.exchange).toBe("NSE_INDEX");
      expect(params.interval).toBe("5m");
    }
  });

  it("Multi Chart arranges its four charts as a 2x2 grid", () => {
    const json = buildPresetJsonById("multi-chart")!;
    const columns = json.layout.children ?? [];
    expect(columns).toHaveLength(2);
    for (const column of columns) {
      expect(column.type).toBe("row");
      const cells = (column as IJsonRowNode).children ?? [];
      expect(cells).toHaveLength(2);
      for (const cell of cells) expect(cell.type).toBe("tabset");
    }
  });

  it("no preset composes the retired chartgrid widget", () => {
    for (const preset of WORKSPACE_PRESETS) {
      const components = collectTabs(preset.build()).map((t) => t.component);
      expect(components).not.toContain("chartgrid");
    }
  });

  it("beginner-core resolves through buildPresetJsonById like a listed preset", () => {
    const json = buildPresetJsonById("beginner-core");
    expect(json).toBeDefined();
    const components = collectTabs(json!).map((t) => t.component).sort();
    expect(components).toEqual(["chart", "indexstrip", "orderpad", "positions", "watchlist"]);
  });

  it("unknown preset id is a no-op (does not throw, does not load)", () => {
    const { api, loaded } = mockApi();
    applyPreset(api, "does-not-exist");
    expect(loaded).toHaveLength(0);
    expect(buildPresetJsonById("does-not-exist")).toBeUndefined();
  });
});
