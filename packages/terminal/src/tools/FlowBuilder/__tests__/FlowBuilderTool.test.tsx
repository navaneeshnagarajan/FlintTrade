/**
 * FlowBuilderTool.test.tsx
 *
 * Tests for the Flow Builder canvas tool.
 * Verifies rendering, heading, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — localStorage for stored flows
// ---------------------------------------------------------------------------

const localStorageMock: Record<string, string> = {};

vi.stubGlobal("localStorage", {
  getItem: vi.fn((key: string) => localStorageMock[key] ?? null),
  setItem: vi.fn((key: string, value: string) => {
    localStorageMock[key] = value;
  }),
  removeItem: vi.fn((key: string) => {
    delete localStorageMock[key];
  }),
  clear: vi.fn(),
  length: 0,
  key: vi.fn(),
});

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import FlowBuilderTool from "../FlowBuilderTool";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FlowBuilderTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Clear stored flows
    Object.keys(localStorageMock).forEach((k) => delete localStorageMock[k]);
  });

  it("renders without crashing", () => {
    const { container } = render(<FlowBuilderTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Flow Builder heading", () => {
    render(<FlowBuilderTool />);
    expect(screen.getByText("Flow Builder")).toBeInTheDocument();
  });

  it("displays the 54 nodes badge", () => {
    render(<FlowBuilderTool />);
    expect(screen.getByText("54 nodes")).toBeInTheDocument();
  });
});
