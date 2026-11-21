import { describe, expect, it } from "vitest";
import { Model, type TabNode } from "flexlayout-react";
import { APPS, widgetAllowed } from "../appCatalog";
import { APP_PRESETS, buildAppPreset, readAppLayouts, saveAppLayout, APP_LAYOUT_NAMESPACE, validateAppLayout } from "../appLayouts";

it("keeps presentation layouts per app, ignores old layouts and never deletes other records", () => {
  localStorage.clear();
  localStorage.setItem("flinttrade:layouts", "old-composition");
  localStorage.setItem("journal:record", "retained");
  const terminal = Model.fromJson(buildAppPreset("terminal", "overview")).toJson();
  const testing = buildAppPreset("testing", "default");
  saveAppLayout("terminal", "My overview", terminal);
  saveAppLayout("testing", "Research", testing);
  expect(readAppLayouts("terminal")["My overview"]).toEqual(terminal);
  expect(readAppLayouts("testing")["My overview"]).toBeUndefined();
  expect(localStorage.getItem("flinttrade:layouts")).toBe("old-composition");
  expect(localStorage.getItem("journal:record")).toBe("retained");
  expect(APP_LAYOUT_NAMESPACE).not.toBe("flinttrade:layouts");
});
describe("purpose-safe presets", () => {
  it.each([
    ["scalper-zone", ["scalper", "positions", "orders", "optionchain"]],
    ["volatility-trading", ["chart", "straddle", "oichart", "positions", "orders", "optionchain", "watchlist"]],
    ["classic", ["chart", "positions", "orders", "optionchain", "watchlist"]],
    ["watchlist-driven", ["watchlist", "chart", "positions", "orders"]],
    ["market-overview", ["chart", "straddle", "oichart"]],
  ] as const)("builds the captured %s template through the canonical owner", (id, expected) => {
    const json = buildAppPreset("terminal", id);
    expect(validateAppLayout("terminal", json)).toBe(true);
    const components: string[] = [];
    Model.fromJson(json).visitNodes(node => { if (node.getType() === "tab") components.push((node as TabNode).getComponent()!); });
    expect(components).toEqual(expected);
  });

  it("starts a fresh Terminal with the captured watchlist-left geometry and retains the overview tab", () => {
    const json = buildAppPreset("terminal", "default");
    expect(json.layout.children).toMatchObject([
      { type: "tabset", weight: 28, children: [{ component: "watchlist" }, { component: "overview:WelcomeCard" }] },
      { type: "tabset", weight: 72, active: true, selected: 0, children: [
        { component: "chart", config: { channel: "none" } },
        { component: "positions" }, { component: "orders" },
      ] },
    ]);
    expect(validateAppLayout("terminal", json)).toBe(true);
  });
  it("offers the captured watchlist-left geometry as an explicit repeatable preset", () => {
    expect(APP_PRESETS.terminal).toContainEqual({ id: "watchlist-driven", name: "Watchlist driven", template: true });
    const json = buildAppPreset("terminal", "watchlist-driven");
    expect(json.layout.children).toMatchObject([
      { type: "tabset", weight: 28, children: [{ component: "watchlist" }] },
      { type: "tabset", weight: 72, active: true, children: [{ component: "chart" }, { component: "positions" }, { component: "orders" }] },
    ]);
    expect(validateAppLayout("terminal", json)).toBe(true);
    const model = Model.fromJson(json);
    expect(model.getActiveTabset()?.getSelectedNode()?.getName()).toBe("Chart");
  });
  it("does not rewrite a saved Current or named layout when building the fresh default", () => {
    localStorage.clear();
    const saved = buildAppPreset("terminal", "overview");
    saveAppLayout("terminal", "Current", saved);
    saveAppLayout("terminal", "My overview", saved);
    const before = localStorage.getItem(`${APP_LAYOUT_NAMESPACE}:terminal`);
    buildAppPreset("terminal", "default");
    expect(localStorage.getItem(`${APP_LAYOUT_NAMESPACE}:terminal`)).toBe(before);
    expect(readAppLayouts("terminal").Current).toEqual(saved);
    expect(readAppLayouts("terminal")["My overview"]).toEqual(saved);
  });
  it("offers Trader and Option Scalper as layouts, never personas", () => {
    expect(APP_PRESETS.terminal.map(preset => preset.name)).toEqual(expect.arrayContaining(["Trader", "Option Scalper"]));
    expect(validateAppLayout("terminal", buildAppPreset("terminal", "trader"))).toBe(true);
  });
  for (const app of APPS) it(`${app.name} mounts only compatible widgets`, () => {
    const json = buildAppPreset(app.id, "default");
    expect(validateAppLayout(app.id, json)).toBe(true);
    const model = Model.fromJson(json);
    const components: string[] = [];
    model.visitNodes(n => { if (n.getType() === "tab") components.push((n as TabNode).getComponent()!); });
    expect(components.length).toBeGreaterThan(0);
    expect(components.every(id => widgetAllowed(app.id, id))).toBe(true);
  });
  it("rejects a Live-capable order panel and saved authority in Testing", () => {
    expect(validateAppLayout("testing", buildAppPreset("terminal", "overview"))).toBe(false);
    const json = buildAppPreset("testing", "default");
    json.layout.children![0] = { type: "tabset", children: [{ type: "tab", component: "orderpad", name: "Unsafe", config: { accountId: "live-A", grant: "armed" } }] };
    expect(validateAppLayout("testing", json)).toBe(false);
  });
});
