/**
 * workspacePresets.test.ts
 *
 * Structural tests for the built-in workspace presets, focused on the
 * Options Scalper preset whose four charts are pinned to independent
 * instruments via per-panel params.
 */

import { describe, it, expect, vi } from "vitest";
import type { DockviewApi } from "dockview-react";

import { WORKSPACE_PRESETS, applyPreset } from "../workspacePresets";

interface RecordedPanel {
  id?: string;
  component?: string;
  title?: string;
  params?: Record<string, unknown>;
  position?: { referencePanel?: string; direction?: string };
}

function mockApi(): { api: DockviewApi; panels: RecordedPanel[]; cleared: () => number } {
  const panels: RecordedPanel[] = [];
  let clears = 0;
  const api = {
    clear: vi.fn(() => {
      clears += 1;
    }),
    addPanel: vi.fn((opts: RecordedPanel) => {
      panels.push(opts);
      return { id: opts.title };
    }),
  } as unknown as DockviewApi;
  return { api, panels, cleared: () => clears };
}

describe("workspacePresets", () => {
  it("registers the Options Scalper preset", () => {
    const preset = WORKSPACE_PRESETS.find((p) => p.id === "options-scalper");
    expect(preset).toBeDefined();
    expect(preset?.name).toBe("Options Scalper");
  });

  it("clears the canvas before applying a preset", () => {
    const { api, cleared } = mockApi();
    applyPreset(api, "options-scalper");
    expect(cleared()).toBe(1);
  });

  it("Options Scalper lays out four independent charts + an option chain", () => {
    const { api, panels } = mockApi();
    applyPreset(api, "options-scalper");

    const charts = panels.filter((p) => p.component === "chart");
    const chains = panels.filter((p) => p.component === "optionchain");
    expect(charts).toHaveLength(4);
    expect(chains).toHaveLength(1);

    // The four charts are titled for their role and pinned to a symbol so they
    // do not all track one global instrument.
    expect(charts.map((c) => c.title).sort()).toEqual(
      ["CE Strike", "Futures", "Index", "PE Strike"],
    );
    for (const chart of charts) {
      expect(chart.params?.symbol).toBeTruthy();
      expect(chart.params?.exchange).toBe("NSE_INDEX");
      expect(chart.params?.interval).toBe("1m"); // fast scalping interval
    }

    expect(chains[0].params?.symbol).toBe("NIFTY");
  });

  it("registers the Multi Chart preset that replaced the chartgrid widget", () => {
    const preset = WORKSPACE_PRESETS.find((p) => p.id === "multi-chart");
    expect(preset).toBeDefined();
    expect(preset?.name).toBe("Multi Chart");
  });

  it("Multi Chart lays out four independent charts on the retired widget's default instruments", () => {
    const { api, panels } = mockApi();
    applyPreset(api, "multi-chart");

    const charts = panels.filter((p) => p.component === "chart");
    expect(panels).toHaveLength(4);
    expect(charts).toHaveLength(4);

    // The retired ChartGrid seeded its cells with these four NSE indices and
    // gave each cell its own symbol/exchange/interval — panel params carry that
    // per-cell independence over, and pin each chart to its instrument.
    expect(charts.map((c) => c.params?.symbol)).toEqual(
      ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"],
    );
    expect(charts.map((c) => c.title)).toEqual(
      ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"],
    );
    for (const chart of charts) {
      expect(chart.params?.exchange).toBe("NSE_INDEX");
      expect(chart.params?.interval).toBe("5m");
    }
  });

  it("Multi Chart arranges its four charts as a 2x2 grid", () => {
    const { api, panels } = mockApi();
    applyPreset(api, "multi-chart");

    const [topLeft, topRight, bottomLeft, bottomRight] = panels;
    expect(topLeft.position).toBeUndefined(); // first panel anchors the grid
    expect(topRight.position).toEqual({ referencePanel: topLeft.id, direction: "right" });
    expect(bottomLeft.position).toEqual({ referencePanel: topLeft.id, direction: "below" });
    expect(bottomRight.position).toEqual({ referencePanel: topRight.id, direction: "below" });
  });

  it("no preset composes the retired chartgrid widget", () => {
    for (const preset of WORKSPACE_PRESETS) {
      const { api, panels } = mockApi();
      applyPreset(api, preset.id);
      expect(panels.map((p) => p.component)).not.toContain("chartgrid");
    }
  });

  it("unknown preset id is a no-op (does not throw, does not clear)", () => {
    const { api, cleared } = mockApi();
    applyPreset(api, "does-not-exist");
    expect(cleared()).toBe(0);
  });
});
