import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";

import { AdmissionNoteField, admissionRationale } from "./AdmissionNoteField";

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
});
