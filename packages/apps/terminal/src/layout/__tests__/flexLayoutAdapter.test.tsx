/**
 * flexLayoutAdapter.test.tsx
 *
 * Exercises the real FlexLayout bridge over genuine Model documents — no
 * view rendering needed. Pins the two audit regressions:
 *  - updateParameters merges partial patches over the LIVE node config
 *    (the stale-spread clobber), and
 *  - model mutations are observable via Model.addChangeListener without a
 *    mounted <Layout> (the unpersisted-add defect).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { createStore, Provider } from "jotai";
import {
  broadcastInstrument,
  channelInstrumentAtoms,
  getChannelMembership,
} from "@/services/fdc3/channels";
import { Model } from "flexlayout-react";
import type { IJsonModel, ITabRenderValues, TabNode } from "flexlayout-react";

import {
  countTabs,
  createWorkspaceApi,
  renderWorkspaceTabExtras,
  createWorkspaceModel,
  detachedPanelProps,
  emptyWorkspaceJson,
  rowJson,
  tabJson,
  tabsetJson,
  tryCreateWorkspaceModel,
  widgetPropsForNode,
  workspaceJson,
} from "../flexLayoutAdapter";
import { flexLayoutFactory } from "../widgetFactory";
import { applyPreset } from "../workspacePresets";

function modelWithTab(config?: Record<string, unknown>): { model: Model; tab: TabNode } {
  const json = workspaceJson(
    rowJson(100, [tabsetJson(100, [tabJson("positions", "Positions", { id: "tab-1", params: config })])]),
  );
  const model = Model.fromJson(json);
  const tab = model.getNodeById("tab-1") as TabNode;
  return { model, tab };
}

describe("widgetPropsForNode", () => {
  it("returns a stable api object across repeated calls for the same node", () => {
    const { tab } = modelWithTab({ view: "table" });
    const first = widgetPropsForNode(tab);
    const second = widgetPropsForNode(tab);
    expect(first.api).toBe(second.api);
    expect(first.api.id).toBe("tab-1");
  });

  it("exposes the node config as params", () => {
    const { tab } = modelWithTab({ view: "heat", group: "sector" });
    expect(widgetPropsForNode(tab).params).toEqual({ view: "heat", group: "sector" });
  });

  it("merges partial updateParameters patches over the LIVE config (stale-spread regression)", () => {
    const { tab } = modelWithTab({ view: "netted", group: "none" });
    const { api } = widgetPropsForNode(tab);

    // Two sequential single-key patches — the second must not revert the first.
    api.updateParameters({ view: "detailed" });
    api.updateParameters({ group: "underlying" });

    expect(tab.getConfig()).toEqual({ view: "detailed", group: "underlying" });
  });

  it("notifies model-level change listeners without any mounted Layout", () => {
    const { model, tab } = modelWithTab({ view: "table" });
    const listener = vi.fn();
    model.addChangeListener(listener);

    widgetPropsForNode(tab).api.updateParameters({ view: "heat" });

    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("flexLayoutFactory", () => {
  it("resolves a registered component to its panel wrapper", () => {
    const { tab } = modelWithTab();
    const element = flexLayoutFactory(tab) as React.ReactElement;
    expect(element).toBeTruthy();
    expect((element.type as { displayName?: string }).displayName).toBe("Panel(positions)");
  });

  it("resolves a retired id to its canonical wrapper instead of failing the tab", () => {
    const json = workspaceJson(
      rowJson(100, [tabsetJson(100, [tabJson("mtmmonitor", "MTM", { id: "tab-r" })])]),
    );
    const model = Model.fromJson(json);
    const element = flexLayoutFactory(model.getNodeById("tab-r") as TabNode) as React.ReactElement;
    expect((element.type as { displayName?: string }).displayName).toBe("Retired(mtmmonitor→pnlmonitor)");
  });

  it("degrades an unknown component id to the widget error card, not a throw", () => {
    const json = workspaceJson(
      rowJson(100, [tabsetJson(100, [tabJson("no-such-widget", "??", { id: "tab-x" })])]),
    );
    const model = Model.fromJson(json);
    expect(() => flexLayoutFactory(model.getNodeById("tab-x") as TabNode)).not.toThrow();
  });
});

describe("createWorkspaceApi", () => {
  function makeApi(initial?: IJsonModel) {
    let model = createWorkspaceModel(initial);
    const loadModel = vi.fn((next: Model) => {
      model = next;
    });
    const api = createWorkspaceApi(() => model, loadModel);
    return { api, loadModel, getModel: () => model };
  }

  it("addPanel adds a tab to the first tabset of an empty workspace", () => {
    const { api, getModel } = makeApi(emptyWorkspaceJson());
    expect(api.panelCount()).toBe(0);

    api.addPanel({ component: "chart", title: "Chart", params: { symbol: "NIFTY" } });

    expect(api.panelCount()).toBe(1);
    expect(countTabs(getModel())).toBe(1);
    const doc = JSON.stringify(api.toJSON());
    expect(doc).toContain('"chart"');
    expect(doc).toContain('"NIFTY"');
  });

  it("loadModelJson replaces the model through the load callback", () => {
    const { api, loadModel } = makeApi(emptyWorkspaceJson());
    api.loadModelJson(
      workspaceJson(rowJson(100, [tabsetJson(100, [tabJson("watchlist", "Watchlist")])])),
    );
    expect(loadModel).toHaveBeenCalledTimes(1);
    expect(countTabs(loadModel.mock.calls[0][0] as Model)).toBe(1);
  });

  it("applyPreset loads a preset document through the api", () => {
    const { api, getModel } = makeApi(emptyWorkspaceJson());
    applyPreset(api, "market-watch");
    expect(countTabs(getModel())).toBe(4);
  });
});

describe("model document helpers", () => {
  it("tryCreateWorkspaceModel returns null for unparseable documents", () => {
    expect(tryCreateWorkspaceModel({ grid: {}, panels: {} })).toBeNull();
  });

  it("detachedPanelProps provides a no-op api with the given id", () => {
    const props = detachedPanelProps("compact-chart");
    expect(props.api.id).toBe("compact-chart");
    expect(() => props.api.updateParameters({ view: "x" })).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// Tab-chrome channel dot (Phase 2 — FDC3 channel membership)
// ---------------------------------------------------------------------------

describe("renderWorkspaceTabExtras (channel dot)", () => {
  let dotSeq = 0;

  function renderDotFor(config?: Record<string, unknown>) {
    // Unique panel id per test — membership atoms are module-keyed by id.
    const panelId = `tab-dot-${++dotSeq}`;
    const json = workspaceJson(
      rowJson(100, [tabsetJson(100, [tabJson("chart", "Chart", { id: panelId, params: config })])]),
    );
    const model = Model.fromJson(json);
    const tab = model.getNodeById(panelId) as TabNode;
    const store = createStore();
    const renderValues: ITabRenderValues = { leading: null, content: "Chart", buttons: [] };
    renderWorkspaceTabExtras(tab, renderValues);
    expect(renderValues.buttons).toHaveLength(1);
    render(<Provider store={store}>{renderValues.buttons}</Provider>);
    return { model, tab, store, panelId };
  }

  it("shows the default (red) channel for a tab with no channel config", () => {
    renderDotFor();
    expect(
      screen.getByRole("button", { name: "Link channel: Red — click to change" }),
    ).toBeInTheDocument();
  });

  it("cycles the channel on click, updating LIVE membership and persisting config", () => {
    const { tab, store, panelId } = renderDotFor({ view: "candles" });

    fireEvent.click(screen.getByRole("button", { name: /link channel/i }));

    // Live membership updated (what mounted widgets follow, hidden or not)…
    expect(getChannelMembership(store, panelId, undefined)).toBe("fdc3.channel.green");
    // …and persisted into the tab config for save/restore.
    expect((tab.getConfig() as Record<string, unknown>).channel).toBe("fdc3.channel.green");
    // Other config keys survive the channel write.
    expect((tab.getConfig() as Record<string, unknown>).view).toBe("candles");
  });

  it("cycles from yellow to unlinked (channel: none)", () => {
    const { tab, store, panelId } = renderDotFor({ channel: "fdc3.channel.yellow" });

    fireEvent.click(screen.getByRole("button", { name: /link channel/i }));

    expect(getChannelMembership(store, panelId, undefined)).toBeNull();
    expect((tab.getConfig() as Record<string, unknown>).channel).toBe("none");
  });

  it("a live widget hook follows the dot click without any re-render of the panel", () => {
    const { store, panelId } = renderDotFor({ channel: "fdc3.channel.blue" });

    // Simulate the widget side: subscribe to the membership atom the same
    // way useChannelMembership does, then broadcast on the NEW channel.
    fireEvent.click(screen.getByRole("button", { name: /link channel/i })); // blue → yellow
    expect(getChannelMembership(store, panelId, undefined)).toBe("fdc3.channel.yellow");
    broadcastInstrument(store, "fdc3.channel.yellow", { symbol: "NIFTY", exchange: "NSE_INDEX" });
    const followed = store.get(
      channelInstrumentAtoms[getChannelMembership(store, panelId, undefined)!],
    );
    expect(followed).toEqual({ symbol: "NIFTY", exchange: "NSE_INDEX" });
  });
});
