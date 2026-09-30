import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";

import { LayaAdmissionNotice } from "./LayaAdmissionNotice";

describe("LayaAdmissionNotice", () => {
  it("names the server reason once inside the denial alert", () => {
    render(
      <LayaAdmissionNotice
        notice={{
          kind: "deny",
          headline: "Laya denied",
          reason: "Laya is Down. Orders are paused until it's Ready.",
          limitsLine: null,
          appliedQuantity: null,
        }}
      />,
    );
    const reason = "Laya is Down. Orders are paused until it's Ready.";
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(reason);
    expect(screen.queryByRole("status", { name: "Laya decision" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Laya decision")).toHaveTextContent(reason);
    expect(alert).toContainElement(screen.getByLabelText("Laya decision"));
  });
});
