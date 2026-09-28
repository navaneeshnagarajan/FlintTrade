import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

vi.mock("../SetupBackendGate", () => ({
  SetupBackendGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("../SetupAccountRoute", () => ({
  default: ({
    requestedStep,
    requestedOptional,
  }: {
    requestedStep?: number;
    requestedOptional?: string;
  }) => (
    <output aria-label="Canonical setup intent">
      {JSON.stringify({ requestedStep, requestedOptional })}
    </output>
  ),
}));

import CanonicalSetupRoute from "../CanonicalSetupRoute";

function renderCanonical(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/setup" element={<CanonicalSetupRoute />} />
      </Routes>
    </MemoryRouter>,
  );
  return screen.getByLabelText("Canonical setup intent");
}

describe("CanonicalSetupRoute deep links", () => {
  it("passes the Practice desk as the last required step", () => {
    expect(renderCanonical("/setup?step=practice#practice")).toHaveTextContent(
      JSON.stringify({ requestedStep: 2 }),
    );
  });

  it("maps a legacy mode link onto the Practice desk step", () => {
    expect(renderCanonical("/setup?step=mode#mode")).toHaveTextContent(
      JSON.stringify({ requestedStep: 2 }),
    );
  });

  it("uses a broker hash as an optional panel, not a required step", () => {
    expect(renderCanonical("/setup#connection")).toHaveTextContent(
      JSON.stringify({ requestedOptional: "broker" }),
    );
  });

  it("ignores a Live mode deep link", () => {
    expect(renderCanonical("/setup?mode=live&step=6")).toHaveTextContent("{}");
  });

  it("ignores invalid mode and step values", () => {
    expect(renderCanonical("/setup?mode=real-money&step=99#password")).toHaveTextContent("{}");
  });
});
