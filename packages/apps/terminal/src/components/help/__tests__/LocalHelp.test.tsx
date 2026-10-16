import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { LocalHelp } from "../LocalHelp";
import { HelpFooterProvider, HelpFooterSlot } from "../HelpFooter";
import { DeveloperPreference, developerEnabled } from "@/chrome/DeveloperPreference";

describe("installed optional presentation", () => {
  it("places the existing Help action inside the shell footer and retains the open dialog when that slot leaves", () => {
    function Surface({ shell }: { shell: boolean }) {
      return <HelpFooterProvider><MemoryRouter>
        {shell && <footer data-testid="footer"><HelpFooterSlot /></footer>}
        <LocalHelp />
      </MemoryRouter></HelpFooterProvider>;
    }
    const view = render(<Surface shell />);
    fireEvent.click(within(screen.getByTestId("footer")).getByRole("button", { name: "Open local help" }));
    expect(screen.getByRole("dialog", { name: "Local help · not an AI response" })).toBeVisible();
    view.rerender(<Surface shell={false} />);
    expect(screen.getByRole("dialog", { name: "Local help · not an AI response" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("button", { name: "Open local help" })).toBeVisible();
    view.rerender(<Surface shell />);
    expect(within(screen.getByTestId("footer")).getByRole("button", { name: "Open local help" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Open local help" })).toHaveLength(1);
  });
  it.each(["/welcome", "/setup", "/setup-account", "/missing"])("retains local Help without app chrome at %s", route => {
    render(<HelpFooterProvider><MemoryRouter initialEntries={[route]}><LocalHelp /></MemoryRouter></HelpFooterProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Open local help" }));
    expect(screen.getByRole("dialog", { name: "Local help · not an AI response" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Configure AI" })).toHaveAttribute("href", "/settings#llm");
  });
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
