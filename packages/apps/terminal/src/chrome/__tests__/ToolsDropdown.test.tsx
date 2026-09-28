/**
 * ToolsDropdown.test — pins the Market Intelligence unmount (ruling D4).
 *
 * The tool's every tab is served by a Dockview widget now, so the entry must
 * not come back: an overlay tool and a widget covering the same ground is the
 * duplication this dedup removed. Quick Settings versus Settings is pinned
 * here as well: Quick Settings stays on the current route, Settings is the
 * full route, and a skill allowlist cannot hide Quick Settings.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import "@testing-library/jest-dom";

import ToolsDropdown from "../ToolsDropdown";

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location-probe">{loc.pathname + loc.hash}</div>;
}

function renderDropdown(route = "/trade", allowedToolIds?: string[]) {
  const onSelectTool = vi.fn();
  const onOpenQuickSettings = vi.fn();
  const onClose = vi.fn();
  render(
    <MemoryRouter initialEntries={[route]}>
      <ToolsDropdown
        isOpen
        onClose={onClose}
        onSelectTool={onSelectTool}
        onOpenQuickSettings={onOpenQuickSettings}
        allowedToolIds={allowedToolIds}
      />
      <LocationProbe />
    </MemoryRouter>,
  );
  return { onSelectTool, onOpenQuickSettings, onClose };
}

describe("ToolsDropdown", () => {
  it("does not offer Market Intelligence on /trade", () => {
    renderDropdown();
    expect(screen.queryByRole("menuitem", { name: /market intelligence/i })).toBeNull();
  });

  it("still offers the surviving overlay tools", () => {
    renderDropdown();
    expect(screen.getByRole("menuitem", { name: "Trade Review" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem").length).toBeGreaterThan(1);
  });

  it("cannot be brought back by a stale skill allowlist entry", () => {
    // A persisted skill allowlist can still carry the retired
    // "market-intelligence" id. The allowlist FILTERS the tool table; it
    // cannot add to it, so a stale entry is inert rather than a way back in.
    renderDropdown("/trade", ["market-intelligence", "settings"]);
    expect(screen.queryByRole("menuitem", { name: /market intelligence/i })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Quick Settings" })).toBeInTheDocument();
  });

  it("shows Quick Settings and Settings off /trade", () => {
    renderDropdown("/analyse");
    expect(screen.getAllByRole("menuitem")).toHaveLength(2);
    expect(screen.getByRole("menuitem", { name: "Quick Settings" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Trade Review" })).toBeNull();
  });

  it("opens Quick Settings in place and keeps Settings on the full route", () => {
    const { onSelectTool, onOpenQuickSettings, onClose } = renderDropdown("/trade");

    fireEvent.click(screen.getByRole("menuitem", { name: "Quick Settings" }));

    expect(onOpenQuickSettings).toHaveBeenCalledTimes(1);
    expect(onSelectTool).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("location-probe").textContent).toBe("/trade");

    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));

    expect(onSelectTool).toHaveBeenCalledTimes(1);
    expect(onSelectTool).toHaveBeenCalledWith("settings");
    expect(screen.getByTestId("location-probe").textContent).toBe("/trade");
  });

  it("does not let a skill allowlist hide Quick Settings", () => {
    renderDropdown("/trade", ["trade-journal"]);
    expect(screen.getByRole("menuitem", { name: "Quick Settings" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Trade Review" })).toBeInTheDocument();
  });

  it("navigates Settings to /settings off the trade desk and leaves Quick Settings in place", () => {
    const { onSelectTool, onOpenQuickSettings } = renderDropdown("/analyse");

    fireEvent.click(screen.getByRole("menuitem", { name: "Quick Settings" }));
    expect(onOpenQuickSettings).toHaveBeenCalledTimes(1);
    expect(onSelectTool).not.toHaveBeenCalled();
    expect(screen.getByTestId("location-probe").textContent).toBe("/analyse");

    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));
    expect(onSelectTool).not.toHaveBeenCalled();
    expect(screen.getByTestId("location-probe").textContent).toBe("/settings");
  });

  it("renders nothing when closed", () => {
    render(
      <MemoryRouter initialEntries={["/trade"]}>
        <ToolsDropdown
          isOpen={false}
          onClose={vi.fn()}
          onSelectTool={vi.fn()}
          onOpenQuickSettings={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
