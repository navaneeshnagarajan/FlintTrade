import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AppearanceSection } from "../AppearanceSection";
vi.mock("@/components/theme/BackgroundPicker", () => ({ BackgroundPicker: () => null }));
describe("Appearance control ownership", () => {
  it("renders one mode selector and one glass control", () => {
    render(<AppearanceSection />);
    for (const name of [/^light(?: mode)?$/i, /^dark(?: mode)?$/i, /^system(?: mode)?$/i]) {
      expect(screen.getAllByRole("button", { name })).toHaveLength(1);
    }
    expect(screen.getAllByRole("switch", { name: /glass/i })).toHaveLength(1);
  });
});
