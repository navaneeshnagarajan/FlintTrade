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
          headline: "Denied by decision model",
          reason: "Not placed. Decision model is down. Start it from Status.",
          limitsLine: null,
          appliedQuantity: null,
        }}
      />,
    );
    const reason = "Not placed. Decision model is down. Start it from Status.";
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(reason);
    expect(screen.queryByRole("status", { name: "Decision model check" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Decision model check")).toHaveTextContent(reason);
    expect(alert).toContainElement(screen.getByLabelText("Decision model check"));
  });
});
