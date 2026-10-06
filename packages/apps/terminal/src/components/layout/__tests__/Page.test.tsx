import { useState } from "react";
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Page, PageBody, PageHeader, PageTabs } from "../Page";

type TabId = "overview" | "holdings" | "tax";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "holdings", label: "Holdings" },
  { id: "tax", label: "Tax" },
] as const;

function TabsHarness({ onChange }: { onChange?: (id: TabId) => void }) {
  const [value, setValue] = useState<TabId>("overview");
  return (
    <PageTabs<TabId>
      tabs={TABS}
      value={value}
      onChange={(id) => {
        setValue(id);
        onChange?.(id);
      }}
      label="Invest sections"
      idPrefix="invest"
    />
  );
}

describe("PageHeader", () => {
  it("renders the title as the page's only H1 with its description", () => {
    render(<PageHeader title="Invest" description="Your holdings and wealth tools." />);
    const heading = screen.getByRole("heading", { level: 1, name: "Invest" });
    expect(heading).toBeInTheDocument();
    expect(screen.getByText("Your holdings and wealth tools.")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("renders actions, meta chips and a secondary navigation slot", () => {
    render(
      <PageHeader
        title="Accounts"
        meta={<span>3 connected</span>}
        actions={<button type="button">Connect broker</button>}
      >
        <nav aria-label="Account sections" />
      </PageHeader>,
    );
    expect(screen.getByText("3 connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect broker" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Account sections" })).toBeInTheDocument();
  });

  it("uses the shared page gutter token", () => {
    render(<PageHeader title="Home" />);
    expect(screen.getByTestId("page-header").className).toContain("px-[var(--ft-page-gutter)]");
  });
});

describe("PageTabs", () => {
  it("exposes an ARIA tablist with linked ids and one tab stop", () => {
    render(<TabsHarness />);
    const tablist = screen.getByRole("tablist", { name: "Invest sections" });
    expect(tablist).toHaveAttribute("aria-orientation", "horizontal");
    const overview = screen.getByRole("tab", { name: "Overview" });
    expect(overview).toHaveAttribute("id", "invest-tab-overview");
    expect(overview).toHaveAttribute("aria-controls", "invest-tabpanel-overview");
    expect(overview).toHaveAttribute("aria-selected", "true");
    expect(overview).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Holdings" })).toHaveAttribute("tabindex", "-1");
  });

  it("moves and activates with arrow, Home and End keys", () => {
    const onChange = vi.fn();
    render(<TabsHarness onChange={onChange} />);
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();

    fireEvent.keyDown(overview, { key: "ArrowRight" });
    const holdings = screen.getByRole("tab", { name: "Holdings" });
    expect(holdings).toHaveFocus();
    expect(holdings).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(holdings, { key: "End" });
    expect(screen.getByRole("tab", { name: "Tax" })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("tab", { name: "Tax" }), { key: "ArrowRight" });
    expect(overview).toHaveFocus();

    fireEvent.keyDown(overview, { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Tax" })).toHaveFocus();

    expect(onChange.mock.calls.map(([id]) => id)).toEqual(["holdings", "tax", "overview", "tax"]);
  });

  it("activates a tab on click", () => {
    render(<TabsHarness />);
    fireEvent.click(screen.getByRole("tab", { name: "Tax" }));
    expect(screen.getByRole("tab", { name: "Tax" })).toHaveAttribute("aria-selected", "true");
  });

  it("points every group tab at the one shared panel when given a panelId", () => {
    render(
      <PageTabs<TabId>
        tabs={TABS}
        value="holdings"
        onChange={() => undefined}
        label="Invest sections"
        idPrefix="invest-group"
        panelId="invest-tabpanel-sip"
      />,
    );
    for (const tab of screen.getAllByRole("tab")) {
      expect(tab).toHaveAttribute("aria-controls", "invest-tabpanel-sip");
    }
    expect(screen.getByRole("tab", { name: "Holdings" })).toHaveAttribute("id", "invest-group-tab-holdings");
  });

  it("renders a smaller secondary row for views inside a group", () => {
    render(
      <PageTabs<TabId>
        tabs={TABS}
        value="overview"
        onChange={() => undefined}
        label="Overview views"
        idPrefix="invest"
        variant="secondary"
      />,
    );
    const classes = (name: string) => screen.getByRole("tab", { name }).className.split(/\s+/);
    expect(classes("Overview")).toEqual(expect.arrayContaining(["h-8", "text-xs", "bg-surface-hover"]));
    expect(classes("Overview")).not.toContain("border-b-2");
    expect(classes("Holdings")).not.toContain("bg-surface-hover");
    expect(screen.getByRole("tablist", { name: "Overview views" })).toBeInTheDocument();
  });
});

describe("PageBody", () => {
  it("is the scroll container and constrains content to the chosen width", () => {
    render(
      <Page data-testid="page">
        <PageBody width="narrow" data-testid="body">
          <p>Content</p>
        </PageBody>
      </Page>,
    );
    const body = screen.getByTestId("body");
    expect(body.className).toContain("overflow-y-auto");
    const column = body.firstElementChild as HTMLElement;
    expect(column.className).toContain("max-w-[var(--ft-page-width-narrow)]");
    expect(column.className).toContain("px-[var(--ft-page-gutter)]");
    expect(screen.getByTestId("page").className).toContain("h-full");
  });

  it("drops the gutter for edge-to-edge tools", () => {
    render(
      <PageBody padded={false} width="full" data-testid="body">
        <p>Canvas</p>
      </PageBody>,
    );
    const column = screen.getByTestId("body").firstElementChild as HTMLElement;
    expect(column.className).not.toContain("px-[var(--ft-page-gutter)]");
    expect(column.className).toContain("max-w-none");
  });

  it("forwards tabpanel semantics", () => {
    render(
      <PageBody role="tabpanel" id="invest-tabpanel-overview" aria-labelledby="invest-tab-overview">
        <p>Panel</p>
      </PageBody>,
    );
    expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "invest-tabpanel-overview");
  });
});
