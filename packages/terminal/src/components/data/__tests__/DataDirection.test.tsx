import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataDirection } from "../DataDirection";

describe("DataDirection", () => {
  it("positive value shows green styling (bullish text class)", () => {
    const { container } = render(<DataDirection value={1234.56} />);
    expect(container.firstChild).toHaveClass("text-bullish-text");
  });

  it("positive value shows up arrow icon", () => {
    render(<DataDirection value={1234.56} />);
    // TrendingUp icon is rendered with aria-hidden; check via svg presence + container
    const { container } = render(<DataDirection value={1234.56} />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
  });

  it("negative value shows red styling (bearish text class)", () => {
    const { container } = render(<DataDirection value={-500} />);
    expect(container.firstChild).toHaveClass("text-bearish-text");
  });

  it("negative value shows down arrow icon", () => {
    const { container } = render(<DataDirection value={-500} />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
  });

  it("zero value shows neutral styling", () => {
    const { container } = render(<DataDirection value={0} />);
    expect(container.firstChild).toHaveClass("text-text-secondary");
  });

  it("null value shows em-dash", () => {
    render(<DataDirection value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("aria-label includes '+₹1,234.56 profit' for positive currency", () => {
    render(<DataDirection value={1234.56} format="currency" />);
    const el = screen.getByRole("text");
    expect(el.getAttribute("aria-label")).toMatch(/\+.*1,234\.56.*profit/i);
  });

  it("aria-label includes '-₹1,234.56 loss' for negative currency", () => {
    render(<DataDirection value={-1234.56} format="currency" />);
    const el = screen.getByRole("text");
    expect(el.getAttribute("aria-label")).toMatch(/-.*1,234\.56.*loss/i);
  });

  it("renders background tint for positive (bg-bullish-bg class)", () => {
    const { container } = render(<DataDirection value={500} />);
    expect(container.firstChild).toHaveClass("bg-bullish-bg");
  });

  it("renders background tint for negative (bg-bearish-bg class)", () => {
    const { container } = render(<DataDirection value={-500} />);
    expect(container.firstChild).toHaveClass("bg-bearish-bg");
  });

  it("renders sign (+) for positive value", () => {
    render(<DataDirection value={100} />);
    expect(screen.getByText(/\+/)).toBeInTheDocument();
  });

  it("renders sign (-) for negative value", () => {
    render(<DataDirection value={-100} />);
    expect(screen.getByText(/-/)).toBeInTheDocument();
  });

  it("format='percent' shows percentage", () => {
    render(<DataDirection value={2.5} format="percent" />);
    expect(screen.getByText(/%/)).toBeInTheDocument();
  });

  it("format='currency' shows ₹ prefix", () => {
    render(<DataDirection value={1000} format="currency" />);
    expect(screen.getByText(/₹/)).toBeInTheDocument();
  });
});
