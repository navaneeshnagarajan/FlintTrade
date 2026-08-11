import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import {
  CANONICAL_SETUP_PATH,
  LEGACY_SETUP_ACCOUNT_PATH,
  SETUP_ROUTE_POLICY,
  SetupAccountAlias,
} from "../setupRouting";

function LocationProbe() {
  const location = useLocation();
  return (
    <output aria-label="Current setup location">
      {location.pathname}{location.search}{location.hash}
    </output>
  );
}

function renderAlias(initialEntry: string) {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path={LEGACY_SETUP_ACCOUNT_PATH} element={<SetupAccountAlias />} />
        <Route path={CANONICAL_SETUP_PATH} element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("setup route authority", () => {
  it("redirects the legacy account path to canonical setup and preserves a valid mode, step and hash deep link", async () => {
    renderAlias("/setup-account?mode=practice&step=mode#mode");

    await waitFor(() => {
      expect(screen.getByLabelText("Current setup location")).toHaveTextContent(
        "/setup?mode=practice&step=mode#mode",
      );
    });
  });

  it("drops invalid setup state rather than carrying an unsafe or impossible deep link", async () => {
    renderAlias("/setup-account?mode=real-money&step=99&next=https://example.invalid#password");

    await waitFor(() => {
      expect(screen.getByLabelText("Current setup location")).toHaveTextContent(/^\/setup$/);
    });
  });

  it("defines exactly one authoritative setup route and keeps setup-account as an alias", () => {
    expect(Object.values(SETUP_ROUTE_POLICY).filter((route) => route.kind === "canonical"))
      .toEqual([{ kind: "canonical", path: CANONICAL_SETUP_PATH }]);
    expect(SETUP_ROUTE_POLICY.setupAccount).toEqual({
      kind: "alias",
      path: LEGACY_SETUP_ACCOUNT_PATH,
      target: CANONICAL_SETUP_PATH,
    });
  });
});
