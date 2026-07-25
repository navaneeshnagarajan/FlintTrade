/**
 * CurrencyConverterWidget.test.tsx
 *
 * Tests: render, currency swap, conversion display, sparkline.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/stores/skillStore", () => ({
  useSkillStore: () => vi.fn(),
}));

import CurrencyConverterWidget from "../CurrencyConverterWidget";

describe("CurrencyConverterWidget", () => {
  it("renders the widget header", () => {
    render(<CurrencyConverterWidget />);
    expect(screen.getByText("Currency Converter")).toBeTruthy();
  });

  it("renders from and to currency selectors", () => {
    render(<CurrencyConverterWidget />);
    expect(screen.getByLabelText("From currency")).toBeTruthy();
    expect(screen.getByLabelText("To currency")).toBeTruthy();
  });

  it("renders amount input with default value", () => {
    render(<CurrencyConverterWidget />);
    const input = screen.getByLabelText("Amount to convert") as HTMLInputElement;
    expect(input.value).toBe("1");
  });

  it("renders the swap button", () => {
    render(<CurrencyConverterWidget />);
    expect(screen.getByLabelText("Swap currencies")).toBeTruthy();
  });

  it("states that no rate history exists instead of plotting a fabricated one", () => {
    // This slot used to render a sin/cos curve labelled "30-day trend" with a
    // signed percentage change. The conversion table is a hardcoded constant,
    // so no such series exists and none may be implied.
    render(<CurrencyConverterWidget />);

    expect(screen.getByText(/no historical series/i)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /rate history sparkline/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/30-day trend/i)).not.toBeInTheDocument();
  });

  it("shows exchange rate info section", () => {
    render(<CurrencyConverterWidget />);
    expect(screen.getByText("Exchange Rate")).toBeTruthy();
    expect(screen.getByText("Inverse")).toBeTruthy();
  });

  it("shows disclaimer text", () => {
    render(<CurrencyConverterWidget />);
    expect(screen.getByText(/indicative rates only/i)).toBeTruthy();
  });
});
