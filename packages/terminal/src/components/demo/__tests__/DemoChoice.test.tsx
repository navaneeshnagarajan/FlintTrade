/**
 * DemoChoice.test.tsx — Renders demo mode selection UI.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock sessionStorage to avoid side effects
// ---------------------------------------------------------------------------

const sessionStorageMock = {
  getItem: vi.fn().mockReturnValue(null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
  length: 0,
  key: vi.fn(),
};
Object.defineProperty(window, "sessionStorage", { value: sessionStorageMock });

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import DemoChoice from "../DemoChoice";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DemoChoice", () => {
  it("renders the heading", () => {
    render(<DemoChoice onChoice={vi.fn()} />);
    expect(
      screen.getByText("How would you like to explore FlintTrade?"),
    ).toBeInTheDocument();
  });

  it("shows Free Explore and Guided Tour options as radio buttons", () => {
    render(<DemoChoice onChoice={vi.fn()} />);
    expect(screen.getByRole("radio", { name: /free explore/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /guided tour/i })).toBeInTheDocument();
  });
});
