import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock Switch (shadcn) to avoid Radix portal issues in test environment
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/switch", () => ({
  Switch: ({
    checked,
    onCheckedChange,
    "aria-label": ariaLabel,
    "data-testid": testId,
  }: {
    checked: boolean;
    onCheckedChange: (v: boolean) => void;
    "aria-label"?: string;
    "data-testid"?: string;
  }) => (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      data-testid={testId}
      onClick={() => onCheckedChange(!checked)}
    />
  ),
}));

// Mock Badge to a simple span
vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...rest }: React.HTMLAttributes<HTMLSpanElement>) => (
    <span {...rest}>{children}</span>
  ),
}));

// Mock shadcn/ui Input to a native <input>
vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}));

// Mock shadcn/ui Select components to render as a native <select> for testability
vi.mock("@/components/ui/select", async () => {
  const { createContext, useContext } = await import("react");
  type SelectCtx = { value?: string; onValueChange?: (v: string) => void };
  const Ctx = createContext<SelectCtx>({});

  return {
    Select: ({
      value,
      onValueChange,
      children,
    }: {
      value?: string;
      onValueChange?: (v: string) => void;
      children?: React.ReactNode;
    }) => <Ctx.Provider value={{ value, onValueChange }}>{children}</Ctx.Provider>,

    SelectTrigger: ({
      "data-testid": testId,
      "aria-label": ariaLabel,
    }: {
      "data-testid"?: string;
      "aria-label"?: string;
      [key: string]: unknown;
    }) => <span data-testid={testId} aria-label={ariaLabel} />,

    SelectValue: ({ placeholder }: { placeholder?: string }) => (
      <span>{placeholder}</span>
    ),

    SelectContent: ({
      children,
      "data-testid": testId,
    }: {
      children?: React.ReactNode;
      "data-testid"?: string;
    }) => {
      const ctx = useContext(Ctx);
      return (
        <select
          data-testid={testId}
          value={ctx.value ?? ""}
          onChange={(e) => ctx.onValueChange?.(e.target.value)}
        >
          {children}
        </select>
      );
    },

    SelectItem: ({
      value,
      children,
    }: {
      value: string;
      children?: React.ReactNode;
    }) => <option value={value}>{children}</option>,
  };
});

import React from "react";

// ---------------------------------------------------------------------------
// Clear localStorage before each test so config doesn't bleed between tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  localStorage.clear();
});

import TradeCopierWidget from "../TradeCopierWidget";

describe("TradeCopierWidget — basic render", () => {
  it("renders the widget root element", () => {
    render(<TradeCopierWidget />);
    expect(screen.getByTestId("tradecopier-widget")).toBeTruthy();
  });

  it("shows 'Trade Copier' heading", () => {
    render(<TradeCopierWidget />);
    expect(screen.getByText(/trade copier/i)).toBeTruthy();
  });

  it("renders the source account selector", () => {
    render(<TradeCopierWidget />);
    expect(screen.getByTestId("source-select")).toBeTruthy();
  });

  it("default source account is Primary", () => {
    render(<TradeCopierWidget />);
    const select = screen.getByTestId("source-select") as HTMLSelectElement;
    expect(select.value).toBe("acc-1");
  });

  it("renders Mirror and Proportional mode buttons", () => {
    render(<TradeCopierWidget />);
    expect(screen.getByTestId("mode-mirror")).toBeTruthy();
    expect(screen.getByTestId("mode-proportional")).toBeTruthy();
  });
});

describe("TradeCopierWidget — source selector", () => {
  it("changes source account on selection", () => {
    render(<TradeCopierWidget />);
    const select = screen.getByTestId("source-select") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "acc-2" } });
    expect(select.value).toBe("acc-2");
  });

  it("lists all sample accounts in the dropdown", () => {
    render(<TradeCopierWidget />);
    const select = screen.getByTestId("source-select") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain("acc-1");
    expect(options).toContain("acc-2");
    expect(options).toContain("acc-3");
  });
});

describe("TradeCopierWidget — copy mode switch", () => {
  it("Mirror button is active by default", () => {
    render(<TradeCopierWidget />);
    const mirrorBtn = screen.getByTestId("mode-mirror");
    // Active button has accent class
    expect(mirrorBtn.className).toContain("accent");
  });

  it("clicking Proportional switches the mode", () => {
    render(<TradeCopierWidget />);
    const propBtn = screen.getByTestId("mode-proportional");
    fireEvent.click(propBtn);
    // Proportional button should now be active
    expect(propBtn.className).toContain("accent");
    // Mirror button should lose accent
    const mirrorBtn = screen.getByTestId("mode-mirror");
    expect(mirrorBtn.className).not.toContain("bg-accent/15 text-accent");
  });

  it("shows 'ratio via multiplier' hint when Proportional is selected", () => {
    render(<TradeCopierWidget />);
    fireEvent.click(screen.getByTestId("mode-proportional"));
    expect(screen.getByText(/ratio via multiplier/i)).toBeTruthy();
  });
});

describe("TradeCopierWidget — target account toggles", () => {
  it("renders default target accounts", () => {
    render(<TradeCopierWidget />);
    // Default targets: acc-2 and acc-3
    expect(screen.getByTestId("target-acc-2")).toBeTruthy();
    expect(screen.getByTestId("target-acc-3")).toBeTruthy();
  });

  it("toggle switch changes enabled state", () => {
    render(<TradeCopierWidget />);
    const toggle = screen.getByTestId("enable-acc-2");
    const initial = toggle.getAttribute("aria-checked");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).not.toBe(initial);
  });

  it("pause button changes status indicator for target", () => {
    render(<TradeCopierWidget />);
    // acc-2 starts as "active" → clicking pause should change to "paused"
    const pauseBtn = screen.getByTestId("status-toggle-acc-2");
    // Should show Pause label initially (active account)
    expect(pauseBtn.getAttribute("aria-label")).toContain("Pause");
    fireEvent.click(pauseBtn);
    // After click should show Resume
    expect(pauseBtn.getAttribute("aria-label")).toContain("Resume");
  });

  it("remove button removes the target account", () => {
    render(<TradeCopierWidget />);
    expect(screen.getByTestId("target-acc-2")).toBeTruthy();
    fireEvent.click(screen.getByTestId("remove-acc-2"));
    expect(screen.queryByTestId("target-acc-2")).toBeNull();
  });

  it("multiplier input accepts new value", () => {
    render(<TradeCopierWidget />);
    const input = screen.getByTestId("multiplier-acc-2") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "2" } });
    expect(input.value).toBe("2");
  });
});

describe("TradeCopierWidget — risk filter panel", () => {
  it("risk panel is hidden by default", () => {
    render(<TradeCopierWidget />);
    expect(screen.queryByTestId("risk-panel")).toBeNull();
  });

  it("clicking risk toggle shows the risk panel", () => {
    render(<TradeCopierWidget />);
    fireEvent.click(screen.getByTestId("risk-toggle"));
    expect(screen.getByTestId("risk-panel")).toBeTruthy();
  });

  it("max position input updates config", () => {
    render(<TradeCopierWidget />);
    fireEvent.click(screen.getByTestId("risk-toggle"));
    const input = screen.getByTestId("max-position-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "10" } });
    expect(input.value).toBe("10");
  });

  it("max daily loss input accepts a value", () => {
    render(<TradeCopierWidget />);
    fireEvent.click(screen.getByTestId("risk-toggle"));
    const input = screen.getByTestId("max-daily-loss-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "5000" } });
    expect(input.value).toBe("5000");
  });

  it("symbol whitelist renders badge chips for entered symbols", () => {
    render(<TradeCopierWidget />);
    fireEvent.click(screen.getByTestId("risk-toggle"));
    const input = screen.getByTestId("symbol-whitelist-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "NIFTY, BANKNIFTY" } });
    expect(screen.getByText("NIFTY")).toBeTruthy();
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
  });
});

describe("TradeCopierWidget — copy log", () => {
  it("copy log is empty by default", () => {
    render(<TradeCopierWidget />);
    expect(screen.getByTestId("copy-log")).toBeTruthy();
    expect(screen.getByText(/no copy events yet/i)).toBeTruthy();
  });

  it("Test Copy button creates log entries", () => {
    render(<TradeCopierWidget />);
    fireEvent.click(screen.getByTestId("test-copy-btn"));
    // Should have at least one log entry now
    expect(screen.queryByText(/no copy events yet/i)).toBeNull();
  });

  it("Clear button removes all log entries", () => {
    render(<TradeCopierWidget />);
    fireEvent.click(screen.getByTestId("test-copy-btn"));
    // Find and click Clear
    const clearBtn = screen.getByTestId("clear-log-btn");
    fireEvent.click(clearBtn);
    expect(screen.getByText(/no copy events yet/i)).toBeTruthy();
  });
});

describe("TradeCopierWidget — add target account", () => {
  it("shows add-target-select when non-source accounts are available", () => {
    render(<TradeCopierWidget />);
    // Remove existing targets first so we can see the add select for all
    fireEvent.click(screen.getByTestId("remove-acc-2"));
    fireEvent.click(screen.getByTestId("remove-acc-3"));
    // Now both acc-2 and acc-3 should appear in the add select
    const addSelect = screen.getByTestId("add-target-select") as HTMLSelectElement;
    const options = Array.from(addSelect.options).map((o) => o.value).filter(Boolean);
    expect(options).toContain("acc-2");
    expect(options).toContain("acc-3");
  });

  it("add button is disabled when no target is selected", () => {
    render(<TradeCopierWidget />);
    // Remove existing targets
    fireEvent.click(screen.getByTestId("remove-acc-2"));
    fireEvent.click(screen.getByTestId("remove-acc-3"));
    const addBtn = screen.getByTestId("add-target-btn") as HTMLButtonElement;
    expect(addBtn.disabled).toBe(true);
  });

  it("adding a target account shows it in the target list", () => {
    render(<TradeCopierWidget />);
    // Remove all targets
    fireEvent.click(screen.getByTestId("remove-acc-2"));
    fireEvent.click(screen.getByTestId("remove-acc-3"));
    // Select acc-2 from the add dropdown
    const addSelect = screen.getByTestId("add-target-select") as HTMLSelectElement;
    fireEvent.change(addSelect, { target: { value: "acc-2" } });
    fireEvent.click(screen.getByTestId("add-target-btn"));
    expect(screen.getByTestId("target-acc-2")).toBeTruthy();
  });
});
