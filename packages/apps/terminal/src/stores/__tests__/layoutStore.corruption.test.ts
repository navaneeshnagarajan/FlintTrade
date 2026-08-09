import { describe, it, expect } from "vitest";
import { classifySerializedLayout } from "../layoutStore";

describe("classifySerializedLayout — family discriminator (RED→GREEN for mixed/hybrid)", () => {
  // Helper to make tests readable
  const cases = [
    {
      name: "A1: grid+panels+__pendingPreset (setup+dock mixed)",
      input: { __pendingPreset: "trading-desk", grid: {}, panels: {} },
      expected: "corrupt",
    },
    {
      name: "A2: grid+panels+global+borders+layout (dock+flex mixed)",
      input: { grid: {}, panels: {}, global: {}, borders: [], layout: {} },
      expected: "corrupt",
    },
    {
      name: "A3: dual valid dockview markers + valid flex document",
      input: {
        grid: {},
        panels: {},
        layout: { type: "row", children: [] },
        global: {},
        borders: [],
      },
      expected: "corrupt",
    },
    {
      name: "pure dockview",
      input: { grid: {}, panels: {} },
      expected: "dockview",
    },
    {
      name: "pure setup",
      input: { __pendingPreset: "trading-desk" },
      expected: "setup",
    },
    {
      name: "empty",
      input: {},
      expected: "empty",
    },
    {
      name: "undefined",
      input: undefined,
      expected: "empty",
    },
    {
      name: "both aliases subLayouts+popouts",
      input: { subLayouts: {}, popouts: {} },
      expected: "corrupt",
    },
    {
      name: "valid flex with layout",
      input: { layout: { type: "row", children: [] }, global: {}, borders: [] },
      expected: "flexlayout",
    },
    {
      name: "flex with subLayouts only",
      input: { subLayouts: { root: {} }, global: {}, borders: [] },
      expected: "flexlayout",
    },
    {
      name: "flex with popouts only (deprecated alias)",
      input: { popouts: {}, global: {}, borders: [] },
      expected: "flexlayout",
    },
    {
      name: "both aliases + grid/panels",
      input: { grid: {}, panels: {}, subLayouts: {}, popouts: {} },
      expected: "corrupt",
    },
  ];

  for (const c of cases) {
    it(c.name, () => {
      const result = classifySerializedLayout(c.input as any);
      expect(result).toBe(c.expected);
    });
  }
});

describe("classifySerializedLayout — additional boundary cases", () => {
  it("malformed nested (predecessor style) → corrupt", () => {
    const bad = { layout: { type: "row", children: [ { id: "dup" }, { id: "dup" } ] } };
    expect(classifySerializedLayout(bad as any)).toBe("corrupt");
  });

  it("setup with extra key → corrupt", () => {
    const badSetup = { __pendingPreset: "x", foo: "bar" };
    expect(classifySerializedLayout(badSetup as any)).toBe("corrupt");
  });
});
