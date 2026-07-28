import { describe, it, expect } from "vitest";
import { Layout, Model } from "flexlayout-react";
import { emptyWorkspaceJson } from "@/layout/flexLayoutAdapter";

describe("FlexLayout 0.10 + React 19", () => {
  it("Layout component is importable", () => {
    expect(Layout).toBeDefined();
    expect(typeof Layout).toMatch(/^(function|object)$/);
  });

  it("builds a Model from the empty workspace document", () => {
    const model = Model.fromJson(emptyWorkspaceJson());
    expect(model.getRootRow()).toBeDefined();
    // Round-trips through toJson without losing the root row.
    expect(model.toJson().layout.type).toBe("row");
  });
});
