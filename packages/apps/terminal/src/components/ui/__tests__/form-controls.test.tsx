import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { Checkbox } from "../checkbox";
import { NativeSelect } from "../native-select";

describe("NativeSelect", () => {
  it("stays a native select with its label, options and change events", () => {
    const onChange = vi.fn();
    render(
      <label>
        Alert channel
        <NativeSelect value="telegram" onChange={onChange}>
          <option value="telegram">Telegram</option>
          <option value="email">Email (SMTP)</option>
        </NativeSelect>
      </label>,
    );
    const select = screen.getByRole("combobox", { name: "Alert channel" });
    expect(select.tagName).toBe("SELECT");
    expect(select).toHaveAttribute("data-slot", "native-select");
    expect(select).toHaveValue("telegram");
    fireEvent.change(select, { target: { value: "email" } });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("offers the toolbar height and passes the disabled state through", () => {
    render(<NativeSelect aria-label="Preset" controlSize="sm" disabled><option>One</option></NativeSelect>);
    const select = screen.getByRole("combobox", { name: "Preset" });
    expect(select).toBeDisabled();
    expect(select).toHaveClass("h-8");
  });
});

describe("Checkbox", () => {
  it("is a labelled native checkbox that reports its checked state", () => {
    const onChange = vi.fn();
    render(<label><Checkbox defaultChecked={false} onChange={onChange} /> Show system jobs</label>);
    const box = screen.getByRole("checkbox", { name: "Show system jobs" });
    expect(box).toHaveAttribute("data-slot", "checkbox");
    expect(box).not.toBeChecked();
    fireEvent.click(box);
    expect(box).toBeChecked();
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
