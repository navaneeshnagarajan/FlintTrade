/**
 * StatusBar.test.tsx — Unit tests for the bento dashboard status bar.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mock bentoStore
// ---------------------------------------------------------------------------
const mockBentoState = {
  cards: Array.from({ length: 8 }, (_, i) => ({ id: `c-${i}`, componentId: "X", size: "default", order: i })),
  presets: [],
  activePresetId: null,
  savePreset: vi.fn(),
  resetToDefault: vi.fn(),
};

vi.mock("@/stores/bentoStore", () => ({
  useBentoStore: (selector: (s: typeof mockBentoState) => unknown) => selector(mockBentoState),
}));

import StatusBar from "../StatusBar";

describe("StatusBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the status bar", () => {
    render(<StatusBar />);
    expect(screen.getByTestId("status-bar")).toBeInTheDocument();
  });

  it("renders card count from store when no cardCount prop given", () => {
    render(<StatusBar />);
    const countEl = screen.getByTestId("status-bar-card-count");
    expect(countEl.textContent).toBe("8");
  });

  it("renders card count from prop when provided", () => {
    render(<StatusBar cardCount={12} />);
    expect(screen.getByTestId("status-bar-card-count").textContent).toBe("12");
  });

  it("renders layout name from prop", () => {
    render(<StatusBar layoutName="Custom Layout" />);
    expect(screen.getByTestId("status-bar-layout-name").textContent).toBe("Custom Layout");
  });

  it("renders 'Default' when no layout name given", () => {
    render(<StatusBar />);
    expect(screen.getByTestId("status-bar-layout-name").textContent).toBe("Default");
  });

  it("renders Save, Presets, and Reset buttons", () => {
    render(<StatusBar />);
    expect(screen.getByRole("button", { name: /save current layout/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /view presets/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset layout/i })).toBeInTheDocument();
  });

  it("renders 'Drag to rearrange' hint", () => {
    render(<StatusBar />);
    expect(screen.getByText(/drag to rearrange/i)).toBeInTheDocument();
  });
});
