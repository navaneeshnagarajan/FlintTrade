import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";

import { LayaAdmissionNotice } from "./LayaAdmissionNotice";

describe("LayaAdmissionNotice", () => {
  it("names the server reason for assistive tech", () => {
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
    expect(screen.getByRole("status", { name: "Laya decision" })).toHaveTextContent(
      "Laya is Down. Orders are paused until it's Ready.",
    );
  });
});
