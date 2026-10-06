import { render, screen, waitFor } from "@testing-library/react";
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

  it("mounts the next tab immediately and completes its real fade", async () => {
    vi.spyOn(motionConfig, "prefersReducedMotion").mockReturnValue(false);
    const { rerender } = render(
      <TabTransition tabKey="overview" className="h-full min-h-0 overflow-hidden">
        <span>Overview panel</span>
      </TabTransition>,
    );
    const previousWrapper = screen.getByText("Overview panel").parentElement;

    rerender(
      <TabTransition tabKey="details" className="h-full min-h-0 overflow-hidden">
        <span>Details panel</span>
      </TabTransition>,
    );

    expect(screen.queryByText("Overview panel")).not.toBeInTheDocument();
    const wrapper = screen.getByText("Details panel").parentElement;
    expect(wrapper).not.toBe(previousWrapper);
    expect(previousWrapper).not.toBeInTheDocument();
    expect(wrapper).toHaveClass("h-full", "min-h-0", "overflow-hidden");
    expect(wrapper).toHaveStyle({ opacity: "0" });
    await waitFor(() => expect(wrapper).toHaveStyle({ opacity: "1" }));
  });
});
