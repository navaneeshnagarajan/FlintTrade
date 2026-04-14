import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { CommandsTab } from "../CommandsTab";
import type { Command } from "../useCommandRegistry";

const mockCommands: Command[] = [
  { id: "nav:trade", title: "Go to Trade", category: "navigate", action: vi.fn() },
  { id: "action:fullscreen", title: "Toggle Fullscreen", category: "action", shortcut: "F11", action: vi.fn() },
  { id: "theme:graphite", title: "Switch to Graphite", category: "theme", action: vi.fn() },
];

describe("CommandsTab", () => {
  it("renders all commands", () => {
    render(
      <CommandsTab commands={mockCommands} query="" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    expect(screen.getByText("Go to Trade")).toBeInTheDocument();
    expect(screen.getByText("Toggle Fullscreen")).toBeInTheDocument();
    expect(screen.getByText("Switch to Graphite")).toBeInTheDocument();
  });

  it("filters commands by query", () => {
    render(
      <CommandsTab commands={mockCommands} query="trade" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("Go to Trade");
    expect(screen.queryByText("Toggle Fullscreen")).not.toBeInTheDocument();
  });

  it("calls onSelect when a command is clicked", () => {
    const onSelect = vi.fn();
    render(
      <CommandsTab commands={mockCommands} query="" activeIndex={0} onSelect={onSelect} onActiveIndexChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByText("Go to Trade"));
    expect(onSelect).toHaveBeenCalledWith(mockCommands[0]);
  });

  it("shows empty state when no commands match", () => {
    render(
      <CommandsTab commands={mockCommands} query="zzzzz" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    expect(screen.getByText(/no commands match/i)).toBeInTheDocument();
  });
});
