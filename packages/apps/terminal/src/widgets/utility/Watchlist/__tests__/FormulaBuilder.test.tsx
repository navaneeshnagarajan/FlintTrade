import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { FormulaBuilder } from "../FormulaBuilder";
import type { WatchlistCustomFormula } from "../types";

describe("FormulaBuilder", () => {
  it("adds a valid custom formula", () => {
    const onAdd = vi.fn();
    render(<FormulaBuilder customFormulas={[]} onAdd={onAdd} onRemove={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Formula name"), { target: { value: "Range %" } });
    fireEvent.change(screen.getByLabelText("Formula expression"), { target: { value: "(high - low) / ltp * 100" } });
    fireEvent.click(screen.getByText("Add formula"));

    expect(onAdd).toHaveBeenCalledWith("Range %", "(high - low) / ltp * 100");
  });

  it("rejects an invalid expression with an error and does not add", () => {
    const onAdd = vi.fn();
    render(<FormulaBuilder customFormulas={[]} onAdd={onAdd} onRemove={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Formula name"), { target: { value: "Bad" } });
    fireEvent.change(screen.getByLabelText("Formula expression"), { target: { value: "foo + bar" } });
    fireEvent.click(screen.getByText("Add formula"));

    expect(onAdd).not.toHaveBeenCalled();
    expect(screen.getByText(/Unknown field/i)).toBeInTheDocument();
  });

  it("requires a name", () => {
    const onAdd = vi.fn();
    render(<FormulaBuilder customFormulas={[]} onAdd={onAdd} onRemove={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Formula expression"), { target: { value: "high - low" } });
    fireEvent.click(screen.getByText("Add formula"));

    expect(onAdd).not.toHaveBeenCalled();
    expect(screen.getByText(/Give the formula a name/i)).toBeInTheDocument();
  });

  it("lists existing formulas and removes them", () => {
    const onRemove = vi.fn();
    const formulas: WatchlistCustomFormula[] = [
      { id: "custom:1", name: "Spread", expression: "high - low" },
    ];
    render(<FormulaBuilder customFormulas={formulas} onAdd={vi.fn()} onRemove={onRemove} />);

    expect(screen.getByText("Spread")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Delete formula Spread"));
    expect(onRemove).toHaveBeenCalledWith("custom:1");
  });
});
