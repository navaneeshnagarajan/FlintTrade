import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import SpreadViewWidget from "../SpreadViewWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  mockUseBrokerConnected.mockReturnValue(false);
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("SpreadViewWidget", () => {
  it("renders widget title", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByText("Spread View")).toBeTruthy();
  });

  it("shows Sample badge when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<SpreadViewWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("hides Sample badge when connected", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    render(<SpreadViewWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
  });

  it("renders spread type selector defaulting to Bull Call", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByText("Bull Call")).toBeTruthy();
  });

  it("renders all metric tiles", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByText("Max Profit")).toBeTruthy();
    expect(screen.getByText("Max Loss")).toBeTruthy();
    expect(screen.getByText("Breakeven")).toBeTruthy();
    // "Net Premium" appears in both the input label and the metric tile span
    expect(screen.getAllByText("Net Premium").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Margin Req.")).toBeTruthy();
  });

  it("renders payoff diagram SVG", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByRole("img", { name: /spread payoff diagram/i })).toBeTruthy();
  });

  it("renders payoff through the shared Flint payoff chart primitive", () => {
    render(<SpreadViewWidget />);
    const chart = screen.getByRole("img", { name: /spread payoff diagram/i });
    expect(chart).toHaveAttribute("data-flint-chart", "payoff");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-zone='profit']")).toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-zone='loss']")).toBeInTheDocument();
  });

  it("renders execute button disabled when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<SpreadViewWidget />);
    const btn = screen.getByLabelText(/Execute.*spread/i);
    expect(btn).toBeDefined();
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows broker connect message when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<SpreadViewWidget />);
    expect(screen.getByText("Connect broker to execute")).toBeTruthy();
  });

  it("keeps execution disabled when connected until basket routing is wired", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    render(<SpreadViewWidget />);
    const btn = screen.getByLabelText(/Execute.*spread unavailable/i);
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Basket execution not wired yet")).toBeTruthy();
  });

  it("renders number inputs for strikes and premium", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByLabelText("Long Strike")).toBeTruthy();
    expect(screen.getByLabelText("Short Strike")).toBeTruthy();
    expect(screen.getByLabelText("Net Premium")).toBeTruthy();
  });

  it("opens spread type dropdown and shows all 4 types", () => {
    render(<SpreadViewWidget />);
    const btn = screen.getByLabelText("Select spread type");
    fireEvent.click(btn);
    expect(screen.getByRole("option", { name: "Bear Put" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Bull Put" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Bear Call" })).toBeTruthy();
  });
});
