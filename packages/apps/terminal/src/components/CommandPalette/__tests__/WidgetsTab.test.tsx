// __tests__/WidgetsTab.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { WidgetsTab } from "../WidgetsTab";
import type { Command } from "../useCommandRegistry";

const mockWidgets: Command[] = [
  { id: "widget:chart", title: "Add Chart", description: "Open Chart widget", category: "widget", action: vi.fn() },
  { id: "widget:positions", title: "Add Positions", description: "Open Positions widget", category: "widget", action: vi.fn() },
];

describe("WidgetsTab", () => {
  it("renders all widget commands", () => {
    render(
      <WidgetsTab widgets={mockWidgets} query="" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    expect(screen.getByText("Add Chart")).toBeInTheDocument();
    expect(screen.getByText("Add Positions")).toBeInTheDocument();
  });

  it("filters by query", () => {
    render(
      <WidgetsTab widgets={mockWidgets} query="chart" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    expect(screen.getByText(/Add Chart/)).toBeInTheDocument();
    expect(screen.queryByText("Add Positions")).not.toBeInTheDocument();
  });

  it("strips # prefix from query", () => {
    render(
      <WidgetsTab widgets={mockWidgets} query="#chart" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    expect(screen.getByText(/Add Chart/)).toBeInTheDocument();
    expect(screen.queryByText("Add Positions")).not.toBeInTheDocument();
  });

  it("calls onSelect on click", () => {
    const onSelect = vi.fn();
    render(
      <WidgetsTab widgets={mockWidgets} query="" activeIndex={0} onSelect={onSelect} onActiveIndexChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByText("Add Chart"));
    expect(onSelect).toHaveBeenCalledWith(mockWidgets[0]);
  });

  it("shows empty state when no widgets match", () => {
    render(
      <WidgetsTab widgets={mockWidgets} query="zzzz" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    expect(screen.getByText(/no widgets match/i)).toBeInTheDocument();
  });
});
