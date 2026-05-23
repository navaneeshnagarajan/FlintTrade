/**
 * BentoCard.test.tsx — Unit tests for BentoCard size variants.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { BentoCard } from "../BentoCard";

// Mock framer-motion to avoid animation issues in JSDOM
vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      style,
      className,
      "data-testid": testId,
      "data-bento-size": size,
      "aria-label": label,
      whileHover: _wh,
      whileTap: _wt,
      initial: _i,
      animate: _a,
      transition: _t,
      ...rest
    }: Record<string, unknown>) => (
      <div
        style={style as React.CSSProperties}
        className={className as string}
        data-testid={testId as string}
        data-bento-size={size as string}
        aria-label={label as string}
        {...rest}
      >
        {children as React.ReactNode}
      </div>
    ),
  },
}));

describe("BentoCard", () => {
  it("renders children", () => {
    render(
      <BentoCard>
        <span data-testid="inner">content</span>
      </BentoCard>
    );
    expect(screen.getByTestId("inner")).toBeInTheDocument();
  });

  it("applies default size (no grid span)", () => {
    render(<BentoCard data-testid="card">content</BentoCard>);
    const card = screen.getByTestId("card");
    expect(card.getAttribute("data-bento-size")).toBe("default");
    // Default has no gridColumn override
    expect((card as HTMLElement).style.gridColumn).toBe("");
  });

  it("applies wide size (grid-column span 2)", () => {
    render(<BentoCard size="wide" data-testid="card">content</BentoCard>);
    const card = screen.getByTestId("card");
    expect(card.getAttribute("data-bento-size")).toBe("wide");
    expect((card as HTMLElement).style.gridColumn).toBe("span 2");
  });

  it("applies tall size (grid-row span 2)", () => {
    render(<BentoCard size="tall" data-testid="card">content</BentoCard>);
    const card = screen.getByTestId("card");
    expect(card.getAttribute("data-bento-size")).toBe("tall");
    expect((card as HTMLElement).style.gridRow).toBe("span 2");
  });

  it("applies hero size (column+row span 2)", () => {
    render(<BentoCard size="hero" data-testid="card">content</BentoCard>);
    const card = screen.getByTestId("card");
    expect(card.getAttribute("data-bento-size")).toBe("hero");
    expect((card as HTMLElement).style.gridColumn).toBe("span 2");
    expect((card as HTMLElement).style.gridRow).toBe("span 2");
  });

  it("renders aria-label when label prop is provided", () => {
    render(
      <BentoCard label="Open Positions" data-testid="labelled-card">
        content
      </BentoCard>
    );
    const card = screen.getByTestId("labelled-card");
    expect(card).toHaveAttribute("aria-label", "Open Positions");
  });

  it("applies extra className", () => {
    render(
      <BentoCard data-testid="card" className="my-custom">
        content
      </BentoCard>
    );
    expect(screen.getByTestId("card").className).toContain("my-custom");
  });
});
