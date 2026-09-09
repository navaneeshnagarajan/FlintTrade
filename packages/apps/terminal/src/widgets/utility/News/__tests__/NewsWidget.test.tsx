/**
 * NewsWidget.test.tsx
 *
 * Tests for the News feed widget.
 * Verifies rendering, sentiment filter tabs, and search input.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Mock ftApi.getNews to avoid real network calls
vi.mock("@/services/ftApi", () => ({
  getNews: vi.fn().mockRejectedValue(new Error("No backend")),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import NewsWidget from "../NewsWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NewsWidget", () => {
  beforeEach(async () => {
    vi.restoreAllMocks();
    const { getNews } = await import("@/services/ftApi");
    vi.mocked(getNews).mockReset().mockRejectedValue(new Error("No backend"));
  });

  it("renders without crashing", () => {
    render(<NewsWidget />);
    expect(screen.getByText("News")).toBeInTheDocument();
  });

  it("shows sentiment filter tabs", () => {
    render(<NewsWidget />);
    expect(screen.getByText("All")).toBeInTheDocument();
    expect(screen.getByText("Bullish")).toBeInTheDocument();
    expect(screen.getByText("Bearish")).toBeInTheDocument();
    expect(screen.getByText("Neutral")).toBeInTheDocument();
  });

  it("shows search input with placeholder", () => {
    render(<NewsWidget />);
    expect(
      screen.getByPlaceholderText("Search headlines, sources..."),
    ).toBeInTheDocument();
  });

  it("reports backend unavailability without browser fetching a feed", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(<NewsWidget />);

    expect(await screen.findByText("News is unavailable from the FlintTrade backend.")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByText("Via proxy")).not.toBeInTheDocument();
  });

  it("reports an empty backend response as unavailable without browser fetching", async () => {
    const { getNews } = await import("@/services/ftApi");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    vi.mocked(getNews).mockResolvedValue({ articles: [] });

    render(<NewsWidget />);

    expect(await screen.findByText("News is unavailable from the FlintTrade backend.")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByText("Via proxy")).not.toBeInTheDocument();
  });

  it("shows backend headlines without a proxy attribution", async () => {
    const { getNews } = await import("@/services/ftApi");
    vi.mocked(getNews).mockResolvedValue({
      articles: [
        {
          title: "NIFTY ends higher",
          link: "https://example.test/a",
          source: "MoneyControl",
          pub_date: "Fri, 24 Jul 2026 10:00:00 +0530",
        },
      ],
    });

    render(<NewsWidget />);

    expect(await screen.findByText("NIFTY ends higher")).toBeInTheDocument();
    expect(screen.queryByText("Via proxy")).not.toBeInTheDocument();
  });

  it("clears a successful backend result when a manual refresh fails", async () => {
    const { getNews } = await import("@/services/ftApi");
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    vi.mocked(getNews)
      .mockResolvedValueOnce({
        articles: [{
          title: "NIFTY ends higher",
          link: "https://example.test/a",
          source: "MoneyControl",
          pub_date: "Fri, 24 Jul 2026 10:00:00 +0530",
        }],
      })
      .mockRejectedValueOnce(new Error("Backend unavailable"));

    render(<NewsWidget />);

    expect(await screen.findByText("NIFTY ends higher")).toBeInTheDocument();
    expect(screen.getByText("0s ago")).toBeInTheDocument();
    screen.getByTitle("Refresh news").click();

    expect(await screen.findByText("News is unavailable from the FlintTrade backend.")).toBeInTheDocument();
    expect(screen.queryByText("NIFTY ends higher")).not.toBeInTheDocument();
    expect(screen.queryByText("0s ago")).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByText("Via proxy")).not.toBeInTheDocument();
  });
});
