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
