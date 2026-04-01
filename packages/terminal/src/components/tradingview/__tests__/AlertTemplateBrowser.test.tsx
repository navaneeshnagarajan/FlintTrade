/**
 * AlertTemplateBrowser.test.tsx
 *
 * Integration tests for the AlertTemplateBrowser component.
 * Covers:
 *  - Initial render with all templates visible
 *  - Category filter reduces the visible card set
 *  - "All" filter restores full list
 *  - Expand/collapse of a card
 *  - Copy button interaction (clipboard mock)
 *  - Pine Script snippet toggle
 *  - ARIA / accessibility attributes
 *  - Count badge updates on filter
 */

// import React from "react";
import { describe, it, expect, vi, beforeAll, afterAll } from "vitest";
import { render, screen, fireEvent, within, act } from "@testing-library/react";
import "@testing-library/jest-dom";

import { AlertTemplateBrowser } from "../AlertTemplateBrowser";
import { TV_ALERT_TEMPLATES } from "@/lib/tradingviewTemplates";

// ---------------------------------------------------------------------------
// Global stubs required by Radix / ScrollArea
// ---------------------------------------------------------------------------

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  // Mock clipboard
  Object.assign(navigator, {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
    },
  });
});

afterAll(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderBrowser() {
  return render(<AlertTemplateBrowser scrollHeight="800px" />);
}

// ---------------------------------------------------------------------------
// Initial render
// ---------------------------------------------------------------------------

describe("AlertTemplateBrowser — initial render", () => {
  it("renders the section heading", () => {
    renderBrowser();
    expect(
      screen.getByRole("heading", { name: /Alert Template Library/i })
    ).toBeInTheDocument();
  });

  it("renders one card per template in the catalogue", () => {
    renderBrowser();
    // Each card title is the template name — find by webhook icon + name
    for (const t of TV_ALERT_TEMPLATES) {
      expect(screen.getByText(t.name)).toBeInTheDocument();
    }
  });

  it("shows correct count label for all 10 templates", () => {
    renderBrowser();
    expect(screen.getByText("10 templates")).toBeInTheDocument();
  });

  it("'All' filter pill is active by default", () => {
    renderBrowser();
    const allPill = screen.getByRole("button", { name: /^all$/i });
    expect(allPill).toHaveAttribute("aria-pressed", "true");
  });

  it("has accessible region label", () => {
    renderBrowser();
    expect(
      screen.getByRole("region", { name: /TradingView Alert Template Browser/i })
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Category filtering
// ---------------------------------------------------------------------------

describe("AlertTemplateBrowser — category filtering", () => {
  it("clicking 'trend' shows only trend templates", () => {
    renderBrowser();
    fireEvent.click(screen.getByRole("button", { name: /^trend$/i }));

    const trendTemplates = TV_ALERT_TEMPLATES.filter(
      (t) => t.category === "trend"
    );
    const nonTrendTemplate = TV_ALERT_TEMPLATES.find(
      (t) => t.category !== "trend"
    )!;

    trendTemplates.forEach((t) =>
      expect(screen.getByText(t.name)).toBeInTheDocument()
    );
    expect(screen.queryByText(nonTrendTemplate.name)).not.toBeInTheDocument();
  });

  it("clicking 'options' shows only options templates", () => {
    renderBrowser();
    fireEvent.click(screen.getByRole("button", { name: /^options$/i }));

    const optionsTemplates = TV_ALERT_TEMPLATES.filter(
      (t) => t.category === "options"
    );
    const nonOption = TV_ALERT_TEMPLATES.find((t) => t.category !== "options")!;

    optionsTemplates.forEach((t) =>
      expect(screen.getByText(t.name)).toBeInTheDocument()
    );
    expect(screen.queryByText(nonOption.name)).not.toBeInTheDocument();
  });

  it("clicking 'All' after filtering restores all templates", () => {
    renderBrowser();
    fireEvent.click(screen.getByRole("button", { name: /^trend$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^all$/i }));

    expect(screen.getAllByText(/BUY|SELL|RSI|MACD|Bollinger|VWAP|ORB|Straddle|Custom|SuperTrend/i).length).toBeGreaterThan(0);
    expect(screen.getByText("10 templates")).toBeInTheDocument();
  });

  it("active filter pill has aria-pressed=true", () => {
    renderBrowser();
    fireEvent.click(screen.getByRole("button", { name: /^momentum$/i }));

    const momentumPill = screen.getByRole("button", { name: /^momentum$/i });
    expect(momentumPill).toHaveAttribute("aria-pressed", "true");

    const allPill = screen.getByRole("button", { name: /^all$/i });
    expect(allPill).toHaveAttribute("aria-pressed", "false");
  });

  it("count label updates after filtering", () => {
    renderBrowser();
    fireEvent.click(screen.getByRole("button", { name: /^options$/i }));

    const optionsCount = TV_ALERT_TEMPLATES.filter(
      (t) => t.category === "options"
    ).length;
    expect(
      screen.getByText(
        new RegExp(`${optionsCount} template${optionsCount !== 1 ? "s" : ""}`)
      )
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Card expand / collapse
// ---------------------------------------------------------------------------

describe("AlertTemplateBrowser — card expand/collapse", () => {
  it("JSON body is hidden before expanding", () => {
    renderBrowser();
    // The first template is SuperTrend — find its card
    const card = screen.getByText("SuperTrend BUY / SELL").closest("[data-slot='card']")!;
    const body = card.querySelector("[id^='tv-template-body-']") as HTMLElement;
    expect(body).toHaveClass("hidden");
  });

  it("clicking 'View JSON' reveals the webhook JSON", () => {
    renderBrowser();
    const card = screen.getByText("SuperTrend BUY / SELL").closest("[data-slot='card']")!;
    const viewBtn = within(card as HTMLElement).getByRole("button", {
      name: /View JSON/i,
    });
    fireEvent.click(viewBtn);

    const body = card.querySelector("[id^='tv-template-body-']") as HTMLElement;
    expect(body).not.toHaveClass("hidden");
  });

  it("clicking 'Collapse' hides the body again", () => {
    renderBrowser();
    const card = screen.getByText("SuperTrend BUY / SELL").closest("[data-slot='card']")!;
    const viewBtn = within(card as HTMLElement).getByRole("button", {
      name: /View JSON/i,
    });
    fireEvent.click(viewBtn);
    // Now it shows "Collapse"
    const collapseBtn = within(card as HTMLElement).getByRole("button", {
      name: /Collapse/i,
    });
    fireEvent.click(collapseBtn);

    const body = card.querySelector("[id^='tv-template-body-']") as HTMLElement;
    expect(body).toHaveClass("hidden");
  });

  it("expanded card shows placeholders badges", () => {
    renderBrowser();
    const card = screen.getByText("SuperTrend BUY / SELL").closest("[data-slot='card']")!;
    fireEvent.click(
      within(card as HTMLElement).getByRole("button", { name: /View JSON/i })
    );
    expect(within(card as HTMLElement).getByText("{{ticker}}")).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("{{exchange}}")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Copy button
// ---------------------------------------------------------------------------

describe("AlertTemplateBrowser — copy button", () => {
  it("Copy JSON button is present on each card", () => {
    renderBrowser();
    const copyBtns = screen.getAllByRole("button", { name: /Copy webhook JSON/i });
    expect(copyBtns).toHaveLength(TV_ALERT_TEMPLATES.length);
  });

  it("clicking Copy JSON calls navigator.clipboard.writeText", async () => {
    renderBrowser();
    const copyBtns = screen.getAllByRole("button", { name: /Copy webhook JSON/i });

    await act(async () => {
      fireEvent.click(copyBtns[0]);
      // Flush the clipboard promise
      await Promise.resolve();
    });

    expect(navigator.clipboard.writeText).toHaveBeenCalledOnce();
    const calledWith = (navigator.clipboard.writeText as ReturnType<typeof vi.fn>).mock
      .calls[0][0] as string;
    // Should be a valid JSON string with at least "action" key
    expect(calledWith).toContain('"action"');
  });
});

// ---------------------------------------------------------------------------
// Pine Script toggle
// ---------------------------------------------------------------------------

describe("AlertTemplateBrowser — Pine Script snippet", () => {
  it("Pine Script button appears on templates that have a pineSnippet", () => {
    renderBrowser();
    // SuperTrend has a Pine snippet
    const card = screen.getByText("SuperTrend BUY / SELL").closest("[data-slot='card']")!;
    expect(
      within(card as HTMLElement).getByRole("button", { name: /Pine Script/i })
    ).toBeInTheDocument();
  });

  it("Pine Script section is hidden before clicking", () => {
    renderBrowser();
    const card = screen.getByText("SuperTrend BUY / SELL").closest("[data-slot='card']")!;
    // Must expand card first to see Pine button
    fireEvent.click(
      within(card as HTMLElement).getByRole("button", { name: /View JSON/i })
    );
    const pineSection = card.querySelector("[id^='tv-template-pine-']") as HTMLElement;
    expect(pineSection).toHaveClass("hidden");
  });

  it("clicking Pine Script reveals the snippet", () => {
    renderBrowser();
    const card = screen.getByText("SuperTrend BUY / SELL").closest("[data-slot='card']")!;
    fireEvent.click(
      within(card as HTMLElement).getByRole("button", { name: /View JSON/i })
    );
    fireEvent.click(
      within(card as HTMLElement).getByRole("button", { name: /Pine Script/i })
    );
    const pineSection = card.querySelector("[id^='tv-template-pine-']") as HTMLElement;
    expect(pineSection).not.toHaveClass("hidden");
    expect(pineSection.textContent).toContain("ta.supertrend");
  });

  it("Custom JSON template has no Pine Script button (no snippet)", () => {
    renderBrowser();
    const card = screen
      .getByText("Custom JSON Template")
      .closest("[data-slot='card']")!;
    expect(
      within(card as HTMLElement).queryByRole("button", { name: /Pine Script/i })
    ).not.toBeInTheDocument();
  });
});
