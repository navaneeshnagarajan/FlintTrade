import { describe, it, expect } from "vitest";
import { DockviewReact } from "dockview-react";

describe("Dockview v5 + React 19", () => {
  it("DockviewReact component is importable", () => {
    expect(DockviewReact).toBeDefined();
    // Dockview v5 exports DockviewReact as a memo/forwardRef wrapper (object), not a plain function
    expect(typeof DockviewReact).toMatch(/^(function|object)$/);
  });
});
