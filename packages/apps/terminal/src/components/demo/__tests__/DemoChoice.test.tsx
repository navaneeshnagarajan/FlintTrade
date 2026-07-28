/**
 * DemoChoice.test.tsx — Renders demo mode selection UI.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

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

function renderDemoChoice() {
  return render(
    <MemoryRouter>
      <DemoChoice onChoice={vi.fn()} />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DemoChoice", () => {
  it("renders the heading", () => {
    renderDemoChoice();
    expect(
      screen.getByText("How would you like to explore FlintTrade?"),
    ).toBeInTheDocument();
    expect(screen.getByRole("main", { name: /explore mode entry/i })).toBeInTheDocument();
  });

  it("shows Free Explore and Guided Tour options as radio buttons", () => {
    renderDemoChoice();
    expect(screen.getByRole("radio", { name: /demo mode/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /guided tour/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /enter demo mode/i })).toBeInTheDocument();
  });
});
