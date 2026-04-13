import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// Stub lucide-react to avoid heavy icon tree-shaking in JSDOM/CI
vi.mock("lucide-react", () => {
  const Stub = ({ children, ...p }: Record<string, unknown>) => <span {...p}>{children as React.ReactNode}</span>;
  return {
    Lightbulb: Stub,
    Plus: Stub,
    X: Stub,
    Check: Stub,
    ChevronDown: Stub,
    ChevronUp: Stub,
    Tag: Stub,
  };
});

// Stub Button and Input to plain HTML to reduce Radix import overhead in JSDOM
vi.mock("@/components/ui/button", () => ({
  Button: ({ children, onClick, type, disabled, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { children?: React.ReactNode }) => (
    <button type={type ?? "button"} onClick={onClick} disabled={disabled} {...rest}>{children}</button>
  ),
}));

vi.mock("@/components/ui/input", () => ({
  Input: ({ id, value, onChange, placeholder, "aria-label": ariaLabel, ...rest }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input id={id} value={value} onChange={onChange} placeholder={placeholder} aria-label={ariaLabel} {...rest} />
  ),
}));

vi.mock("@/components/ui/textarea", () => ({
  Textarea: ({ id, value, onChange, placeholder, "aria-label": ariaLabel, ...rest }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea id={id} value={value} onChange={onChange} placeholder={placeholder} aria-label={ariaLabel} {...rest} />
  ),
}));

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  localStorage.clear();
});

import TradeIdeaWidget from "../TradeIdeaWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TradeIdeaWidget", () => {
  it("renders widget title", () => {
    render(<TradeIdeaWidget />);
    expect(screen.getByText("Trade Ideas")).toBeTruthy();
  });

  it("shows zero count badge initially", () => {
    render(<TradeIdeaWidget />);
    expect(screen.getByText("0")).toBeTruthy();
  });

  it("renders New button", () => {
    render(<TradeIdeaWidget />);
    expect(screen.getByLabelText("Add new trade idea")).toBeTruthy();
  });

  it("clicking New button shows the add form", () => {
    render(<TradeIdeaWidget />);
    fireEvent.click(screen.getByLabelText("Add new trade idea"));
    expect(screen.getByLabelText("Add trade idea form")).toBeTruthy();
  });

  it("Cancel button hides the form", () => {
    render(<TradeIdeaWidget />);
    fireEvent.click(screen.getByLabelText("Add new trade idea"));
    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByLabelText("Add trade idea form")).toBeNull();
  });

  it("All filter tab shows correct initial count", () => {
    render(<TradeIdeaWidget />);
    expect(screen.getByText("All (0)")).toBeTruthy();
  });

  it("empty state message shown when no ideas", () => {
    render(<TradeIdeaWidget />);
    expect(screen.getByText("No trade ideas yet")).toBeTruthy();
  });

  it("filter tablist has correct aria-label", () => {
    render(<TradeIdeaWidget />);
    expect(screen.getByRole("tablist", { name: "Filter by status" })).toBeTruthy();
  });

  it("widget aria-label is present", () => {
    render(<TradeIdeaWidget />);
    expect(screen.getByLabelText("Trade Idea widget")).toBeTruthy();
  });

  it("saves idea and shows count = 1", () => {
    render(<TradeIdeaWidget />);
    fireEvent.click(screen.getByLabelText("Add new trade idea"));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "INFY" } });
    fireEvent.click(screen.getByText("Save Idea"));
    expect(screen.getByText("1")).toBeTruthy();
  });

  it("persists idea to localStorage on save", () => {
    render(<TradeIdeaWidget />);
    fireEvent.click(screen.getByLabelText("Add new trade idea"));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "TCS" } });
    fireEvent.click(screen.getByText("Save Idea"));
    const stored = localStorage.getItem("flinttrade:tradeideas");
    expect(stored).toBeTruthy();
    const parsed = JSON.parse(stored!);
    expect(parsed[0].symbol).toBe("TCS");
  });

  it("idea card renders saved symbol", () => {
    render(<TradeIdeaWidget />);
    fireEvent.click(screen.getByLabelText("Add new trade idea"));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "RELIANCE" } });
    fireEvent.click(screen.getByText("Save Idea"));
    expect(screen.getByText("RELIANCE")).toBeTruthy();
  });

  it("delete button removes idea from list", () => {
    render(<TradeIdeaWidget />);
    fireEvent.click(screen.getByLabelText("Add new trade idea"));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "WIPRO" } });
    fireEvent.click(screen.getByText("Save Idea"));
    fireEvent.click(screen.getByLabelText("Delete idea for WIPRO"));
    expect(screen.queryByText("WIPRO")).toBeNull();
  });

  it("empty symbol does not save idea", () => {
    render(<TradeIdeaWidget />);
    fireEvent.click(screen.getByLabelText("Add new trade idea"));
    fireEvent.click(screen.getByText("Save Idea"));
    expect(screen.getByText("0")).toBeTruthy();
  });
});
