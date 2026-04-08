/**
 * PresetPicker.test.tsx — Renders the preset dialog with all 6 workspace names.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: { applyPreset: () => void }) => unknown) =>
    selector({ applyPreset: vi.fn() }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import PresetPicker from "../PresetPicker";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PresetPicker", () => {
  it("renders the dialog title when open", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Choose a Workspace Template")).toBeInTheDocument();
  });

  it("shows all 6 preset names", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    const presetNames = [
      "Scalper Zone",
      "Options Desk",
      "Market Watch",
      "Analysis",
      "Risk Monitor",
      "Investor View",
    ];
    for (const name of presetNames) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });
});
