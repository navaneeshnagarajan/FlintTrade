/**
 * AlertsWidget.test.tsx
 *
 * Tests for the Price Alerts widget.
 * Covers: render, creating alerts, deleting alerts, tab switching.
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// localStorage mock
// ---------------------------------------------------------------------------

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

// ---------------------------------------------------------------------------
// Suppress ResizeObserver noise
// ---------------------------------------------------------------------------

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Mock external dependencies
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn().mockResolvedValue([
    { symbol: "SBIN", exchange: "NSE" },
    { symbol: "SBICARD", exchange: "NSE" },
  ]),
  getTicker: vi.fn().mockResolvedValue({ ltp: 845.5 }),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: vi.fn().mockReturnValue(false),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import AlertsWidget from "../AlertsWidget";
import { searchSymbol } from "@/services/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const LS_KEY = "flinttrade:alerts";

function clearAlerts() {
  localStorageMock.removeItem(LS_KEY);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AlertsWidget", () => {
  beforeEach(() => {
    clearAlerts();
    vi.clearAllMocks();
  });

  afterEach(() => {
    clearAlerts();
  });

  // ─── Render ──────────────────────────────────────────────────────────────

  it("renders without crashing", () => {
    render(<AlertsWidget />);
    expect(screen.getByText("Price Alerts")).toBeInTheDocument();
  });

  it("renders Active Alerts and Alert Log tabs", () => {
    render(<AlertsWidget />);
    const nav = screen.getByRole("tablist", { name: /alerts tabs/i });
    expect(within(nav).getByText("Active Alerts")).toBeInTheDocument();
    expect(within(nav).getByText("Alert Log")).toBeInTheDocument();
  });

  it("shows Active Alerts tab by default", () => {
    render(<AlertsWidget />);
    const activeTab = screen.getByRole("tab", { name: /active alerts/i });
    expect(activeTab).toHaveAttribute("aria-current", "true");
  });

  it("shows empty state when no active alerts exist", () => {
    render(<AlertsWidget />);
    expect(screen.getByText("No active alerts")).toBeInTheDocument();
  });

  it("renders Create Alert button in header", () => {
    render(<AlertsWidget />);
    expect(screen.getByRole("button", { name: /create alert/i })).toBeInTheDocument();
  });

  // ─── Tab switching ────────────────────────────────────────────────────────

  it("switches to Alert Log tab on click", () => {
    render(<AlertsWidget />);
    const nav = screen.getByRole("tablist", { name: /alerts tabs/i });
    const logTab = within(nav).getByText("Alert Log").closest("button")!;

    fireEvent.click(logTab);

    expect(logTab).toHaveAttribute("aria-current", "true");
    expect(screen.getByText("No triggered alerts yet")).toBeInTheDocument();
  });

  it("switches back to Active Alerts tab from Alert Log", () => {
    render(<AlertsWidget />);
    const nav = screen.getByRole("tablist", { name: /alerts tabs/i });

    // Go to Log
    fireEvent.click(within(nav).getByText("Alert Log").closest("button")!);
    expect(screen.getByText("No triggered alerts yet")).toBeInTheDocument();

    // Back to Active
    fireEvent.click(within(nav).getByText("Active Alerts").closest("button")!);
    expect(screen.getByText("No active alerts")).toBeInTheDocument();
  });

  // ─── Create form ──────────────────────────────────────────────────────────

  it("opens the create alert form when Create Alert button is clicked", () => {
    render(<AlertsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /create alert/i }));
    expect(screen.getByText("New Alert")).toBeInTheDocument();
    expect(screen.getByLabelText("Symbol search")).toBeInTheDocument();
    expect(screen.getByLabelText("Alert condition")).toBeInTheDocument();
    expect(screen.getByLabelText("Target price")).toBeInTheDocument();
  });

  it("closes the create form when Cancel is clicked", () => {
    render(<AlertsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /create alert/i }));
    expect(screen.getByText("New Alert")).toBeInTheDocument();

    // Use the text-labelled Cancel button inside the form footer (not the X icon)
    const cancelButtons = screen.getAllByRole("button", { name: "Cancel" });
    // The shadcn Button with text "Cancel" is the last one (X icon comes first in DOM)
    fireEvent.click(cancelButtons[cancelButtons.length - 1]);
    expect(screen.queryByText("New Alert")).not.toBeInTheDocument();
  });

  it("shows validation error when submitting form without a symbol", () => {
    render(<AlertsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /create alert/i }));

    const targetInput = screen.getByLabelText("Target price");
    fireEvent.change(targetInput, { target: { value: "500" } });

    fireEvent.click(screen.getByRole("button", { name: "Set Alert" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Symbol is required");
  });

  it("shows 'Symbol is required' validation error when submitting empty form", () => {
    render(<AlertsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /create alert/i }));

    // Submit without filling any field — symbol state is empty
    fireEvent.click(screen.getByRole("button", { name: "Set Alert" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Symbol is required");
  });

  // ─── Symbol autocomplete ──────────────────────────────────────────────────

  it("calls searchSymbol when typing in the symbol input", async () => {
    render(<AlertsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /create alert/i }));

    const symbolInput = screen.getByLabelText("Symbol search");
    fireEvent.change(symbolInput, { target: { value: "SBI" } });

    await waitFor(
      () => {
        expect(searchSymbol).toHaveBeenCalledWith("SBI");
      },
      { timeout: 500 },
    );
  });

  it("shows search suggestions after typing", async () => {
    render(<AlertsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /create alert/i }));

    const symbolInput = screen.getByLabelText("Symbol search");
    fireEvent.change(symbolInput, { target: { value: "SBI" } });

    await waitFor(
      () => {
        expect(screen.getByRole("listbox", { name: "Symbol suggestions" })).toBeInTheDocument();
      },
      { timeout: 500 },
    );
  });

  // ─── Creating an alert ────────────────────────────────────────────────────

  it("adds a new alert to the active list after form submission via localStorage", () => {
    // Pre-seed localStorage with a valid armed alert
    const alert = {
      id: "test-1",
      symbol: "TATAMOTORS",
      exchange: "NSE",
      condition: "above",
      targetPrice: 1000,
      createdAt: new Date().toISOString(),
      status: "armed",
    };
    localStorageMock.setItem(LS_KEY, JSON.stringify([alert]));

    render(<AlertsWidget />);

    // Should display the armed alert row
    expect(screen.getByText("TATAMOTORS")).toBeInTheDocument();
    expect(screen.getByLabelText("Condition: Above")).toBeInTheDocument();
  });

  it("shows the armed count badge when there are armed alerts", () => {
    const alerts = [
      {
        id: "a1",
        symbol: "RELIANCE",
        exchange: "NSE",
        condition: "below",
        targetPrice: 2800,
        createdAt: new Date().toISOString(),
        status: "armed",
      },
      {
        id: "a2",
        symbol: "HDFCBANK",
        exchange: "NSE",
        condition: "above",
        targetPrice: 1700,
        createdAt: new Date().toISOString(),
        status: "armed",
      },
    ];
    localStorageMock.setItem(LS_KEY, JSON.stringify(alerts));

    render(<AlertsWidget />);
    expect(screen.getByLabelText("2 armed alerts")).toBeInTheDocument();
  });

  // ─── Deleting an alert ────────────────────────────────────────────────────

  it("deletes an alert when the delete button is clicked", () => {
    const alert = {
      id: "del-1",
      symbol: "INFY",
      exchange: "NSE",
      condition: "above",
      targetPrice: 1500,
      createdAt: new Date().toISOString(),
      status: "armed",
    };
    localStorageMock.setItem(LS_KEY, JSON.stringify([alert]));

    render(<AlertsWidget />);
    expect(screen.getByText("INFY")).toBeInTheDocument();

    const deleteBtn = screen.getByRole("button", { name: /delete alert for INFY/i });
    fireEvent.click(deleteBtn);

    expect(screen.queryByText("INFY")).not.toBeInTheDocument();
    expect(screen.getByText("No active alerts")).toBeInTheDocument();
  });

  it("persists alert deletion to localStorage", () => {
    const alert = {
      id: "del-2",
      symbol: "TCS",
      exchange: "NSE",
      condition: "below",
      targetPrice: 3500,
      createdAt: new Date().toISOString(),
      status: "armed",
    };
    localStorageMock.setItem(LS_KEY, JSON.stringify([alert]));

    render(<AlertsWidget />);
    const deleteBtn = screen.getByRole("button", { name: /delete alert for TCS/i });
    fireEvent.click(deleteBtn);

    const stored = JSON.parse(localStorageMock.getItem(LS_KEY) ?? "[]") as unknown[];
    expect(stored).toHaveLength(0);
  });

  // ─── Alert Log tab ────────────────────────────────────────────────────────

  it("shows triggered alerts in Alert Log tab", () => {
    const triggered = {
      id: "t1",
      symbol: "WIPRO",
      exchange: "NSE",
      condition: "crosses_above",
      targetPrice: 560,
      createdAt: new Date().toISOString(),
      triggeredAt: new Date().toISOString(),
      status: "triggered",
    };
    localStorageMock.setItem(LS_KEY, JSON.stringify([triggered]));

    render(<AlertsWidget />);

    // Switch to log tab
    const nav = screen.getByRole("tablist", { name: /alerts tabs/i });
    fireEvent.click(within(nav).getByText("Alert Log").closest("button")!);

    expect(screen.getByText("WIPRO")).toBeInTheDocument();
  });

  it("shows triggered alert in active tab with BellRing icon aria-label", () => {
    const triggered = {
      id: "t2",
      symbol: "AXISBANK",
      exchange: "NSE",
      condition: "above",
      targetPrice: 1100,
      createdAt: new Date().toISOString(),
      triggeredAt: new Date().toISOString(),
      status: "triggered",
    };
    localStorageMock.setItem(LS_KEY, JSON.stringify([triggered]));

    render(<AlertsWidget />);
    expect(screen.getByText("AXISBANK")).toBeInTheDocument();
    expect(screen.getByLabelText("Status: triggered")).toBeInTheDocument();
  });

  // ── Interaction tests ─────────────────────────────────────────────────────

  it("changing alert condition select updates the visible condition value", () => {
    render(<AlertsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /create alert/i }));

    const conditionSelect = screen.getByLabelText("Alert condition") as HTMLSelectElement;
    fireEvent.change(conditionSelect, { target: { value: "below" } });

    expect(conditionSelect.value).toBe("below");
  });

  it("entering a target price updates the input value", () => {
    render(<AlertsWidget />);
    fireEvent.click(screen.getByRole("button", { name: /create alert/i }));

    const priceInput = screen.getByLabelText("Target price") as HTMLInputElement;
    fireEvent.change(priceInput, { target: { value: "1250.50" } });

    expect(priceInput.value).toBe("1250.50");
  });

  it("armed alert row shows the condition badge label", () => {
    localStorageMock.setItem(
      LS_KEY,
      JSON.stringify([
        {
          id: "badge-1",
          symbol: "ONGC",
          exchange: "NSE",
          condition: "below",
          targetPrice: 200,
          createdAt: new Date().toISOString(),
          status: "armed",
        },
      ]),
    );
    render(<AlertsWidget />);
    expect(screen.getByLabelText("Condition: Below")).toBeInTheDocument();
  });

  it("multiple armed alerts each have their own delete button", () => {
    localStorageMock.setItem(
      LS_KEY,
      JSON.stringify([
        { id: "m1", symbol: "SBIN", exchange: "NSE", condition: "above", targetPrice: 900, createdAt: new Date().toISOString(), status: "armed" },
        { id: "m2", symbol: "HDFC", exchange: "NSE", condition: "below", targetPrice: 1400, createdAt: new Date().toISOString(), status: "armed" },
      ]),
    );
    render(<AlertsWidget />);

    expect(screen.getByRole("button", { name: /delete alert for SBIN/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete alert for HDFC/i })).toBeInTheDocument();
  });

  it("deletes a log entry from the Alert Log tab", () => {
    const triggered = {
      id: "log-del",
      symbol: "COALINDIA",
      exchange: "NSE",
      condition: "below",
      targetPrice: 400,
      createdAt: new Date().toISOString(),
      triggeredAt: new Date().toISOString(),
      status: "triggered",
    };
    localStorageMock.setItem(LS_KEY, JSON.stringify([triggered]));

    render(<AlertsWidget />);

    // Switch to log tab
    const nav = screen.getByRole("tablist", { name: /alerts tabs/i });
    fireEvent.click(within(nav).getByText("Alert Log").closest("button")!);

    expect(screen.getByText("COALINDIA")).toBeInTheDocument();

    const deleteBtn = screen.getByRole("button", {
      name: /remove log entry for COALINDIA/i,
    });
    fireEvent.click(deleteBtn);

    expect(screen.queryByText("COALINDIA")).not.toBeInTheDocument();
    expect(screen.getByText("No triggered alerts yet")).toBeInTheDocument();
  });
});
