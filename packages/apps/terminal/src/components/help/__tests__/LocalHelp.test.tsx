import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { LocalHelp } from "../LocalHelp";
import { DeveloperPreference, developerEnabled } from "@/chrome/DeveloperPreference";

describe("installed optional presentation", () => {
  it("offers useful labelled help without sending a model task", () => {
    render(<MemoryRouter><LocalHelp /></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Open local help" }));
    expect(screen.getByText("Local help · not an AI response")).toBeVisible();
    expect(screen.getByRole("link", { name: "Learn" })).toHaveAttribute("href", "/learn");
    expect(screen.getByRole("link", { name: "Configure AI" })).toHaveAttribute("href", "/settings#llm");
  });
  it("starts with Developer off and records only explicit presentation opt-in", () => {
    localStorage.removeItem("flinttrade:developer:v1");
    render(<DeveloperPreference />);
    expect(developerEnabled()).toBe(false);
    fireEvent.click(screen.getByRole("checkbox", { name: "Enable Developer features" }));
    expect(developerEnabled()).toBe(true);
    expect(screen.getByText(/does not arm Live/)).toBeVisible();
  });
});
