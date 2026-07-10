/**
 * SentimentPanel.test.tsx
 *
 * Tests for the Market Sentiment Dashboard panel.
 * Covers: loading state, error state, gauge render, index cards,
 * sector grid, FII/DII card, key points, risks, and opportunities.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { MarketSummary } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Mocks — must be hoisted before component import
// ---------------------------------------------------------------------------

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
    tr: ({
      children,
      ...props
    }: React.HTMLAttributes<HTMLTableRowElement>) => (
      <tr {...props}>{children}</tr>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    stagger: (i: number) => ({ delay: i * 0.05 }),
    transitions: { tab: { duration: 0.2 } },
  },
}));

const mockGetMarketSentimentSummary = vi.fn();
const mockGetTickerSentiments = vi.fn();

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return {
    ...actual,
    getMarketSentimentSummary: () => mockGetMarketSentimentSummary(),
    getTickerSentiments: () => mockGetTickerSentiments(),
  };
});

// Static import must come AFTER vi.mock() calls
import SentimentPanel from "../SentimentPanel";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_SUMMARY: MarketSummary = {
  sentiment_score: 4.2,
  market_sentiment: "BULLISH",
  indices: [
    { name: "NIFTY 50", value: 24350.5, change_pct: 0.45, signal: "BUY" },
    { name: "BANK NIFTY", value: 52100.0, change_pct: -0.12, signal: "HOLD" },
  ],
  sectors: [
    {
      name: "IT",
      performance: "Outperforming",
      outlook: "Tech rally expected to continue.",
    },
    {
      name: "FMCG",
      performance: "Underperforming",
      outlook: "Margin pressure persists.",
    },
  ],
  key_points: [
    "FII buying supports upside",
    "IT sector leading the rally",
    "Global cues remain positive",
  ],
  fii_dii_flow: {
    fii_net: 1240.5,
    dii_net: -320.0,
    interpretation: "FII inflows dominating despite DII selling.",
  },
  risks: ["Rising crude oil prices", "Global recession fears"],
  opportunities: ["IT breakout setup", "Banking sector re-rating potential"],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPanel() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <SentimentPanel />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SentimentPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetTickerSentiments.mockResolvedValue({ tickers: [] });
  });

  it("renders the panel title", () => {
    mockGetMarketSentimentSummary.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByText("Market Sentiment Dashboard")).toBeInTheDocument();
  });

  it("shows loading spinner initially", () => {
    mockGetMarketSentimentSummary.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByText(/Generating market summary/i)).toBeInTheDocument();
  });

  it("renders sentiment score gauge on success", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("+4.2")).toBeInTheDocument();
    });
  });

  it("renders sentiment label badge on success", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("BULLISH")).toBeInTheDocument();
    });
  });

  it("renders index cards with name and change percent", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("NIFTY 50")).toBeInTheDocument();
      expect(screen.getByText("BANK NIFTY")).toBeInTheDocument();
    });
    expect(screen.getByText("+0.45%")).toBeInTheDocument();
    expect(screen.getByText("-0.12%")).toBeInTheDocument();
  });

  it("renders key points list", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByText("FII buying supports upside"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("IT sector leading the rally"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Global cues remain positive"),
      ).toBeInTheDocument();
    });
  });

  it("renders FII / DII flows section", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("FII / DII Flows")).toBeInTheDocument();
    });
  });

  it("labels disconnected FII/DII flows as unavailable", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue({
      ...MOCK_SUMMARY,
      fii_dii_flow: {
        fii_net: 0,
        dii_net: 0,
        interpretation: "FII/DII flow not connected; zero values are placeholders.",
      },
    });
    renderPanel();

    await waitFor(() => {
      expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    });
    expect(screen.queryByText("+₹0 Cr")).not.toBeInTheDocument();
  });

  it("renders sector performance grid", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("IT")).toBeInTheDocument();
      expect(screen.getByText("FMCG")).toBeInTheDocument();
      expect(screen.getByText("Outperforming")).toBeInTheDocument();
      expect(screen.getByText("Underperforming")).toBeInTheDocument();
    });
  });

  it("renders risk items", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Risks to Watch")).toBeInTheDocument();
      expect(screen.getByText("Rising crude oil prices")).toBeInTheDocument();
    });
  });

  it("renders opportunity items", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Opportunities")).toBeInTheDocument();
      expect(screen.getByText("IT breakout setup")).toBeInTheDocument();
    });
  });

  it("shows an honest 'coming soon' state on API failure", async () => {
    // The endpoint fails closed (e.g. 404 / no LLM configured); the panel
    // degrades to a calm preview placeholder, not a raw backend error.
    mockGetMarketSentimentSummary.mockRejectedValue(
      new Error("Backend unavailable"),
    );
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByText("Market sentiment coming soon"),
      ).toBeInTheDocument();
    });
    // Raw backend error message must not leak into the UI.
    expect(screen.queryByText("Backend unavailable")).not.toBeInTheDocument();
  });

  it("'Check again' button re-fetches after the coming-soon state", async () => {
    mockGetMarketSentimentSummary.mockRejectedValue(new Error("fail"));
    renderPanel();
    await waitFor(() => screen.getByText("Market sentiment coming soon"));
    expect(screen.getByText("Check again")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Check again"));
    // Refetch is triggered — mock gets called again
    await waitFor(() => {
      expect(mockGetMarketSentimentSummary).toHaveBeenCalledTimes(2);
    });
  });

  it("does not render risks section when risks array is empty", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue({
      ...MOCK_SUMMARY,
      risks: [],
    });
    renderPanel();
    await waitFor(() => screen.getByText("+4.2"));
    expect(screen.queryByText("Risks to Watch")).not.toBeInTheDocument();
  });

  it("does not render opportunities section when array is empty", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue({
      ...MOCK_SUMMARY,
      opportunities: [],
    });
    renderPanel();
    await waitFor(() => screen.getByText("+4.2"));
    expect(screen.queryByText("Opportunities")).not.toBeInTheDocument();
  });

  it("formats negative sentiment score with minus sign", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue({
      ...MOCK_SUMMARY,
      sentiment_score: -3.5,
      market_sentiment: "BEARISH" as const,
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("-3.5")).toBeInTheDocument();
    });
  });

  it("renders 'Key Points' section heading", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Key Points")).toBeInTheDocument();
    });
  });

  it("renders 'Sector Performance' section heading", async () => {
    mockGetMarketSentimentSummary.mockResolvedValue(MOCK_SUMMARY);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("Sector Performance")).toBeInTheDocument();
    });
  });
});
