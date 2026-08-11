import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, useLocation } from "react-router";
import { useLayoutStore } from "@/stores/layoutStore";
import WorkspaceSwitcher from "../WorkspaceSwitcher";

function renderSwitcher(path = "/trade") {
  function LocationProbe() {
    return <span data-testid="location">{useLocation().pathname}</span>;
  }
  return render(
    <MemoryRouter initialEntries={[path]}>
      <WorkspaceSwitcher />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("WorkspaceSwitcher", () => {
  beforeEach(() => {
    localStorage.clear();
    useLayoutStore.setState(useLayoutStore.getInitialState(), true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("switches to another saved workspace through an accessible control", () => {
    const first = useLayoutStore.getState().tabs[0];
    useLayoutStore.getState().addTab("Options Desk", undefined, "ws-options");
    useLayoutStore.getState().setActiveTab(first.id);

    renderSwitcher();

    const switcher = screen.getByRole("combobox", { name: "Active workspace" });
    expect(switcher).toHaveValue(first.id);

    fireEvent.change(switcher, { target: { value: "ws-options" } });

    expect(useLayoutStore.getState().activeTabId).toBe("ws-options");
    expect(switcher).toHaveValue("ws-options");
  });

  it("opens workspace management from the top bar", () => {
    renderSwitcher();

    fireEvent.click(screen.getByRole("button", { name: "Manage workspaces" }));

    expect(useLayoutStore.getState().presetPickerOpen).toBe(true);
  });

  it("navigates to the terminal before opening workspace management", () => {
    renderSwitcher("/home");

    fireEvent.click(screen.getByRole("button", { name: "Manage workspaces" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/trade");
    expect(useLayoutStore.getState().presetPickerOpen).toBe(true);
  });

  it("reports a persistence failure and restores the previous selection", () => {
    useLayoutStore.getState().addTab("Options Desk", undefined, "ws-options");
    useLayoutStore.getState().setActiveTab(useLayoutStore.getState().tabs[0].id);
    const originalId = useLayoutStore.getState().activeTabId;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    renderSwitcher();

    fireEvent.change(screen.getByRole("combobox", { name: "Active workspace" }), {
      target: { value: "ws-options" },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Workspace could not be switched: quota exceeded",
    );
    expect(useLayoutStore.getState().activeTabId).toBe(originalId);
  });
});
