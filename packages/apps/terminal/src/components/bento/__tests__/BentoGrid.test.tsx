/**
 * BentoGrid.test.tsx — Unit tests for the BentoGrid layout engine.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { BentoGrid, BentoGridContainer } from "../BentoGrid";

describe("BentoGrid", () => {
  it("renders children", () => {
    render(
      <BentoGrid>
        <div data-testid="child-1">Child 1</div>
        <div data-testid="child-2">Child 2</div>
      </BentoGrid>
    );

    expect(screen.getByTestId("child-1")).toBeInTheDocument();
    expect(screen.getByTestId("child-2")).toBeInTheDocument();
  });

  it("applies data-testid attribute", () => {
    render(
      <BentoGrid data-testid="bento-grid-root">
        <div>child</div>
      </BentoGrid>
    );
    expect(screen.getByTestId("bento-grid-root")).toBeInTheDocument();
  });

  it("applies bento-grid CSS class", () => {
    render(
      <BentoGrid data-testid="grid">
        <div>child</div>
      </BentoGrid>
    );
    const grid = screen.getByTestId("grid");
    expect(grid.className).toContain("bento-grid");
  });

  it("merges extra className", () => {
    render(
      <BentoGrid data-testid="grid" className="extra-class">
        <div>child</div>
      </BentoGrid>
    );
    const grid = screen.getByTestId("grid");
    expect(grid.className).toContain("extra-class");
  });

  it("renders multiple children", () => {
    const COUNT = 6;
    render(
      <BentoGrid>
        {Array.from({ length: COUNT }, (_, i) => (
          <div key={i} data-testid={`item-${i}`}>
            {i}
          </div>
        ))}
      </BentoGrid>
    );
    for (let i = 0; i < COUNT; i++) {
      expect(screen.getByTestId(`item-${i}`)).toBeInTheDocument();
    }
  });
});

describe("BentoGridContainer", () => {
  it("renders children", () => {
    render(
      <BentoGridContainer>
        <div data-testid="container-child">content</div>
      </BentoGridContainer>
    );
    expect(screen.getByTestId("container-child")).toBeInTheDocument();
  });

  it("applies bento-scroll-container class", () => {
    const { container } = render(
      <BentoGridContainer>
        <div>content</div>
      </BentoGridContainer>
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("bento-scroll-container");
  });
});
