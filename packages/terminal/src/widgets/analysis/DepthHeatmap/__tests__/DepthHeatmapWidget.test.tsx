import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock ResizeObserver for JSDOM
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };

  // Mock canvas getContext
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
    fillRect: vi.fn(),
    fillText: vi.fn(),
    strokeRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    setLineDash: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    globalAlpha: 1,
    font: "",
    textAlign: "",
    textBaseline: "",
  }) as unknown as typeof HTMLCanvasElement.prototype.getContext;
});

import DepthHeatmapWidget from "../DepthHeatmapWidget";

describe("DepthHeatmapWidget", () => {
  it("renders the widget with toolbar", () => {
    render(<DepthHeatmapWidget />);
    expect(screen.getByText("Depth Heatmap")).toBeTruthy();
    expect(screen.getByText("Synthetic")).toBeTruthy();
    expect(screen.getByText("LTP")).toBeTruthy();
  });

  it("renders the canvas container with proper role", () => {
    render(<DepthHeatmapWidget />);
    const container = screen.getByTestId("depthheatmap-container");
    expect(container).toBeTruthy();
    expect(container.getAttribute("role")).toBe("img");
    expect(container.getAttribute("aria-label")).toContain("Depth heatmap");
  });

  it("renders the canvas element", () => {
    render(<DepthHeatmapWidget />);
    const canvas = screen.getByTestId("depthheatmap-canvas");
    expect(canvas).toBeTruthy();
    expect(canvas.tagName.toLowerCase()).toBe("canvas");
  });

  it("has symbol selector with default NIFTY", () => {
    render(<DepthHeatmapWidget />);
    // The SelectValue renders the current value
    expect(screen.getByText("NIFTY")).toBeTruthy();
  });

  it("has accessible symbol selector label", () => {
    render(<DepthHeatmapWidget />);
    const label = document.getElementById("dh-symbol-label");
    expect(label).toBeTruthy();
    expect(label?.textContent).toBe("Symbol");
  });
});
