/**
 * ModeSelection — skip setup lands on persona default workspace (Slice 2).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

const { mockNavigate, settingsPersona } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  settingsPersona: { value: "beginner" as string },
}));

vi.mock("react-router", () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: Object.assign(
    vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
      selector({ persona: settingsPersona.value }),
    ),
    { getState: () => ({ persona: settingsPersona.value }) },
  ),
}));

vi.mock("@/components/layout/PublicRouteShell", () => ({
  default: ({ children, title }: { children: React.ReactNode; title?: string }) => (
    <div>
      <h1>{title}</h1>
      {children}
    </div>
  ),
}));

import { ModeSelection } from "../ModeSelection";

describe("ModeSelection Slice 2", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    settingsPersona.value = "beginner";
  });

  it("skip setup navigates to persona default (beginner → Home)", () => {
    render(<ModeSelection onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /skip setup/i }));
    expect(mockNavigate).toHaveBeenCalledWith("/home");
  });

  it("skip setup navigates trader to Trade", () => {
    settingsPersona.value = "trader";
    render(<ModeSelection onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /skip setup/i }));
    expect(mockNavigate).toHaveBeenCalledWith("/trade");
  });
});
