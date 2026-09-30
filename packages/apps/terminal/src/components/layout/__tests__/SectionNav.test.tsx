import { useState } from "react";
import { afterEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Monitor, Palette, UserCircle } from "lucide-react";
import { SectionNav, type SectionNavGroup } from "../SectionNav";

type SectionId = "profile" | "general" | "appearance";

const GROUPS: SectionNavGroup<SectionId>[] = [
  { id: "account", label: "Account", items: [{ id: "profile", label: "Profile", icon: UserCircle }] },
  {
    id: "preferences",
    label: "Preferences",
    items: [
      { id: "general", label: "General", icon: Monitor },
      { id: "appearance", label: "Appearance", icon: Palette, indicator: <span data-testid="dot" /> },
    ],
  },
];

function mockDesktop(matches: boolean) {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
}

function Harness({ collapsed = false }: { collapsed?: boolean }) {
  const [value, setValue] = useState<SectionId>("general");
  return (
    <>
      <SectionNav
        groups={GROUPS}
        value={value}
        onChange={setValue}
        label="Settings sections"
        idPrefix="settings"
        collapsed={collapsed}
      />
      <div role="tabpanel" id={`settings-tabpanel-${value}`}>
        {value}
      </div>
    </>
  );
}

describe("SectionNav", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows group headings and a vertical tablist on desktop", () => {
    mockDesktop(true);
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Settings sections" })).toHaveAttribute(
      "aria-orientation",
      "vertical",
    );
    expect(screen.getByText("Account")).toBeInTheDocument();
    expect(screen.getByText("Preferences")).toBeInTheDocument();
    expect(screen.getByTestId("dot")).toBeInTheDocument();
  });

  it("links only the selected tab to the mounted panel", () => {
    mockDesktop(true);
    render(<Harness />);
    const general = screen.getByRole("tab", { name: "General" });
    expect(general).toHaveAttribute("aria-controls", "settings-tabpanel-general");
    expect(screen.getByRole("tab", { name: "Profile" })).not.toHaveAttribute("aria-controls");
  });

  it("moves across groups with Up and Down on desktop", () => {
    mockDesktop(true);
    render(<Harness />);
    const general = screen.getByRole("tab", { name: "General" });
    general.focus();
    fireEvent.keyDown(general, { key: "ArrowUp" });
    const profile = screen.getByRole("tab", { name: "Profile" });
    expect(profile).toHaveFocus();
    expect(profile).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(profile, { key: "End" });
    expect(screen.getByRole("tab", { name: "Appearance" })).toHaveAttribute("aria-selected", "true");
  });

  it("becomes a horizontal row with Left and Right keys on narrow screens", () => {
    mockDesktop(false);
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Settings sections" })).toHaveAttribute(
      "aria-orientation",
      "horizontal",
    );
    expect(screen.queryByText("Account")).not.toBeInTheDocument();
    const general = screen.getByRole("tab", { name: "General" });
    general.focus();
    fireEvent.keyDown(general, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Appearance" })).toHaveFocus();
  });

  it("keeps labels available to assistive tech when collapsed to icons", () => {
    mockDesktop(true);
    render(<Harness collapsed />);
    const general = screen.getByRole("tab", { name: "General" });
    expect(general).toHaveAttribute("title", "General");
  });
});
