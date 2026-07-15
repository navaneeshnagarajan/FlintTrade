import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { motionConfig } from "@/lib/motion";
import TabTransition from "../TabTransition";

describe("TabTransition", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves layout classes when reduced motion is enabled", () => {
    vi.spyOn(motionConfig, "prefersReducedMotion").mockReturnValue(true);

    render(
      <TabTransition tabKey="flows" className="h-full min-h-0 overflow-hidden">
        <span>Flow canvas</span>
      </TabTransition>
    );

    expect(screen.getByText("Flow canvas").parentElement).toHaveClass(
      "h-full",
      "min-h-0",
      "overflow-hidden"
    );
  });
});
