import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SectionHeader } from "../SectionHeader";

describe("SectionHeader", () => {
  it("renders title as h2 by default", () => {
    render(<SectionHeader title="My Section" />);
    const heading = screen.getByRole("heading", { name: "My Section" });
    expect(heading.tagName).toBe("H2");
  });

  it("renders title as h3 when as='h3'", () => {
    render(<SectionHeader title="Sub Section" as="h3" />);
    const heading = screen.getByRole("heading", { name: "Sub Section" });
    expect(heading.tagName).toBe("H3");
  });

  it("renders title as h4 when as='h4'", () => {
    render(<SectionHeader title="Deep Section" as="h4" />);
    const heading = screen.getByRole("heading", { name: "Deep Section" });
    expect(heading.tagName).toBe("H4");
  });

  it("renders optional description when provided", () => {
    render(
      <SectionHeader
        title="My Section"
        description="This is a helpful description"
      />
    );
    expect(
      screen.getByText("This is a helpful description")
    ).toBeInTheDocument();
  });

  it("does not render description paragraph when omitted", () => {
    const { container } = render(<SectionHeader title="My Section" />);
    expect(container.querySelector("p")).toBeNull();
  });

  it("renders optional action slot when provided", () => {
    render(
      <SectionHeader
        title="My Section"
        action={<button data-testid="action-btn">View All</button>}
      />
    );
    expect(screen.getByTestId("action-btn")).toBeInTheDocument();
  });

  it("does not render action slot when omitted", () => {
    render(<SectionHeader title="My Section" />);
    // No button or extra element in DOM
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("heading has correct typography classes", () => {
    render(<SectionHeader title="Styled Title" />);
    const heading = screen.getByRole("heading", { name: "Styled Title" });
    expect(heading.className).toContain("text-lg");
    expect(heading.className).toContain("font-semibold");
  });

  it("action is rendered to the right (flex row layout on root)", () => {
    render(
      <SectionHeader
        title="My Section"
        action={<button data-testid="action-btn">Go</button>}
      />
    );
    const root = screen
      .getByRole("heading", { name: "My Section" })
      .closest("div")?.parentElement as HTMLElement;
    expect(root.className).toContain("flex");
    expect(root.className).toContain("justify-between");
  });

  it("renders title text content correctly", () => {
    render(<SectionHeader title="Portfolio Overview" />);
    expect(
      screen.getByRole("heading", { name: "Portfolio Overview" })
    ).toBeInTheDocument();
  });

  it("action wrapper has shrink-0 to prevent shrinking", () => {
    render(
      <SectionHeader
        title="My Section"
        action={<button data-testid="action-btn">Act</button>}
      />
    );
    const actionBtn = screen.getByTestId("action-btn");
    // The action is wrapped in a shrink-0 div
    expect(actionBtn.parentElement?.className).toContain("shrink-0");
  });
});
