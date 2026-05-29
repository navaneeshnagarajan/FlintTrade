import { describe, expect, it, vi } from "vitest";

import { renderReactRoot } from "../reactRoot";

describe("renderReactRoot", () => {
  it("reuses an existing root for the same container", () => {
    const render = vi.fn();
    const createRoot = vi.fn(() => ({ render }));
    const container = document.createElement("div");

    renderReactRoot(container, <div>first</div>, createRoot);
    renderReactRoot(container, <div>second</div>, createRoot);

    expect(createRoot).toHaveBeenCalledTimes(1);
    expect(render).toHaveBeenCalledTimes(2);
  });
});
