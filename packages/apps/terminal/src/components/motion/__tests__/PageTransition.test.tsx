import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { motionConfig } from "@/lib/motion";
import PageTransition from "../PageTransition";

describe("PageTransition", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("fills the Trade route body so the desk can flex", () => {
    vi.spyOn(motionConfig, "prefersReducedMotion").mockReturnValue(false);

    render(
      <PageTransition locationKey="/trade">
        <div data-testid="trade-desk">Trade desk</div>
      </PageTransition>,
    );

    const fill = screen.getByTestId("route-body-fill");
    expect(fill.className).toMatch(/flex-1/);
    expect(fill.className).toMatch(/min-h-0/);
    expect(fill.className).toMatch(/h-full/);
    expect(screen.getByTestId("trade-desk")).toBeInTheDocument();
  });
});
