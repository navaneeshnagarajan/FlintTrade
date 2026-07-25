/**
 * ToolsDropdown.test — pins the Market Intelligence unmount (ruling D4).
 *
 * The tool's every tab is served by a Dockview widget now, so the entry must
 * not come back: an overlay tool and a widget covering the same ground is the
 * duplication this dedup removed. Deliberately silent about the OTHER entries'
 * labels, which are not this suite's business.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "@testing-library/jest-dom";

import ToolsDropdown from "../ToolsDropdown";

function renderDropdown(route = "/trade", allowedToolIds?: string[]) {
  const onSelectTool = vi.fn();
  render(
    <MemoryRouter initialEntries={[route]}>
      <ToolsDropdown
        isOpen
        onClose={vi.fn()}
        onSelectTool={onSelectTool}
        allowedToolIds={allowedToolIds}
      />
    </MemoryRouter>,
  );
  return { onSelectTool };
}

describe("ToolsDropdown", () => {
  it("does not offer Market Intelligence on /trade", () => {
    renderDropdown();
    expect(screen.queryByRole("menuitem", { name: /market intelligence/i })).toBeNull();
  });

  it("still offers the surviving overlay tools", () => {
    renderDropdown();
    expect(screen.getByRole("menuitem", { name: /settings/i })).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem").length).toBeGreaterThan(1);
  });

  it("cannot be brought back by a stale skill allowlist entry", () => {
    // `useSkillContent` still lists "market-intelligence" for advanced users.
    // The allowlist FILTERS the tool table; it cannot add to it, so a stale
    // entry is inert rather than a way back in.
    renderDropdown("/trade", ["market-intelligence", "settings"]);
    expect(screen.queryByRole("menuitem", { name: /market intelligence/i })).toBeNull();
    expect(screen.getByRole("menuitem", { name: /settings/i })).toBeInTheDocument();
  });

  it("shows Settings only off /trade", () => {
    renderDropdown("/analyse");
    expect(screen.getAllByRole("menuitem")).toHaveLength(1);
    expect(screen.getByRole("menuitem", { name: /settings/i })).toBeInTheDocument();
  });

  it("renders nothing when closed", () => {
    render(
      <MemoryRouter initialEntries={["/trade"]}>
        <ToolsDropdown isOpen={false} onClose={vi.fn()} onSelectTool={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
