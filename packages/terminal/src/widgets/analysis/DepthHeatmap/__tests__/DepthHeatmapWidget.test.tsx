import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Mock ResizeObserver for JSDOM
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };

  // Mock canvas getContext — shared by both heatmap and crosshair canvases
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
    fillRect: vi.fn(),
    clearRect: vi.fn(),
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

  it("renders the heatmap canvas (layer 1)", () => {
    render(<DepthHeatmapWidget />);
    const canvas = screen.getByTestId("depthheatmap-canvas");
    expect(canvas).toBeTruthy();
    expect(canvas.tagName.toLowerCase()).toBe("canvas");
  });

  it("renders the crosshair overlay canvas (layer 2)", () => {
    render(<DepthHeatmapWidget />);
    const crosshair = screen.getByTestId("depthheatmap-crosshair");
    expect(crosshair).toBeTruthy();
    expect(crosshair.tagName.toLowerCase()).toBe("canvas");
    // Must be above the heatmap canvas
    expect((crosshair as HTMLElement).style.zIndex).toBe("1");
  });

  it("both canvas layers have pointer-events:none so mouse events reach the container", () => {
    render(<DepthHeatmapWidget />);
    const heatmap = screen.getByTestId("depthheatmap-canvas");
    const crosshair = screen.getByTestId("depthheatmap-crosshair");
    // Tailwind's pointer-events-none class should be applied
    expect(heatmap.classList.contains("pointer-events-none")).toBe(true);
    expect(crosshair.classList.contains("pointer-events-none")).toBe(true);
  });

  it("mouse move on container does not throw", () => {
    render(<DepthHeatmapWidget />);
    const container = screen.getByTestId("depthheatmap-container");
    expect(() =>
      fireEvent.mouseMove(container, { clientX: 100, clientY: 80 }),
    ).not.toThrow();
  });

  it("mouse leave on container does not throw", () => {
    render(<DepthHeatmapWidget />);
    const container = screen.getByTestId("depthheatmap-container");
    fireEvent.mouseMove(container, { clientX: 100, clientY: 80 });
    expect(() => fireEvent.mouseLeave(container)).not.toThrow();
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
