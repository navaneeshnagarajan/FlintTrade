import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataNumber } from "../DataNumber";

describe("DataNumber", () => {
  it("renders value as formatted number", () => {
    render(<DataNumber value={1234} />);
    expect(screen.getByText(/1,234/)).toBeInTheDocument();
  });

  it("hero tier uses correct font size class", () => {
    const { container } = render(<DataNumber value={42} tier="hero" />);
    expect(container.firstChild).toHaveClass("text-4xl");
  });

  it("primary tier uses correct font size class", () => {
    const { container } = render(<DataNumber value={42} tier="primary" />);
    expect(container.firstChild).toHaveClass("text-xl");
  });

  it("cell tier uses correct font size class", () => {
    const { container } = render(<DataNumber value={42} tier="cell" />);
    expect(container.firstChild).toHaveClass("text-[13px]");
  });

  it("applies JetBrains Mono font", () => {
    const { container } = render(<DataNumber value={42} />);
    expect(container.firstChild).toHaveClass("font-mono");
  });

  it("uses tabular-nums font feature", () => {
    const { container } = render(<DataNumber value={42} />);
    expect(container.firstChild).toHaveClass("tabular-nums");
  });

  it("handles null value by showing em-dash", () => {
    render(<DataNumber value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("handles undefined value by showing em-dash", () => {
    render(<DataNumber value={undefined} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("formats with Indian locale (1,23,456)", () => {
    render(<DataNumber value={123456} />);
    expect(screen.getByText(/1,23,456/)).toBeInTheDocument();
  });

  it("accepts prefix (₹)", () => {
    render(<DataNumber value={500} prefix="₹" />);
    expect(screen.getByText(/₹/)).toBeInTheDocument();
  });

  it("accepts suffix (%)", () => {
    render(<DataNumber value={12.5} suffix="%" />);
    expect(screen.getByText(/%/)).toBeInTheDocument();
  });

  it("aria-label includes the formatted value", () => {
    render(<DataNumber value={1234} />);
    const el = screen.getByRole("text");
    expect(el.getAttribute("aria-label")).toMatch(/1,234/);
  });
});
