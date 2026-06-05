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
  component?: string;
  title?: string;
  params?: Record<string, unknown>;
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

  it("unknown preset id is a no-op (does not throw, does not clear)", () => {
    const { api, cleared } = mockApi();
    applyPreset(api, "does-not-exist");
    expect(cleared()).toBe(0);
  });
});
