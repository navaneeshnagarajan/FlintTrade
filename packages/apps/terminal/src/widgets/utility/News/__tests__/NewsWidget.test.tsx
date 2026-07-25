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

// Mock global fetch to avoid real RSS calls in the CORS proxy fallback
vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No network"));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import NewsWidget from "../NewsWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NewsWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Re-apply fetch mock after restoreAllMocks
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No network"));
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

  // The widget falls back to corsproxy.io when the operator's own backend is
  // unreachable. That is a reasonable degraded path, but the proxy sees their
  // IP and which feeds they read, so it must not happen silently.
  it("discloses when headlines came through the third-party proxy", async () => {
    const rss = `<rss><channel><item>
      <title>NIFTY ends higher</title>
      <link>https://example.test/a</link>
      <pubDate>Fri, 24 Jul 2026 10:00:00 +0530</pubDate>
    </item></channel></rss>`;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(rss, { status: 200 }),
    );

    render(<NewsWidget />);

    expect(await screen.findByText("Via proxy")).toBeInTheDocument();
  });

  it("shows no proxy badge when the backend serves the headlines", async () => {
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
});
