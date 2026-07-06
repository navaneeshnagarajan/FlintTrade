import { describe, it, expect, beforeEach } from "vitest";
import { useValueVisibilityStore } from "../valueVisibilityStore";

describe("valueVisibilityStore", () => {
  beforeEach(() => {
    useValueVisibilityStore.setState({ hidden: false });
  });

  it("defaults to visible", () => {
    expect(useValueVisibilityStore.getState().hidden).toBe(false);
  });

  it("toggle flips visibility", () => {
    useValueVisibilityStore.getState().toggle();
    expect(useValueVisibilityStore.getState().hidden).toBe(true);
    useValueVisibilityStore.getState().toggle();
    expect(useValueVisibilityStore.getState().hidden).toBe(false);
  });

  it("setHidden sets the flag explicitly", () => {
    useValueVisibilityStore.getState().setHidden(true);
    expect(useValueVisibilityStore.getState().hidden).toBe(true);
  });
});
