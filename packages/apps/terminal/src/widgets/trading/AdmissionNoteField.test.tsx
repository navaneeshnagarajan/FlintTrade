import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ADMISSION_NOTE_MAX, AdmissionNoteField, admissionRationale } from "./AdmissionNoteField";

const LABEL = "Add a reason (optional)";

function Harness({ initial = "", collapsible = false }: { initial?: string; collapsible?: boolean }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <AdmissionNoteField id="note" value={value} onChange={setValue} collapsible={collapsible} />
      <output data-testid="note-value">{value}</output>
    </>
  );
}

describe("AdmissionNoteField", () => {
  it("keeps an empty note and trims a typed plan", () => {
    expect(admissionRationale("  ")).toBe("");
    expect(admissionRationale("  Planned breakout  ")).toBe("Planned breakout");

    let value = "";
    const view = render(
      <AdmissionNoteField id="note" value={value} onChange={(next) => { value = next; }} />,
    );
    fireEvent.change(screen.getByLabelText("Add a reason (optional)"), {
      target: { value: "Planned breakout" },
    });
    expect(value).toBe("Planned breakout");
    view.rerender(
      <AdmissionNoteField id="note" value={value} onChange={(next) => { value = next; }} />,
    );
    expect(screen.getByLabelText("Add a reason (optional)")).toHaveValue("Planned breakout");
  });

  it("is an always-open textarea unless asked to collapse", () => {
    render(<Harness />);
    expect(screen.getByRole("textbox", { name: LABEL }).tagName).toBe("TEXTAREA");
    expect(screen.queryByRole("button", { name: LABEL })).not.toBeInTheDocument();
  });
});

describe("AdmissionNoteField collapsible", () => {
  it("starts as a link and shows no field until asked", () => {
    render(<Harness collapsible />);
    expect(screen.getByRole("button", { name: LABEL })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: LABEL })).not.toBeInTheDocument();
  });

  it("opens a focused single-line field and reports what is typed", () => {
    render(<Harness collapsible />);
    fireEvent.click(screen.getByRole("button", { name: LABEL }));

    const field = screen.getByRole("textbox", { name: LABEL });
    expect(field.tagName).toBe("INPUT");
    expect(field).toHaveAttribute("id", "note");
    expect(field).toHaveAttribute("placeholder", "Optional note for this order");
    expect(field).toHaveFocus();
    expect(screen.queryByRole("button", { name: LABEL })).not.toBeInTheDocument();

    fireEvent.change(field, { target: { value: "Planned breakout" } });
    expect(screen.getByTestId("note-value")).toHaveTextContent("Planned breakout");
  });

  it("stays open once the operator clears the note", () => {
    render(<Harness collapsible />);
    fireEvent.click(screen.getByRole("button", { name: LABEL }));
    const field = screen.getByRole("textbox", { name: LABEL });
    fireEvent.change(field, { target: { value: "x" } });
    fireEvent.change(field, { target: { value: "" } });
    expect(screen.getByRole("textbox", { name: LABEL })).toBeInTheDocument();
  });

  it("starts open, without stealing focus, when a note is already present", () => {
    render(<Harness collapsible initial="Carry trade" />);
    const field = screen.getByRole("textbox", { name: LABEL });
    expect(field).toHaveValue("Carry trade");
    expect(field).not.toHaveFocus();
  });

  it("reveals a note that arrives while collapsed, so it is never sent unseen", () => {
    const view = render(<AdmissionNoteField id="note" value="" onChange={() => {}} collapsible />);
    expect(screen.queryByRole("textbox", { name: LABEL })).not.toBeInTheDocument();

    view.rerender(<AdmissionNoteField id="note" value="Prefilled plan" onChange={() => {}} collapsible />);
    expect(screen.getByRole("textbox", { name: LABEL })).toHaveValue("Prefilled plan");
  });

  it("applies the same length cap as the open field", () => {
    render(<Harness collapsible />);
    fireEvent.click(screen.getByRole("button", { name: LABEL }));
    const field = screen.getByRole("textbox", { name: LABEL });
    expect(field).toHaveAttribute("maxlength", String(ADMISSION_NOTE_MAX));

    fireEvent.change(field, { target: { value: "a".repeat(ADMISSION_NOTE_MAX + 25) } });
    expect(screen.getByTestId("note-value").textContent).toHaveLength(ADMISSION_NOTE_MAX);
  });
});
