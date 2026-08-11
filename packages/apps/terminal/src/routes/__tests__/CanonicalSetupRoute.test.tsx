import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

vi.mock("../SetupBackendGate", () => ({
  SetupBackendGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("../SetupAccountRoute", () => ({
  default: ({ requestedMode, requestedStep }: { requestedMode?: string; requestedStep?: number }) => (
    <output aria-label="Canonical setup intent">
      {JSON.stringify({ requestedMode, requestedStep })}
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
  it("passes a valid selected trading mode and named step to the authoritative wizard", () => {
    expect(renderCanonical("/setup?mode=practice&step=mode#mode")).toHaveTextContent(
      JSON.stringify({ requestedMode: "practice", requestedStep: 6 }),
    );
  });

  it("uses a valid hash-only setup step deep link", () => {
    expect(renderCanonical("/setup#connection")).toHaveTextContent(
      JSON.stringify({ requestedStep: 3 }),
    );
  });

  it("ignores invalid mode and step values", () => {
    expect(renderCanonical("/setup?mode=real-money&step=99#password")).toHaveTextContent("{}");
  });
});
