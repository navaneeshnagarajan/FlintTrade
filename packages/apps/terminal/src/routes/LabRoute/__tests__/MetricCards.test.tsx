/**
 * MetricCards.test.tsx
 *
 * Pins FT-LAB-002: Lab headline metrics must show one formatted value.
 * AnimatedCounter used to paint a leftover count-up `0.00` beside an
 * sr-only final figure — Sharpe read as "0.00 1.84".
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom";

vi.mock("@/components/ui/GlassCard", () => ({
  GlassCard: ({ children, ...props }: Record<string, unknown>) => (
    <div {...props}>{children as React.ReactNode}</div>
  ),
}));

import { AnimatedMetricCard } from "../MetricCards";

function metricCardText(label: string): string {
  const labelEl = screen.getByText(label);
  const card = labelEl.parentElement;
  expect(card).not.toBeNull();
  return (card?.textContent ?? "").replace(/\s+/g, " ").trim();
}

describe("AnimatedMetricCard", () => {
  it("shows a single Sharpe value without a leftover 0.00", () => {
    render(
      <AnimatedMetricCard
        label="Sharpe Ratio"
        numericValue={1.84}
        displayValue="1.84"
        positive
        formatter={(v) => v.toFixed(2)}
      />,
    );

    const text = metricCardText("Sharpe Ratio");
    expect(text).toMatch(/^Sharpe Ratio\s*1\.84$/);
    expect(text).not.toContain("0.00");
  });

  it("shows a single win-rate percentage without a leftover 0.00%", () => {
    render(
      <AnimatedMetricCard
        label="Win Rate"
        numericValue={75}
        displayValue="75.00%"
        positive
        formatter={(v) => `${v.toFixed(2)}%`}
      />,
    );

    const text = metricCardText("Win Rate");
    expect(text).toMatch(/^Win Rate\s*75\.00%$/);
    expect(text).not.toContain("0.00%");
  });

  it("shows a single profit-factor value without a leftover 0.00", () => {
    render(
      <AnimatedMetricCard
        label="Profit Factor"
        numericValue={8.43}
        displayValue="8.43"
        positive
        formatter={(v) => v.toFixed(2)}
      />,
    );

    const text = metricCardText("Profit Factor");
    expect(text).toMatch(/^Profit Factor\s*8\.43$/);
    expect(text).not.toContain("0.00");
  });
});
