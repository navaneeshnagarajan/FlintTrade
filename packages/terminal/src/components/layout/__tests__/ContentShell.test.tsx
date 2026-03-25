import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ContentShell } from "../ContentShell";

describe("ContentShell", () => {
  it("renders children inside a centered container", () => {
    render(<ContentShell>Hello</ContentShell>);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("applies max-w-6xl by default", () => {
    const { container } = render(<ContentShell>Content</ContentShell>);
    const shell = container.firstChild as HTMLElement;
    expect(shell.className).toContain("max-w-6xl");
    expect(shell.className).toContain("mx-auto");
  });

  it("renders hero slot above content", () => {
    render(
      <ContentShell hero={<div data-testid="hero">Hero</div>}>
        <div data-testid="content">Content</div>
      </ContentShell>
    );
    const hero = screen.getByTestId("hero");
    const content = screen.getByTestId("content");
    expect(hero).toBeInTheDocument();
    expect(content).toBeInTheDocument();
    // Hero should come before content in DOM
    expect(
      hero.compareDocumentPosition(content) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("accepts maxWidth prop for narrow layouts", () => {
    const { container } = render(
      <ContentShell maxWidth="sm">Narrow</ContentShell>
    );
    const shell = container.firstChild as HTMLElement;
    expect(shell.className).toContain("max-w-sm");
  });

  it("has correct padding responsive classes", () => {
    const { container } = render(<ContentShell>Test</ContentShell>);
    const shell = container.firstChild as HTMLElement;
    expect(shell.className).toContain("px-4");
  });

  it("does not render hero slot when hero prop is omitted", () => {
    render(<ContentShell>Only children</ContentShell>);
    // No hero wrapper should be in the DOM at all
    const { container } = render(<ContentShell>Only children</ContentShell>);
    const heroWrapper = container.querySelector("[data-hero]");
    expect(heroWrapper).toBeNull();
  });

  it("applies custom className to root element", () => {
    const { container } = render(
      <ContentShell className="my-custom-class">Test</ContentShell>
    );
    const shell = container.firstChild as HTMLElement;
    expect(shell.className).toContain("my-custom-class");
  });

  it("wraps children in a space-y container", () => {
    render(
      <ContentShell>
        <div data-testid="child-a">A</div>
        <div data-testid="child-b">B</div>
      </ContentShell>
    );
    const childA = screen.getByTestId("child-a");
    const childB = screen.getByTestId("child-b");
    // Both children are in DOM
    expect(childA).toBeInTheDocument();
    expect(childB).toBeInTheDocument();
    // Children share a parent wrapper
    expect(childA.parentElement).toBe(childB.parentElement);
    expect(childA.parentElement?.className).toContain("space-y");
  });
});
